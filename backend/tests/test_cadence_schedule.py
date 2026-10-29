"""Cadence scheduling (1.5.1): the runner is reachable, visible and pausable.

The cadence only ever prepares drafts and tasks. These tests prove the three things a
user needs from it: a way to start it, a way to see it, and a reason to trust that it
stops itself when the facts say it should.
"""

from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.models import LeadSequenceState, Message, Task
from app.services import sequences, templates
from app.services.imports import create_local_lead

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)


def _lead(db, **extra):
    data = {
        "full_name": "Dana Seller",
        "primary_phone": "+12025550143",
        "street_address": "1000 Oak Ridge Dr",
        "city": "Arlington",
        "state": "TX",
        "zip_code": "76015",
        "county": "Tarrant",
        "in_license": True,
        "normalized_address": "1000oakridgedr|arlington|tx|76015",
        "external_id": "ds:1000oakridgedr|arlington|tx|76015",
        "outreach_mode": "cold",
        "needs_skip_trace": False,
        "source_do_not_contact": False,
        "stage_code": "not_contacted",
        **extra,
    }
    lead = create_local_lead(db, data, data, source_kind="import")
    db.commit()
    return lead


def _clean(db, lead):
    """Record the evidence-based restriction review a real draft needs."""
    lead.restriction_reviewed = True
    lead.restriction_evidence = "Reviewed locally before contact"
    lead.local_do_not_contact = False
    db.commit()
    return lead


def test_the_scheduler_actually_registers_the_cadence_runner(db):
    from app.scheduler import configure_scheduler, scheduler

    configure_scheduler(db)
    try:
        job = scheduler.get_job("cadence_runner")
        assert job is not None, "the cadence runner must be scheduled, not just callable"
        assert scheduler.get_job("nightly_backup") is not None
        assert scheduler.get_job("crm_sync") is None  # sync is off in the test settings
    finally:
        for job_id in ("cadence_runner", "nightly_backup", "crm_sync"):
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)


def test_the_cadence_runner_can_be_switched_off(db, monkeypatch):
    from app.scheduler import configure_scheduler, scheduler

    settings = get_settings()
    monkeypatch.setattr(settings, "cadence_enabled", False)
    configure_scheduler(db)
    try:
        assert scheduler.get_job("cadence_runner") is None
    finally:
        for job_id in ("cadence_runner", "nightly_backup", "crm_sync"):
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)


def test_starting_and_reading_the_cadence_through_the_api(client, db):
    templates.seed_templates(db)
    lead = _lead(db)

    before = client.get(f"/api/leads/{lead.id}/sequence").json()
    assert before["status"] == "not_started"
    assert before["cadence_days"] == [0, 3, 7, 14, 30, 60, 90, 120]
    assert before["never_sent"] is True

    started = client.post(f"/api/leads/{lead.id}/sequence/start")
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "active"

    state = client.get(f"/api/leads/{lead.id}/sequence").json()
    assert state["active"] is True
    assert state["current_step"] == 0
    assert state["total_steps"] == 8
    assert state["next_due_at"] is not None
    assert [step["day_offset"] for step in state["steps"]] == [0, 3, 7, 14, 30, 60, 90, 120]

    summary = client.get("/api/sequences/summary").json()
    assert summary["active"] == 1
    assert summary["never_sent"] is True


def test_pausing_stops_the_cadence_and_keeps_a_reason(client, db):
    templates.seed_templates(db)
    lead = _lead(db)
    client.post(f"/api/leads/{lead.id}/sequence/start")

    paused = client.post(f"/api/leads/{lead.id}/sequence/pause")
    assert paused.status_code == 200
    assert paused.json()["paused"] == 1

    state = client.get(f"/api/leads/{lead.id}/sequence").json()
    assert state["active"] is False
    assert state["status"] == "stopped"
    assert state["stop_reason"] == "paused_by_user"
    # Pausing twice is harmless and reports nothing to do.
    assert client.post(f"/api/leads/{lead.id}/sequence/pause").json()["paused"] == 0


def test_the_due_runner_prepares_a_draft_and_a_task_but_never_sends(client, db):
    templates.seed_templates(db)
    lead = _clean(db, _lead(db))
    client.post(f"/api/leads/{lead.id}/sequence/start")

    result = client.post("/api/sequences/run-due")
    assert result.status_code == 200, result.text
    body = result.json()
    drafted = [item for item in body["items"] if item.get("status") == "drafted"]
    assert drafted, body

    message = db.get(Message, drafted[0]["message_id"])
    assert message.status == "DRAFT"
    assert message.direction == "outbound"
    assert message.validator_result["ok"] is True

    task = db.get(Task, drafted[0]["task_id"])
    assert task.source == "cadence"
    assert "Nothing was sent" in task.description

    state = client.get(f"/api/leads/{lead.id}/sequence").json()
    assert state["current_step"] == 1
    assert datetime.fromisoformat(state["next_due_at"]) > datetime.now(timezone.utc)
    # Running again the same day does nothing: the next step is days away.
    again = client.post("/api/sequences/run-due").json()
    assert not [item for item in again["items"] if item.get("lead_id") == lead.id]


def test_the_runner_stops_instead_of_drafting_for_a_suppressed_lead(db):
    templates.seed_templates(db)
    lead = _clean(db, _lead(db))
    state = sequences.start_sequence(db, lead)
    lead.local_do_not_contact = True
    db.commit()

    items = sequences.runner_due_today(db, NOW + timedelta(days=1))
    db.refresh(state)
    assert state.status == "stopped"
    assert state.stop_reason == "dnc"
    assert not [item for item in items if item.get("status") == "drafted"]


def test_a_reply_stops_the_next_run_without_deleting_anything(db):
    templates.seed_templates(db)
    lead = _clean(db, _lead(db))
    state = sequences.start_sequence(db, lead)
    assert state.status == "active"
    db.add(Message(lead_id=lead.id, direction="inbound", body="STOP", status="RECEIVED"))
    db.commit()

    sequences.runner_due_today(db, NOW + timedelta(days=4))
    db.refresh(state)
    assert state.status == "stopped" and state.stop_reason == "replied"
    # The earlier state row is kept: this is a record, not a scratch pad.
    assert db.query(LeadSequenceState).filter(LeadSequenceState.lead_id == lead.id).count() == 1
