"""Work queue, follow-ups, appointments, AI analysis and drafts."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.models import Lead


def test_work_queue_sections_and_overdue_sorting(client, make_lead):
    make_lead(name="Fresh Lead", stage="new", contact_status="never_contacted")
    aged = make_lead(
        name="Aged Lead",
        stage="new",
        contact_status="never_contacted",
        created_at=datetime.utcnow() - timedelta(hours=6),
    )
    overdue = make_lead(name="Late Lead", stage="contacted", contact_status="spoke_with_seller")
    client.post(
        "/api/followups",
        json={
            "lead_id": overdue.id,
            "due_at": (datetime.utcnow() - timedelta(days=3)).isoformat(),
            "reason": "Seller asked for a call back",
            "priority": 5,
        },
    )

    queue = client.get("/api/work-queue").json()
    keys = [s["key"] for s in queue["sections"]]
    assert keys == [
        "overdue",
        "due_today",
        "new_not_contacted",
        "callbacks_requested",
        "appointments_today",
        "offers_awaiting_response",
        "negotiations_requiring_attention",
        "upcoming",
        "unscheduled",
        "missing_critical",
    ]
    overdue_section = next(s for s in queue["sections"] if s["key"] == "overdue")
    assert overdue_section["tasks"], "overdue follow-up should be surfaced"
    assert overdue_section["tasks"][0]["lead_id"] == overdue.id

    new_section = next(s for s in queue["sections"] if s["key"] == "new_not_contacted")
    aged_task = next((t for t in new_section["tasks"] if t["lead_id"] == aged.id), None)
    assert aged_task, "leads past the grace period must be surfaced"
    assert aged_task["suggested_next_action"]

    stats = client.get("/api/work-queue/stats").json()
    assert set(stats) == {"completed", "total", "rate", "definition"}
    assert "follow-ups" in stats["definition"]


def test_followup_lifecycle_never_claims_a_message_was_sent(client, make_lead):
    lead = make_lead(name="Rita Owens", contact_status="never_contacted")
    created = client.post(
        "/api/followups",
        json={
            "lead_id": lead.id,
            "due_at": (datetime.utcnow() + timedelta(hours=2)).isoformat(),
            "reason": "First touch",
            "priority": 4,
        },
    )
    assert created.status_code == 201
    followup = created.json()
    assert followup["status"] == "open"

    completed = client.post(
        f"/api/followups/{followup['id']}/complete",
        json={"outcome": "connected", "notes": "Spoke with seller"},
    )
    assert completed.status_code == 200
    body = completed.json()
    assert "No message was sent" in body["note"]
    assert body["followup"]["status"] == "completed"
    assert body["followup"]["completion_outcome"] == "connected"

    again = client.post(f"/api/followups/{followup['id']}/complete", json={"outcome": "connected"})
    assert again.status_code == 400
    assert "already closed" in again.json()["detail"]

    bad = client.post(
        f"/api/followups/{followup['id']}/cancel",
        params={"reason": "no longer needed"},
    )
    assert bad.status_code in {200, 400}


def test_unknown_completion_outcome_is_rejected(client, make_lead):
    lead = make_lead(name="Validation Lead")
    followup = client.post(
        "/api/followups",
        json={"lead_id": lead.id, "due_at": datetime.utcnow().isoformat()},
    ).json()
    response = client.post(f"/api/followups/{followup['id']}/complete", json={"outcome": "made_up"})
    assert response.status_code == 400
    assert "Unknown outcome" in response.json()["detail"]


def test_completion_outcome_can_set_do_not_contact(client, make_lead):
    lead = make_lead(name="No Call Please")
    followup = client.post(
        "/api/followups",
        json={"lead_id": lead.id, "due_at": datetime.utcnow().isoformat()},
    ).json()
    client.post(f"/api/followups/{followup['id']}/complete", json={"outcome": "do_not_contact"})

    detail = client.get(f"/api/leads/{lead.id}").json()
    assert detail["do_not_contact"] is True

    open_after = client.get("/api/followups", params={"lead_id": lead.id, "status": "open"}).json()
    assert open_after["total"] == 0, "DNC must cancel open follow-ups"

    queue = client.get("/api/work-queue").json()
    for section in queue["sections"]:
        assert all(t["lead_id"] != lead.id for t in section["tasks"]), "DNC leads stay out of outreach queues"


def test_appointment_create_and_update(client, make_lead):
    lead = make_lead(name="Walkthrough Seller")
    created = client.post(
        "/api/appointments",
        json={
            "lead_id": lead.id,
            "scheduled_at": (datetime.utcnow() + timedelta(days=2)).isoformat(),
            "appointment_type": "property walkthrough",
        },
    )
    assert created.status_code == 201
    appt = created.json()
    assert appt["status"] == "scheduled"

    updated = client.patch(
        f"/api/appointments/{appt['id']}",
        json={"status": "kept", "notes": "Saw the roof needs work"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "kept"
    assert updated.json()["notes"] == "Saw the roof needs work"

    listed = client.get("/api/appointments").json()
    assert listed["total"] == 1


def test_ai_status_and_rule_based_analysis(client, make_lead, db):
    lead = make_lead(
        name="Motivated Seller",
        notes="Foreclosure timeline is 3 weeks and I am a tired landlord with two tenants.",
        stage="contacted",
        contact_status="spoke_with_seller",
    )
    status = client.get("/api/ai/status").json()
    assert status["engine"] in {"rules", "ollama"}
    assert "disclaimer" in status or status["available"] in {True, False}

    insight = client.post(f"/api/ai/analyze/{lead.id}").json()
    assert insight["engine"] in {"rules", "ollama"}
    assert insight["summary"]
    assert insight["missing_information"], "unknowns must be reported explicitly"
    if insight["engine"] == "rules":
        assert insight["confidence"] in {"low", "medium"}
        assert any("Foreclosure" in m or "foreclosure" in m.lower() for m in [insight["seller_motivation"]])

    second = client.post(f"/api/ai/analyze/{lead.id}").json()
    assert second["id"] == insight["id"], "unchanged context must not be re-analyzed"


def test_ai_batch_analysis_counts_and_skips(client, make_lead):
    make_lead(name="Batch One", stage="new")
    make_lead(name="Batch Two", stage="new")
    result = client.post("/api/ai/analyze-batch").json()
    assert result["analyzed"] + result["skipped"] >= 2

    again = client.post("/api/ai/analyze-batch").json()
    assert again["analyzed"] == 0, "unchanged leads are skipped"
    assert again["skipped"] >= 2


def test_background_batch_runs_and_reports_progress(client, make_lead):
    import time

    make_lead(name="Background One", stage="new")
    started = client.post("/api/ai/analyze-batch?background=true").json()
    assert started["running"] is True

    state = started
    for _ in range(100):
        state = client.get("/api/ai/analyze-progress").json()
        if not state["running"] and state["finished_at"]:
            break
        time.sleep(0.1)
    assert state["error"] is None, state["error"]
    assert state["done"] >= 1, "background worker processed the queue"
    assert state["groq"] + state["rules"] + state["skipped"] == state["done"]


def test_draft_refused_for_do_not_contact_lead(client, make_lead):
    lead = make_lead(name="DNC Seller", do_not_contact=True, stage="contacted")
    draft = client.post(f"/api/ai/draft/{lead.id}", json={"channel": "text"}).json()
    assert draft["body"] == ""
    assert draft["refusal_reason"]
    assert "Do Not Contact" in draft["refusal_reason"]


def test_draft_refused_when_context_is_insufficient(client, db):
    lead = Lead(origin="manual", pipeline_stage="new", contact_status="never_contacted")
    db.add(lead)
    db.commit()
    draft = client.post(f"/api/ai/draft/{lead.id}", json={"channel": "text"}).json()
    assert draft["refusal_reason"]
    assert "Not enough" in draft["refusal_reason"]


def test_draft_is_stored_not_sent(client, make_lead):
    lead = make_lead(name="Barbara", email="barbara@example.com", address="412 Sycamore St")
    draft = client.post(f"/api/ai/draft/{lead.id}", json={"channel": "text"}).json()
    assert draft["id"]
    assert draft["body"], "a usable draft body should be produced"
    assert draft.get("sent_at") in {None, ""}
    assert draft["refusal_reason"] in {None, ""}

    fetched = client.get(f"/api/ai/drafts/{draft['id']}").json()
    assert fetched["body"] == draft["body"]

    edited = client.patch(
        f"/api/ai/drafts/{draft['id']}",
        json={"edited_body": "Human reviewed and rewritten draft."},
    )
    assert edited.json()["edited_body"] == "Human reviewed and rewritten draft."
    assert edited.json()["body"] == draft["body"], "the original AI draft must be preserved"

    confirmation = client.get("/api/ai/no-send-confirmation").json()
    assert confirmation["sends_messages"] is False


def test_generation_failure_puts_model_in_cooldown(client, make_lead):
    from app.services import ai_service

    ai_service._note_generation_failure("HTTP 500: out of memory during startup")
    try:
        status = client.get("/api/ai/status").json()
        assert status["available"] is False
        assert status["engine"] == "rules"
        assert "after a failure" in status["error"]
        assert "out of memory" in status["error"]

        lead = make_lead(name="Cooldown Lead", notes="Foreclosure timeline is 2 weeks.")
        insight = client.post(f"/api/ai/analyze/{lead.id}").json()
        assert insight["engine"] == "rules", "no model call is attempted while cooling down"
    finally:
        ai_service._clear_generation_failures()

    assert client.get("/api/ai/status").json()["error"] != status["error"] or status["available"] is False


def test_ollama_request_uses_configured_context_window(monkeypatch):
    from app.config import settings
    from app.services import ai_service

    captured: dict = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):  # noqa: ANN001
            return None

        def json(self):
            return {"response": '{"summary": "ok"}'}

    class FakeClient:
        def __init__(self, timeout=None):  # noqa: ANN001
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None, **kwargs):  # noqa: A002
            captured.update(json or {})
            return FakeResponse()

    monkeypatch.setattr(ai_service.httpx, "Client", FakeClient)
    result = ai_service._ollama_generate("prompt", "test-model")

    assert result == '{"summary": "ok"}'
    assert captured["options"]["num_ctx"] == int(settings.ollama_num_ctx)
    assert captured["format"] == "json"
    assert ai_service._cooldown_reason() is None


def test_disabled_local_ai_reports_an_actionable_message(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ai_enabled", False)
    status = client.get("/api/ai/status").json()

    assert status["available"] is False
    assert status["engine"] == "rules"
    assert "AI_ENABLED=false" in status["message"]
    assert "backend/.env" in status["message"]
    assert "sellers" in status["disclaimer"]
