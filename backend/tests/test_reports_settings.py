"""Dashboard metrics, reports, exports, settings and audit."""
from __future__ import annotations

from datetime import datetime, timedelta


def test_dashboard_metrics_shape(client, make_lead):
    make_lead(name="Fresh Lead", stage="new", contact_status="never_contacted")
    make_lead(name="In Play", stage="contacted", contact_status="spoke_with_seller")

    body = client.get("/api/dashboard/metrics").json()
    assert body["total_leads"] >= 2
    assert body["tiles"]["never_contacted_tile"]["count"] >= 1
    assert body["tiles"]["total_leads"]["count"] == body["total_leads"]
    assert isinstance(body["pipeline"], dict)
    assert body["generated_at"]


def test_reports_summary_denominators_are_explicit(client, make_lead):
    make_lead(name="Report Lead", stage="qualified", contact_status="qualified")
    body = client.get("/api/reports/summary").json()

    conversion = body["conversion"]
    for key in ("contact_rate", "contact_attempt_rate", "qualification_rate", "appointment_rate"):
        assert key in conversion
        assert conversion[f"{key}_definition"] or key == "contact_attempt_rate"
    assert conversion["denominators"]["all_leads"] >= 1
    assert body["totals"]["leads"] >= 1
    assert body["unavailable_metrics"], "metrics that cannot be computed must be listed"


def test_reports_by_source_and_lead_volume(client, make_lead):
    make_lead(name="FB Lead", source="Facebook")
    make_lead(name="CL Lead", source="Craigslist")

    sources = client.get("/api/reports/by-source").json()
    names = [i["source"] for i in sources["items"]]
    assert "Facebook" in names
    for item in sources["items"]:
        assert set(item) >= {"source", "count", "share", "closed", "closed_rate", "stages"}

    volume = client.get("/api/reports/lead-volume", params={"days": 90}).json()
    assert volume["days"] == 90
    assert isinstance(volume["by_original_creation_date"], list)
    assert volume["note"]


def test_report_csv_exports_are_downloadable(client, make_lead):
    make_lead(name="Exported Lead", stage="new")
    for kind in ("leads", "aging", "followups", "activities"):
        response = client.get("/api/reports/export/csv", params={"kind": kind})
        assert response.status_code == 200, f"{kind}: {response.text}"
        assert "text/csv" in response.headers["content-type"]
        assert response.text.splitlines()[0], f"{kind} export has no header row"


def test_settings_roundtrip(client):
    settings_body = client.get("/api/settings").json()
    assert settings_body["settings"]["followup_rules"]["default_priority"] >= 1
    assert settings_body["runtime"]["resimpli_api_key_configured"] is False
    stage_keys = [s["key"] for s in settings_body["pipeline"]["stages"]]
    assert "new" in stage_keys

    updated = client.put(
        "/api/settings",
        json={"followup_rules": {"default_priority": 2}, "stage_mapping": {"custom status": "contacted"}},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["followup_rules"]["default_priority"] == 2
    assert body["stage_mapping"]["custom status"] == "contacted"

    rules = client.get("/api/settings/followup-rules").json()
    assert rules["rules"]["default_priority"] == 2
    assert "default_priority" in rules["defaults"]


def test_audit_log_records_important_actions(client, make_lead):
    lead = make_lead(name="Audited Lead")
    client.patch(f"/api/leads/{lead.id}", json={"pipeline_stage": "nurture"})
    client.put("/api/settings", json={"followup_rules": {"new_lead_priority": 4}})

    entries = client.get("/api/audit").json()["items"]
    actions = {e["action"] for e in entries}
    assert "lead.update" in actions
    assert "settings.update" in actions
    assert all(e["id"] and e["created_at"] for e in entries)


def test_followup_due_date_drives_next_followup(client, make_lead):
    lead = make_lead(name="Scheduled Lead", stage="contacted", contact_status="spoke_with_seller")
    due = datetime.utcnow() + timedelta(days=1)
    client.post(
        "/api/followups",
        json={"lead_id": lead.id, "due_at": due.isoformat(), "reason": "Check in"},
    )
    detail = client.get(f"/api/leads/{lead.id}").json()
    assert detail["next_followup_at"], "lead rollup should carry the open follow-up date"
