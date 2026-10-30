from datetime import timedelta

from app.db import utcnow
from app.models import Activity, CallLog, Followup, LeadTag, Suppression


def test_recording_an_interested_call_creates_activity_followup_and_stage(client, db, make_lead):
    lead = make_lead(stage_code="new")
    r = client.post(
        f"/api/leads/{lead.id}/conversations",
        json={"outcome": "interested", "notes": "Wants to sell in spring", "duration_seconds": 420},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["call"]["outcome"] == "interested"
    assert body["suggestion"]["should_schedule"] is True
    assert body["lead"]["stage_code"] == "qualified"
    assert body["lead"]["contact_status"] == "contacted"

    db.expire_all()
    assert db.query(CallLog).filter_by(lead_id=lead.id).count() == 1
    assert db.query(Activity).filter_by(lead_id=lead.id, activity_type="call").count() == 1
    followup = db.query(Followup).filter_by(lead_id=lead.id).one()
    assert followup.creation_source == "call_log"
    assert followup.status == "pending"


def test_dnc_call_suppresses_the_phone_and_schedules_no_followup(client, db, make_lead):
    lead = make_lead(primary_phone="+15125550123")
    r = client.post(f"/api/leads/{lead.id}/conversations", json={"outcome": "dnc"})
    assert r.status_code == 201, r.text
    assert r.json()["suggestion"]["should_schedule"] is False
    assert r.json()["lead"]["do_not_contact"] is True

    db.expire_all()
    assert db.query(Suppression).filter_by(phone="+15125550123").count() == 1
    assert db.query(Followup).filter_by(lead_id=lead.id).count() == 0


def test_no_answer_does_not_move_the_stage_but_keeps_a_callback(client, db, make_lead):
    lead = make_lead()
    lead.stage_code = "attempting_contact"
    db.commit()
    r = client.post(f"/api/leads/{lead.id}/conversations", json={"outcome": "no_answer"})
    assert r.status_code == 201, r.text
    assert r.json()["lead"]["stage_code"] == "attempting_contact"
    assert r.json()["lead"]["contact_status"] == "attempted"


def test_a_second_call_does_not_stack_duplicate_pending_followups(client, db, make_lead):
    lead = make_lead()
    for outcome in ("no_answer", "voicemail"):
        r = client.post(f"/api/leads/{lead.id}/conversations", json={"outcome": outcome})
        assert r.status_code == 201, r.text
    db.expire_all()
    assert db.query(Followup).filter_by(lead_id=lead.id, status="pending").count() == 1


def test_live_script_is_local_and_has_the_five_steps(client, make_lead):
    lead = make_lead(full_name="Dana Seller")
    r = client.get(f"/api/leads/{lead.id}/conversations/script")
    assert r.status_code == 200, r.text
    script = r.json()["script"]
    assert len(script["steps"]) == 5
    assert script["key_objections"]
    assert "Dana" in script["steps"][0]["content"]
    assert "Jason Wade" in script["steps"][0]["content"]
    assert "GreenSeedTX LLC" in script["steps"][0]["content"]


def test_tags_are_unique_listed_and_removable(client, db, make_lead):
    lead = make_lead()
    first = client.post(f"/api/leads/{lead.id}/tags", json={"tag": "hot"})
    assert first.status_code == 201
    again = client.post(f"/api/leads/{lead.id}/tags", json={"tag": "hot"})
    assert again.status_code == 201 and again.json()["id"] == first.json()["id"]

    profile = client.get(f"/api/leads/{lead.id}")
    assert [tag["tag"] for tag in profile.json()["tags"]] == ["hot"]

    removed = client.delete(f"/api/leads/{lead.id}/tags/{first.json()['id']}")
    assert removed.status_code == 204
    db.expire_all()
    assert db.query(LeadTag).filter_by(lead_id=lead.id).count() == 0


def test_assignment_rules_fill_only_the_manager(client, db, make_lead):
    lead = make_lead(state="TX", city="Austin")
    created = client.post(
        "/api/assignment/rules",
        json={
            "name": "Texas desk",
            "state": "TX",
            "target_assignee": "Jason",
            "priority": 10,
        },
    )
    assert created.status_code == 201, created.text
    applied = client.post("/api/assignment/apply", json={"only_unassigned": True})
    assert applied.status_code == 200, applied.text
    assert applied.json()["assigned"] >= 1
    db.expire_all()
    assert db.get(type(lead), lead.id).assigned_manager == "Jason"
    assert db.get(type(lead), lead.id).stage_code == "new"


def test_fallback_rule_cannot_also_filter(client):
    r = client.post(
        "/api/assignment/rules",
        json={
            "name": "Bad fallback",
            "is_fallback": True,
            "state": "TX",
            "target_assignee": "Nobody",
        },
    )
    assert r.status_code == 400


def test_stale_automation_creates_one_followup_and_logs_the_run(client, db, make_lead):
    lead = make_lead(stage_code="new")
    lead.last_contact_at = utcnow() - timedelta(days=30)
    db.commit()

    assert client.post("/api/automation/seed-defaults").status_code == 200
    run = client.post("/api/automation/run")
    assert run.status_code == 200, run.text
    results = run.json()["results"]
    assert results and all(result["state"] in ("success", "failed") for result in results)

    db.expire_all()
    assert db.query(Followup).filter_by(lead_id=lead.id, creation_source="automation").count() == 1
    logs = client.get("/api/automation/logs").json()
    assert logs
    assert logs[0]["rule_name"]


def test_automation_can_be_disabled_and_does_nothing(client, db, make_lead):
    lead = make_lead(stage_code="new")
    lead.last_contact_at = utcnow() - timedelta(days=60)
    db.commit()
    client.post("/api/automation/seed-defaults")
    for rule in client.get("/api/automation/rules").json():
        client.patch(f"/api/automation/rules/{rule['id']}", json={"enabled": False})
    run = client.post("/api/automation/run")
    assert run.status_code == 200
    assert run.json()["results"] == []
    db.expire_all()
    assert db.query(Followup).filter_by(lead_id=lead.id).count() == 0
