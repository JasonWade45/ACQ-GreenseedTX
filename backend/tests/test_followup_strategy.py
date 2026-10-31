from app.db import utcnow
from app.models import Activity, Followup
from app.services import followup_strategy


def test_first_message_names_the_sender_and_company(db, make_lead):
    lead = make_lead("Dana Seller")
    message = followup_strategy.build_message(lead, None, first=True)
    assert "Jason Wade" in message["text"]
    assert "GreenSeedTX LLC" in message["text"]
    assert message["first_message"] is True
    assert len(message["text"]) <= 320


def test_later_message_omits_the_sender_name_but_keeps_the_company(db, make_lead):
    lead = make_lead("Dana Seller")
    message = followup_strategy.build_message(lead, None, first=False)
    assert "Jason Wade" not in message["text"]
    assert "GreenSeedTX LLC" in message["text"]
    assert message["first_message"] is False


def test_a_conversation_is_quoted_only_when_it_is_real(db, make_lead):
    lead = make_lead("Dana Seller")
    activity = Activity(
        lead_id=lead.id,
        activity_type="call",
        outcome="Connected",
        occurred_at=utcnow(),
        summary="Seller said the roof is older and they want to close before spring.",
    )
    db.add(activity)
    db.commit()
    message = followup_strategy.build_message(lead, activity, first=False)
    assert "roof is older" in message["text"]
    assert message["basis"] == "last conversation"


def test_mark_sent_completes_and_schedules_the_next_cadence_touch(db, make_lead):
    lead = make_lead("Dana Seller")
    lead.contact_status = "not_contacted"
    followup = Followup(
        lead_id=lead.id,
        due_at=utcnow(),
        reason="first touch",
        suggested_action="Call",
        status="pending",
    )
    db.add(followup)
    db.commit()
    message = followup_strategy.build_message(lead, None, first=True)
    result = followup_strategy.mark_sent(db, followup, message["text"], "SMS")
    assert result["followup"].status == "completed"
    assert result["completed_count"] == 1
    assert result["next_due"] is not None
    assert db.query(Followup).filter_by(lead_id=lead.id, status="pending").count() == 1
    assert db.query(Activity).filter_by(lead_id=lead.id, activity_type="message").count() == 1
    assert lead.contact_status == "attempted"
    next_message = followup_strategy.build_message(lead, None, first=followup_strategy.first_message(lead, db))
    assert "Jason Wade" not in next_message["text"]


def test_the_sent_endpoint_removes_the_current_task_and_creates_the_next(client, db, make_lead):
    lead = make_lead("Dana Seller")
    followup = Followup(
        lead_id=lead.id,
        due_at=utcnow(),
        reason="first touch",
        suggested_action="Call",
        status="pending",
    )
    db.add(followup)
    db.commit()
    message = followup_strategy.build_message(lead, None, first=True)["text"]
    r = client.post(
        f"/api/followups/{followup.id}/sent",
        json={"message": message, "channel": "SMS", "confirm": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["followup"]["status"] == "completed"
    assert r.json()["next_due"] is not None
