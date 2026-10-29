"""Batch contact-permission review (1.5.1).

Fifty imported leads used to mean fifty profile visits before a single draft could
exist. This batch action is the one bulk write that can *open* outreach, so the tests
are written from the suspicious side: what stops it, what it refuses to overwrite, and
what it leaves behind if it is misused.
"""

from app.models import AuditLog, Lead
from app.services.imports import create_local_lead

PHRASE = "REVIEW RESTRICTIONS"


def _lead(db, index=1, **extra):
    data = {
        "full_name": f"Seller {index}",
        "primary_phone": f"+12025550{100 + index}",
        "street_address": f"{100 + index} Oak Ridge Dr",
        "city": "Arlington",
        "state": "TX",
        "zip_code": "76015",
        "county": "Tarrant",
        "normalized_address": f"{100 + index}oak|arlington|tx|76015",
        "external_id": f"ds:batch{index}",
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


def _review(client, lead_ids, **overrides):
    payload = {
        "lead_ids": lead_ids,
        "restricted": False,
        "evidence": "Source list screened for opt-outs on 2026-10-29; no STOP entries.",
        "confirm": True,
        "confirmation": PHRASE,
        **overrides,
    }
    return client.post("/api/leads/restrictions/bulk", json=payload)


def test_the_pending_list_shows_what_blocks_drafting(client, db):
    pending = _lead(db, 1)
    reviewed = _lead(db, 2)
    reviewed.restriction_reviewed = True
    reviewed.restriction_evidence = "Checked earlier"
    blocked = _lead(db, 3, source_do_not_contact=True)
    db.commit()

    body = client.get("/api/leads/restrictions/pending").json()
    ids = {item["id"] for item in body["items"]}
    assert pending.id in ids
    assert reviewed.id not in ids
    # A lead the source already blocks is not something to "review away".
    assert blocked.id not in ids
    assert body["total"] == len(ids)
    assert body["confirmation_phrase"] == PHRASE
    assert body["never_sent"] is True


def test_a_batch_needs_the_typed_phrase_not_just_a_click(client, db):
    lead = _lead(db)
    assert _review(client, [lead.id], confirmation="").status_code == 400
    assert _review(client, [lead.id], confirmation="yes").status_code == 400
    assert _review(client, [lead.id], confirm=False).status_code == 400
    assert _review(client, [lead.id], evidence="short").status_code == 422
    db.expire_all()
    assert db.get(Lead, lead.id).restriction_reviewed is False

    assert _review(client, [lead.id], confirmation="review restrictions").status_code == 200


def test_every_lead_keeps_its_own_audit_row(client, db):
    leads = [_lead(db, i) for i in (1, 2, 3)]
    body = _review(client, [lead.id for lead in leads]).json()
    assert body["reviewed"] == 3

    for lead in leads:
        db.expire_all()
        refreshed = db.get(Lead, lead.id)
        assert refreshed.restriction_reviewed is True
        assert refreshed.restriction_status == "reviewed_clear"
        assert "screened" in refreshed.restriction_evidence
        rows = (
            db.query(AuditLog)
            .filter(AuditLog.lead_id == lead.id, AuditLog.action == "restriction_reviewed")
            .all()
        )
        assert len(rows) == 1
        assert rows[0].details["batch"] is True
        assert rows[0].details["evidence"].startswith("Source list screened")

    summary = db.query(AuditLog).filter(AuditLog.action == "restriction_batch_reviewed").all()
    assert summary and summary[0].details["reviewed"] == 3


def test_a_source_do_not_contact_is_never_cleared_in_a_batch(client, db):
    clear = _lead(db, 1)
    blocked = _lead(db, 2, source_do_not_contact=True)
    body = _review(client, [clear.id, blocked.id]).json()

    assert body["reviewed"] == 1
    assert body["blocked"] == [{"id": blocked.id, "reason": "source_do_not_contact"}]
    db.expire_all()
    assert db.get(Lead, blocked.id).do_not_contact is True
    assert db.get(Lead, blocked.id).restriction_reviewed is False


def test_already_reviewed_leads_are_reported_not_rewritten(client, db):
    lead = _lead(db)
    lead.restriction_reviewed = True
    lead.restriction_evidence = "The original note"
    db.commit()

    body = _review(client, [lead.id]).json()
    assert body["reviewed"] == 0
    assert body["already_reviewed"] == 1
    db.expire_all()
    # The earlier evidence is not silently replaced by the batch sentence.
    assert db.get(Lead, lead.id).restriction_evidence == "The original note"


def test_a_batch_can_also_restrict_instead_of_clearing(client, db):
    lead = _lead(db)
    body = _review(client, [lead.id], restricted=True).json()
    assert body["reviewed"] == 1
    db.expire_all()
    refreshed = db.get(Lead, lead.id)
    assert refreshed.do_not_contact is True
    assert refreshed.restriction_status == "do_not_contact"
    # And it is no longer offered in a drafting queue.
    assert client.post(f"/api/leads/{lead.id}/draft", json={"regenerate": True}).status_code == 400


def test_unknown_ids_are_reported_without_failing_the_batch(client, db):
    lead = _lead(db)
    body = _review(client, [lead.id, 999_999]).json()
    assert body["reviewed"] == 1
    assert body["missing"] == [999_999]


def test_a_batch_does_not_override_the_other_gates(client, db):
    """Reviewing permission is not a licence or a phone number."""
    unverified = _lead(db, 1, primary_phone=None, needs_skip_trace=True)
    out_of_area = _lead(db, 2, in_license=False)

    _review(client, [unverified.id, out_of_area.id])
    assert client.post(f"/api/leads/{unverified.id}/draft", json={"regenerate": True}).status_code == 400
    assert client.post(f"/api/leads/{out_of_area.id}/draft", json={"regenerate": True}).status_code == 400
