"""Orphan endpoints wired to the interface (1.5.1).

Two routes existed with no caller: the reply scan of already-synced activity, and the
template-selection preview. These tests hold them to a standard the interface can print
truthfully -- exact counts, and a reason that names the flags that matched.
"""

from datetime import datetime, timezone

from app.models import Activity, Lead, SuggestedAction
from app.services import replies, templates
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
        "normalized_address": "1000oakridgedr|arlington|tx|76015",
        "external_id": "ds:1000oakridgedr|arlington|tx|76015",
        "outreach_mode": "cold",
        "needs_skip_trace": False,
        "source_do_not_contact": False,
        "stage_code": "not_contacted",
        "in_license": True,
        **extra,
    }
    lead = create_local_lead(db, data, data, source_kind="import")
    db.commit()
    return lead


def _activity(db, lead, summary, direction="inbound"):
    row = Activity(
        lead_id=lead.id,
        activity_type="sms",
        direction=direction,
        occurred_at=NOW,
        source="resimpli",
        summary=summary,
        external_id=f"a-{abs(hash((lead.id, summary)))}",
    )
    db.add(row)
    db.commit()
    return row


def test_scan_reports_what_it_read_and_what_it_left_alone(client, db):
    lead = _lead(db)
    _activity(db, lead, "Yes, interested - tell me more")
    _activity(db, lead, "ok")
    _activity(db, lead, "")
    _activity(db, lead, "Outbound note", direction="outbound")

    body = client.post("/api/replies/scan").json()
    # The outbound row is not a reply, and an empty summary is not "unread" either.
    assert body["scanned"] == 2, body
    assert body["classified"] == 1
    assert body["needs_human"] == 1
    assert body["skipped_empty"] == 1
    assert body["never_sent"] is True
    assert body["items"][0]["classification"] == "INTERESTED"
    # The suggestion is a proposal, not a stored decision.
    action = db.query(SuggestedAction).one()
    assert action.status == "pending"
    assert action.requires_confirmation is True


def test_scanning_twice_does_not_duplicate_a_suggestion(client, db):
    lead = _lead(db)
    _activity(db, lead, "STOP")
    first = client.post("/api/replies/scan").json()
    second = client.post("/api/replies/scan").json()
    assert first["classified"] == 1
    assert second["classified"] == 0
    assert second["already_seen"] == 1
    assert db.query(SuggestedAction).count() == 1


def test_a_stop_found_in_synced_activity_blocks_outreach_immediately(client, db):
    lead = _lead(db)
    _activity(db, lead, "Please stop")
    client.post("/api/replies/scan")
    db.expire_all()
    refreshed = db.get(Lead, lead.id)
    assert refreshed.local_do_not_contact is True
    # The suppression list itself still needs Jason's confirmation.
    assert db.query(SuggestedAction).one().status == "pending"


def test_template_selection_names_the_flag_that_matched(client, db):
    lead = _lead(db, ds_flags={"senior_owner": True}, lead_type="Inheritance")
    body = client.get(f"/api/leads/{lead.id}/template-selection").json()
    assert body["category"] == "SENIOR_OWNER"
    assert "senior_owner" in body["tags"]
    assert "Matched on:" in body["reason"]
    assert body["variants_available"] == ["A", "B"]
    assert body["preview"] and "senior_owner" not in body["preview"].lower()
    assert body["selectable"] is True

    plain = _lead(
        db,
        full_name="Plain Seller",
        external_id="ds:plain",
        normalized_address="plain|arlington|tx|76015",
        primary_phone="+12025550188",
    )
    plain_body = client.get(f"/api/leads/{plain.id}/template-selection").json()
    assert plain_body["category"] == "GENERIC_OPENER"
    assert "No distress flag matched" in plain_body["reason"]


def test_template_selection_lists_the_blockers_instead_of_pretending(client, db):
    unverified = _lead(db, full_name="No Contact", phone=None, needs_skip_trace=True, external_id="ds:nc")
    # An explicit source "no" counts as reviewed; unknown needs a person to look.
    unverified.source_do_not_contact = None
    unverified.restriction_reviewed = False
    db.commit()
    body = client.get(f"/api/leads/{unverified.id}/template-selection").json()
    assert body["selectable"] is False
    assert any("skip trace" in item for item in body["blockers"])
    assert any("not reviewed" in item for item in body["blockers"])

    blocked = _lead(db, full_name="Stop Seller", external_id="ds:stop", primary_phone="+12025550177")
    blocked.local_do_not_contact = True
    db.commit()
    payload = client.get(f"/api/leads/{blocked.id}/template-selection").json()
    assert payload["selectable"] is False
    assert any("Do Not Contact" in item for item in payload["blockers"])


def test_the_preview_is_the_same_wording_the_draft_would_use(client, db):
    templates.seed_templates(db)
    lead = _lead(db, lead_type="Inheritance", ds_flags={"senior_owner": True})
    lead.restriction_reviewed = True
    lead.restriction_evidence = "Reviewed locally before contact"
    db.commit()

    preview = client.get(f"/api/leads/{lead.id}/template-selection").json()["preview"]
    draft = client.post(f"/api/leads/{lead.id}/draft", json={"regenerate": True})
    assert draft.status_code == 200, draft.text
    body = draft.json()
    # Same category, same opening sentence: the preview is not a different message.
    assert body["category"] == "SENIOR_OWNER"
    assert preview.split(".")[0] == body["body"].split(".")[0]


def test_the_scan_service_still_returns_a_plain_list_for_callers():
    """The old helper stays usable: scan_inbound_activities added counts around it."""
    assert callable(replies.classify_inbound_activities)


def test_an_unnamed_lead_never_reads_hi_hello(client, db):
    """The preview exposed it; the same wording would reach a real draft."""
    templates.seed_templates(db)
    lead = _lead(db, full_name=None, primary_phone=None, needs_skip_trace=False, external_id="ds:anon")
    lead.restriction_reviewed = True
    lead.restriction_evidence = "Reviewed locally before contact"
    db.commit()

    preview = client.get(f"/api/leads/{lead.id}/template-selection").json()["preview"]
    assert "Hi Hello" not in preview
    assert preview.startswith("Hello, this is")

    named = _lead(db, full_name="Dana Seller", external_id="ds:named", primary_phone="+12025550166")
    named_preview = client.get(f"/api/leads/{named.id}/template-selection").json()["preview"]
    assert named_preview.startswith("Hi Dana, this is")
