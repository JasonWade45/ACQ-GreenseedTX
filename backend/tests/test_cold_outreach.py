"""Phase 4/5/6: priority factors, cold outreach drafts, validator, replies, cadence."""

from datetime import datetime, timezone

import pytest

from app.models import Lead, Message, SuggestedAction, Template
from app.services import compliance, operations, replies, sequences, templates
from app.services.imports import create_local_lead

BUSINESS_HOURS = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)


def _cold_lead(db, **extra):
    data = {
        "full_name": "Dana Seller",
        "primary_phone": "+12025550143",
        "street_address": "1000 Oak Ridge Dr",
        "city": "Arlington",
        "state": "TX",
        "zip_code": "76015",
        "county": "Tarrant",
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


# ── Phase 4: priority ────────────────────────────────────────────────────────
def test_very_hot_outranks_a_plain_lead(db, make_lead):
    rules = db.get(__import__("app.models", fromlist=["AppSetting"]).AppSetting, "priority_rules").value
    hot = _cold_lead(db, heat="VERY_HOT", score=92.0, equity_pct=55.0)
    plain = _cold_lead(
        db,
        full_name="Plain Seller",
        primary_phone="+12025550144",
        external_id="ds:plain",
        heat="NONE",
        score=None,
        equity_pct=None,
    )
    hot_score, hot_factors = operations.priority_for(hot, None, rules, BUSINESS_HOURS, "America/Chicago")
    plain_score, _ = operations.priority_for(plain, None, rules, BUSINESS_HOURS, "America/Chicago")
    assert hot_score > plain_score
    assert any("Very hot" in reason for reason in hot_factors)
    assert any("Sale likelihood" in reason for reason in hot_factors)
    assert any("Equity" in reason for reason in hot_factors)
    assert hot_score <= 100


def test_negative_equity_penalty_applies(db):
    rules = db.get(__import__("app.models", fromlist=["AppSetting"]).AppSetting, "priority_rules").value
    lead = _cold_lead(db, equity_pct=-3.0, heat="NONE", score=None)
    _, factors = operations.priority_for(lead, None, rules, BUSINESS_HOURS, "America/Chicago")
    assert any("Equity -3%" in reason for reason in factors)


def test_queue_has_a_skip_trace_section_and_excludes_dnc(db, make_lead):
    skip = _cold_lead(db, needs_skip_trace=True, full_name=None, primary_phone=None)
    contactable = _cold_lead(db, full_name="Ready Seller", external_id="ds:ready", primary_phone="+12025550145")
    assert contactable.needs_skip_trace is False
    blocked = make_lead(name="Blocked", phone="+12025550146", source_do_not_contact=True)
    queue = operations.daily_queue(db, "America/Chicago")
    skip_ids = {item["lead"]["id"] for item in queue["sections"]["needs_skip_trace"]}
    assert skip.id in skip_ids
    for section, items in queue["sections"].items():
        if section == "needs_skip_trace":
            continue
        assert skip.id not in {item["lead"]["id"] for item in items}
    every_queue_id = {item["lead"]["id"] for items in queue["sections"].values() for item in items}
    assert blocked.id not in every_queue_id
    out_of_license = _cold_lead(db, full_name="Georgia", external_id="ds:ga", primary_phone="+12025550147")
    from app.services.compliance import save_settings

    save_settings(db, {"licensed_counties": ["Tarrant, TX"]})
    db.refresh(out_of_license)
    lead_state = out_of_license.properties[0].state if out_of_license.properties else None
    if lead_state != "TX":
        assert out_of_license.in_license is False


def test_priority_weights_are_editable_and_validated(client, db):
    settings = client.get("/api/settings").json()
    rules = dict(settings["priority_rules"])
    rules["heat_very_hot_bonus"] = 5
    ok = client.patch("/api/settings", json={"priority_rules": rules})
    assert ok.status_code == 200
    assert ok.json()["priority_rules"]["heat_very_hot_bonus"] == 5
    bad = dict(rules)
    bad["heat_very_hot_bonus"] = 999
    assert client.patch("/api/settings", json={"priority_rules": bad}).status_code == 400
    missing = {k: v for k, v in rules.items() if k != "equity_bonus"}
    assert client.patch("/api/settings", json={"priority_rules": missing}).status_code == 400


# ── Phase 5: cold drafting ──────────────────────────────────────────────────
def test_skip_traced_lead_can_generate_a_cold_draft(client, db):
    templates.seed_templates(db)
    lead = _cold_lead(db)
    response = client.post(f"/api/leads/{lead.id}/draft", json={"mode": "cold"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "cold"
    assert "Jason Wade with GreenSeedTX LLC" in body["body"]
    assert "Reply STOP to opt out" in body["body"]
    assert "1000 Oak Ridge Dr" in body["body"]
    assert body["validator_result"]["ok"] is True
    assert body["status"] == "DRAFT"


@pytest.mark.parametrize(
    "fault,reason",
    [
        ({"needs_skip_trace": True}, "Needs skip trace"),
        ({"primary_phone": None}, "Needs skip trace"),
        ({"full_name": None, "needs_skip_trace": True}, "Needs skip trace"),
        ({"source_do_not_contact": True}, "Do Not Contact"),
        ({"source_do_not_contact": None}, "restriction"),
    ],
)
def test_cold_draft_refuses_with_a_specific_reason(client, db, fault, reason):
    templates.seed_templates(db)
    lead = _cold_lead(db, **fault)
    response = client.post(f"/api/leads/{lead.id}/draft", json={"mode": "cold"})
    assert response.status_code == 400
    assert reason.lower() in response.json()["detail"].lower()


def test_cold_draft_is_blocked_out_of_license(client, db):
    templates.seed_templates(db)
    lead = _cold_lead(db)
    lead.properties[0].state = "GA"
    lead.in_license = False
    db.commit()
    response = client.post(f"/api/leads/{lead.id}/draft", json={"mode": "cold"})
    assert response.status_code == 400
    assert "out of license" in response.json()["detail"].lower()


def test_suppressed_phone_blocks_a_cold_draft(client, db):
    templates.seed_templates(db)
    lead = _cold_lead(db)
    compliance.add_suppression(db, lead.primary_phone, "manual", "test")
    response = client.post(f"/api/leads/{lead.id}/draft", json={"mode": "cold"})
    assert response.status_code == 400
    assert "suppression" in response.json()["detail"].lower()


def test_relationship_leads_keep_the_original_behavior(client, make_lead):
    lead = make_lead(source_do_not_contact=False, contact_outcome="Callback Requested")
    response = client.post(f"/api/leads/{lead.id}/draft", json={})
    assert response.status_code == 200
    assert response.json()["kind"] == "relationship"
    assert "callback request" in response.json()["body"]


def test_senior_inheritance_selects_senior_owner(db):
    lead = _cold_lead(
        db,
        lead_type="Inheritance",
        ds_flags={"senior_owner": True},
    )
    assert templates.select_category(lead) == "SENIOR_OWNER"
    reason = templates.selection_reason(lead)
    assert "senior_owner" in reason["tags"]


def test_tax_deed_selects_the_tax_category(db):
    lead = _cold_lead(db, lead_type="Tax Deed Sale", ds_flags={})
    assert templates.select_category(lead) == "TAX_LIEN_LISPENDENS_HOA"
    lead2 = _cold_lead(db, lead_type="Federal Tax Lien", external_id="ds:2", primary_phone="+12025550148")
    assert templates.select_category(lead2) == "TAX_LIEN_LISPENDENS_HOA"


def test_every_default_template_passes_the_validator(db):
    templates.seed_templates(db)
    lead = _cold_lead(db)
    for category, variants in templates.DEFAULT_TEMPLATES.items():
        for variant, body in variants.items():
            rendered = templates.render_template(body, lead, "Jason Wade", "GreenSeedTX LLC")
            ok, reasons = templates.validate_message(rendered, True, sender_name="Jason Wade", company="GreenSeedTX LLC")
            assert ok, (category, variant, reasons)
            assert len(rendered) <= templates.MAX_CHARS, (category, variant, len(rendered))


@pytest.mark.parametrize(
    "body",
    [
        "Hi {first_name}, this is Jason Wade with GreenSeedTX LLC about your property. Reply STOP to opt out",
        "Hi Dana, this is Jason Wade with GreenSeedTX LLC about the tax lien on your home. Reply STOP to opt out",
        "Hi Dana, this is Jason Wade with GreenSeedTX LLC. Selling? 😀 Reply STOP to opt out",
        "Hi Dana, this is Jason Wade with GreenSeedTX LLC, see https://example.com. Reply STOP to opt out",
        "Hi Dana, this is Jason Wade with GreenSeedTX LLC. We can pay $250,000. Reply STOP to opt out",
        "Hi Dana, this is Jason Wade with GreenSeedTX LLC about your property.",
        "Hi Dana, this is Jason Wade with GreenSeedTX LLC. " + "We buy as-is. " * 30 + "Reply STOP to opt out",
    ],
)
def test_validator_rejects_each_failure_mode(body):
    ok, reasons = templates.validate_message(body, True, sender_name="Jason Wade", company="GreenSeedTX LLC")
    assert ok is False and reasons


def test_validator_rejects_false_urgency_and_nulls():
    base = "Hi Dana, this is Jason Wade with GreenSeedTX LLC about 1 Test St. {} Reply STOP to opt out"
    for filler in ("This is urgent.", "Last chance.", "Act now.", "Owner: None"):
        ok, reasons = templates.validate_message(
            base.format(filler), True, sender_name="Jason Wade", company="GreenSeedTX LLC"
        )
        assert ok is False, filler


def test_template_library_is_editable_with_reset(client, db):
    templates.seed_templates(db)
    row = db.query(Template).filter(Template.category == "GENERIC_OPENER", Template.variant == "A").one()
    edited = client.patch(
        f"/api/message-templates/{row.id}",
        json={"body": "Hi {first_name}, this is {sender_name} with {company} about {address}. Reply STOP to opt out"},
    )
    assert edited.status_code == 200, edited.text
    assert "about {address}" in edited.json()["body"]
    rejected = client.patch(f"/api/message-templates/{row.id}", json={"body": "Call me about the foreclosure"})
    assert rejected.status_code == 400
    reset = client.post("/api/message-templates/reset")
    assert reset.status_code == 200
    db.expire_all()
    restored = db.get(Template, row.id)
    assert restored.body == templates.DEFAULT_TEMPLATES["GENERIC_OPENER"]["A"]


def test_sender_identity_is_configurable_and_never_leaves_a_placeholder(client, db, monkeypatch):
    templates.seed_templates(db)
    lead = _cold_lead(db)
    from app.services import templates as T

    monkeypatch.setattr(T, "sender_identity", lambda settings=None: ("Alex Rivera", "Example Homes LLC"))
    response = client.post(f"/api/leads/{lead.id}/draft", json={"mode": "cold", "regenerate": True})
    assert response.status_code == 200, response.text
    body = response.json()["body"]
    assert "Alex Rivera with Example Homes LLC" in body
    assert "[your name]" not in body and "{" not in body

    monkeypatch.setattr(T, "sender_identity", lambda settings=None: ("", ""))
    failed = client.post(f"/api/leads/{lead.id}/draft", json={"mode": "cold", "regenerate": True})
    assert failed.status_code == 400
    assert "sender identity" in failed.json()["detail"].lower()


def test_message_draft_can_be_edited_and_approved_but_not_sent(client, db):
    templates.seed_templates(db)
    lead = _cold_lead(db)
    created = client.post(f"/api/leads/{lead.id}/draft", json={"mode": "cold"}).json()
    edited = client.patch(f"/api/messages/{created['id']}", json={"body": created["body"] + " Thanks."})
    assert edited.status_code == 200, edited.text
    approved = client.post(f"/api/messages/{created['id']}/approve")
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"
    rejected = client.patch(f"/api/messages/{created['id']}", json={"body": "the foreclosure sale"})
    assert rejected.status_code == 400


def test_bulk_draft_generation_creates_review_items_without_bulk_copy(client, db):
    templates.seed_templates(db)
    _cold_lead(db, heat="VERY_HOT", priority_tier="P1")
    _cold_lead(db, full_name="Other Seller", external_id="ds:other", primary_phone="+12025550149", priority_tier="P1")
    response = client.post("/api/drafts/bulk", json={"tier": "P1", "confirm": True})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["generated"] == 2
    assert payload["bulk_copy"] is False and payload["bulk_send"] is False
    queue = client.get("/api/drafts").json()
    assert queue["total"] >= 2


def test_draft_queue_marks_invalid_bodies(db):
    templates.seed_templates(db)
    lead = _cold_lead(db)
    row = Message(
        lead_id=lead.id,
        direction="outbound",
        body="Hi, this is Jason Wade with GreenSeedTX LLC about the tax lien.",
        status="DRAFT",
    )
    db.add(row)
    db.commit()
    ok, reasons = templates.validate_message(row.body, True, sender_name="Jason Wade", company="GreenSeedTX LLC")
    assert not ok and any("banned" in reason for reason in reasons)


# ── Phase 6: replies and cadence ────────────────────────────────────────────
def test_stop_reply_is_classified_and_needs_confirmation(client, db):
    templates.seed_templates(db)
    lead = _cold_lead(db)
    response = client.post(f"/api/leads/{lead.id}/reply", json={"text": "STOP"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["classification"] == "STOP" and payload["confidence"] >= 0.95
    assert payload["contact_blocked"] is True
    db.expire_all()
    # The number is not on the suppression list until Jason confirms.
    assert compliance.is_suppressed(db, lead.primary_phone) is False
    assert db.get(Lead, lead.id).local_do_not_contact is True
    action = db.get(SuggestedAction, payload["suggested_action_id"])
    assert action.kind == "suppress" and action.status == "pending"

    confirmed = client.post(f"/api/suggested-actions/{action.id}/confirm")
    assert confirmed.status_code == 200
    db.expire_all()
    assert compliance.is_suppressed(db, lead.primary_phone) is True


@pytest.mark.parametrize(
    "text,label",
    [
        ("Yes, I'm interested", "INTERESTED"),
        ("How much would you pay?", "WANTS_PRICE"),
        ("Maybe next month", "NOT_NOW"),
        ("Not interested, remove me", "NOT_INTERESTED"),
        ("Wrong number", "WRONG_NUMBER"),
        ("Is this a real company?", "QUESTION"),
        ("ok", "OTHER"),
    ],
)
def test_reply_classification_labels(text, label):
    cls, _ = replies.classify(None, text)
    assert cls == label


def test_interested_reply_creates_a_validated_suggested_draft(client, db):
    templates.seed_templates(db)
    lead = _cold_lead(db)
    payload = client.post(f"/api/leads/{lead.id}/reply", json={"text": "Yes, tell me more"}).json()
    assert payload["suggested_draft_id"]
    draft = db.get(Message, payload["suggested_draft_id"])
    assert draft.validator_result["ok"] is True
    assert draft.direction == "outbound" and draft.status == "DRAFT"


def test_wants_price_reply_never_quotes_a_number(client, db):
    templates.seed_templates(db)
    lead = _cold_lead(db)
    payload = client.post(f"/api/leads/{lead.id}/reply", json={"text": "How much?"}).json()
    assert payload["suggested_kind"] == "price_question"
    body = db.get(Message, payload["suggested_draft_id"]).body
    assert "$" not in body


def test_a_reply_pauses_the_cadence(db):
    templates.seed_templates(db)
    lead = _cold_lead(db)
    state = sequences.start_sequence(db, lead)
    replies.handle_inbound(db, lead, "Not now thanks")
    db.refresh(state)
    assert state.status == "stopped"


def test_cadence_defaults_and_stop_conditions(db):
    templates.seed_templates(db)
    assert sequences.cadence_days(db) == [0, 3, 7, 14, 30, 60, 90, 120]
    lead = _cold_lead(db)
    state = sequences.start_sequence(db, lead)
    items = sequences.runner_due_today(db, BUSINESS_HOURS)
    assert any(item["status"] == "drafted" for item in items)
    db.refresh(state)
    assert state.current_step == 1 and state.next_due_at is not None

    dead = _cold_lead(db, full_name="Dead Lead", external_id="ds:dead", primary_phone="+12025550150")
    dead.stage_code = "dead"
    db.commit()
    assert sequences.stop_conditions_met(db, dead, BUSINESS_HOURS) == "stage"


def test_cadence_is_editable_and_validated(client, db):
    ok = client.patch("/api/settings", json={"cadence": [0, 4, 9, 21]})
    assert ok.status_code == 200
    assert ok.json()["cadence"] == [0, 4, 9, 21]
    assert client.patch("/api/settings", json={"cadence": []}).status_code == 400
    assert client.patch("/api/settings", json={"cadence": [0, 999]}).status_code == 400


def test_sequence_runner_stops_when_a_reply_exists(db):
    templates.seed_templates(db)
    lead = _cold_lead(db)
    state = sequences.start_sequence(db, lead)
    db.add(Message(lead_id=lead.id, direction="inbound", body="stop", status="RECEIVED"))
    db.commit()
    sequences.runner_due_today(db, BUSINESS_HOURS)
    db.refresh(state)
    assert state.status == "stopped" and state.stop_reason == "replied"


def test_low_confidence_reply_is_flagged_for_review(client, db):
    templates.seed_templates(db)
    lead = _cold_lead(db)
    payload = client.post(f"/api/leads/{lead.id}/reply", json={"text": "ok"}).json()
    assert payload["needs_review"] is True
    action = db.get(SuggestedAction, payload["suggested_action_id"])
    assert action.payload.get("needs_review") is True


def test_dismissing_a_suggestion_changes_nothing(db):
    templates.seed_templates(db)
    lead = _cold_lead(db)
    payload = replies.handle_inbound(db, lead, "Please stop")
    action = db.get(SuggestedAction, payload["suggested_action_id"])
    result = replies.confirm_action(db, action, decision="dismiss")
    assert result["status"] == "dismissed"
    db.expire_all()
    assert compliance.is_suppressed(db, lead.primary_phone) is False
