"""The push engine: idempotent, reviewable, and never a duplicate.

Every request goes to a mocked transport. There is no live REsimpli account behind these
tests and there is no code path in them that could reach one: the reader is a fixture-mode
client over an in-memory transport and the writer is a live-mode client over the same kind
of transport with a request recorder attached.
"""

import json

import httpx
import pytest
from sqlalchemy import select

from app.config import Settings
from app.models import AuditLog, CrmNoteOutbox, CrmPush, SyncConflict
from app.services import crm_push
from app.services.resimpli import ResimpliClient
from app.services.resimpli_write import ResimpliWriter

DEFAULTS = {
    "marketing_campign_id": "5f1d7c9a1b2c3d4e5f607182",
    "market_id": "5f1d7c9a1b2c3d4e5f607183",
    "pipeline_id": "5f1d7c9a1b2c3d4e5f607184",
    "main_status_id": "5f1d7c9a1b2c3d4e5f607185",
}


def app_settings(**extra):
    values = {
        "resimpli_mode": "live",
        "resimpli_api_key": "not-a-real-key-000000000000",
        "resimpli_adapter_path": "",
        "crm_writes_enabled": True,
        "sync_requests_per_minute": 100,
        **extra,
    }
    return Settings(_env_file=None, **values)


class Crm:
    """A mocked REsimpli: read search plus write recorder, one object for both."""

    def __init__(self, existing=(), write_responses=None, search_status=200):
        self.existing = list(existing)
        self.write_responses = list(write_responses or [])
        self.search_status = search_status
        self.searches = []
        self.writes = []

    def read(self, request):
        body = json.loads(request.content or "{}")
        self.searches.append(body)
        if self.search_status != 200:
            return httpx.Response(self.search_status, json={"ok": False, "message": "search failed"})
        query = (body.get("searchStr") or "").lower()
        records = [
            record
            for record in self.existing
            if query in (record.get("phone", "") or "").lower() or query in (record.get("address", "") or "").lower()
        ]
        return httpx.Response(200, json={"ok": True, "data": {"records": records, "total": len(records)}})

    def write(self, request):
        self.writes.append(json.loads(request.content or "{}"))
        if self.write_responses:
            answer = self.write_responses.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return httpx.Response(200, json={"ok": True, "data": {"_id": "crm-lead-1"}})

    def reader(self):
        return ResimpliClient(
            Settings(_env_file=None, resimpli_mode="fixture"),
            transport=httpx.MockTransport(self.read),
            sleeper=lambda _seconds: None,
        )

    def writer(self):
        return ResimpliWriter(
            app_settings(),
            transport=httpx.MockTransport(self.write),
            sleeper=lambda _seconds: None,
        )


@pytest.fixture
def configured(db):
    crm_push.save_push_settings(db, DEFAULTS)
    return db


def counts(db):
    return (
        len(db.scalars(select(CrmPush)).all()),
        len(db.scalars(select(CrmNoteOutbox)).all()),
        len(db.scalars(select(SyncConflict)).all()),
        len(db.scalars(select(AuditLog)).all()),
    )


def test_a_dry_run_writes_nothing_and_shows_the_exact_body(configured, make_lead):
    lead = make_lead()
    crm = Crm()
    outcome = crm_push.execute_push(configured, lead, reader=crm.reader(), writer=None, settings=app_settings())
    assert outcome.state == "dry_run"
    assert outcome.plan.body["contactDetails"]["phoneNumbers"][0]["phoneNumber"] == "2025550199"
    assert outcome.plan.payload_hash == crm_push.payload_hash(outcome.plan.body)
    assert counts(configured) == (0, 0, 0, 0), "a dry run must not write a mapping, note, conflict or audit row"
    assert crm.writes == []


def test_review_mode_needs_the_typed_confirmation(configured, make_lead):
    lead = make_lead()
    crm = Crm()
    outcome = crm_push.execute_push(configured, lead, reader=crm.reader(), writer=crm.writer(), settings=app_settings())
    assert outcome.state == "blocked"
    assert outcome.reason == "confirmation_required"
    assert crm.writes == []
    assert configured.scalars(select(CrmPush)).all() == []


def test_a_confirmed_push_creates_the_lead_and_records_the_mapping(configured, make_lead):
    lead = make_lead()
    crm = Crm()
    outcome = crm_push.execute_push(
        configured,
        lead,
        reader=crm.reader(),
        writer=crm.writer(),
        confirmation="PUSH TO CRM",
        note="[GreenSeed] reviewed note",
        settings=app_settings(),
    )
    assert outcome.state == "pushed"
    assert outcome.resimpli_lead_id == "crm-lead-1"
    assert len(crm.writes) == 1
    mapping = configured.scalar(select(CrmPush).where(CrmPush.lead_id == lead.id))
    assert mapping.state == "pushed"
    assert mapping.resimpli_lead_id == "crm-lead-1"
    assert mapping.payload_hash == outcome.payload_hash
    assert mapping.pushed_at is not None
    note = configured.scalar(select(CrmNoteOutbox).where(CrmNoteOutbox.lead_id == lead.id))
    assert note.state == "delivered" and note.delivered_via == "lead_add_comment"
    audit = configured.scalar(select(AuditLog).where(AuditLog.action == "crm_lead_created"))
    assert audit.details["resimpli_lead_id"] == "crm-lead-1"
    assert "2025550199" not in json.dumps(audit.details), "the audit row never carries the phone number"


def test_an_existing_crm_lead_blocks_the_create_and_records_a_conflict(configured, make_lead):
    lead = make_lead()
    crm = Crm(existing=[{"id": "crm-existing", "name": "Same Seller", "phone": "2025550199", "address": "12 Example St"}])
    outcome = crm_push.execute_push(
        configured, lead, reader=crm.reader(), writer=crm.writer(), confirmation="PUSH TO CRM", settings=app_settings()
    )
    assert outcome.state == "blocked"
    assert outcome.reason == "exists_in_crm"
    assert crm.writes == [], "nothing may be created when the CRM already has a match"
    mapping = configured.scalar(select(CrmPush).where(CrmPush.lead_id == lead.id))
    assert mapping.state == "blocked" and mapping.blocked_reason == "exists_in_crm"
    conflict = configured.scalar(select(SyncConflict).where(SyncConflict.lead_id == lead.id))
    assert conflict.crm_value == "crm-existing" and conflict.resolved is False


def test_losing_the_mapping_cannot_produce_a_duplicate(configured, make_lead):
    """A restore that drops crm_pushes must still not create the same lead twice."""
    lead = make_lead()
    first = Crm()
    crm_push.execute_push(
        configured, lead, reader=first.reader(), writer=first.writer(), confirmation="PUSH TO CRM", settings=app_settings()
    )
    mapping = configured.scalar(select(CrmPush).where(CrmPush.lead_id == lead.id))
    configured.delete(mapping)
    configured.commit()

    # The CRM now knows the lead; the local mapping is gone.
    second = Crm(existing=[{"id": "crm-lead-1", "name": "Test Seller", "phone": "2025550199", "address": "12 Example St"}])
    outcome = crm_push.execute_push(
        configured, lead, reader=second.reader(), writer=second.writer(), confirmation="PUSH TO CRM", settings=app_settings()
    )
    assert outcome.state == "blocked" and outcome.reason == "exists_in_crm"
    assert second.writes == []
    assert configured.scalar(select(SyncConflict).where(SyncConflict.crm_value == "crm-lead-1")) is not None


def test_the_address_alone_can_match(configured, make_lead):
    lead = make_lead(phone="+12025550199")
    crm = Crm(existing=[{"id": "crm-addr", "name": "Owner Unknown", "phone": "5125550143", "address": "12 Example St", "city": "Austin", "state": "TX", "zip": "78701"}])
    outcome = crm_push.execute_push(
        configured, lead, reader=crm.reader(), writer=crm.writer(), confirmation="PUSH TO CRM", settings=app_settings()
    )
    assert outcome.reason == "exists_in_crm"
    assert outcome.plan.matches[0]["matched_on"] == "address"


def test_the_crm_single_line_address_matches_the_split_local_shape(configured, make_lead):
    """REsimpli list records carry the whole address as one line, so the pipe-key
    comparison lost and the create was refused by the CRM instead (observed live:
    "Address is already associated with other property")."""
    lead = make_lead(phone="+12025550199")
    crm = Crm(existing=[{"id": "crm-1line", "name": "Owner", "phone": "5125550143", "address": "12 Example St, Austin, TX 78701"}])
    outcome = crm_push.execute_push(
        configured, lead, reader=crm.reader(), writer=crm.writer(), confirmation="PUSH TO CRM", settings=app_settings()
    )
    assert outcome.reason == "exists_in_crm"
    assert outcome.plan.matches[0]["matched_on"] == "address"


def test_the_crm_refusing_the_create_because_the_address_exists_is_blocked_clearly(configured, make_lead):
    lead = make_lead(phone="+12025550199")
    crm = Crm(write_responses=[httpx.Response(400, json={"ok": False, "message": "Address is already associated with other property."})])
    outcome = crm_push.execute_push(
        configured, lead, reader=crm.reader(), writer=crm.writer(), confirmation="PUSH TO CRM", settings=app_settings()
    )
    assert outcome.state == "blocked"
    assert outcome.reason == "address_exists_in_crm"
    assert "already exists in the CRM" in outcome.message


def test_a_failed_search_blocks_the_push_instead_of_guessing(configured, make_lead):
    lead = make_lead()
    crm = Crm(search_status=400)
    outcome = crm_push.execute_push(
        configured, lead, reader=crm.reader(), writer=crm.writer(), confirmation="PUSH TO CRM", settings=app_settings()
    )
    assert outcome.state == "blocked" and outcome.reason == "crm_search_failed"
    assert "nothing was sent" in outcome.message
    assert crm.writes == []


def test_one_failed_lead_does_not_stop_the_batch(configured, make_lead):
    good_one, bad, good_two = make_lead("One Seller"), make_lead("Two Seller"), make_lead("Three Seller")
    crm = Crm(
        write_responses=[
            httpx.Response(200, json={"ok": True, "data": {"_id": "crm-1"}}),
            httpx.Response(400, json={"ok": False, "message": "marketId invalid"}),
            httpx.Response(200, json={"ok": True, "data": {"_id": "crm-3"}}),
        ]
    )
    results = crm_push.push_batch(
        configured,
        [good_one, bad, good_two],
        reader=crm.reader(),
        writer=crm.writer(),
        settings=app_settings(),
        confirmation="PUSH TO CRM",
    )
    assert [result.state for result in results] == ["pushed", "failed", "pushed"]
    assert results[1].reason == "rejected_payload"
    failed = configured.scalar(select(CrmPush).where(CrmPush.lead_id == bad.id))
    assert failed.state == "failed" and failed.blocked_reason == "rejected_payload"
    assert failed.attempts == 1 and "marketId invalid" in failed.last_error


def test_the_environment_switch_blocks_every_write(configured, make_lead):
    lead = make_lead()
    crm = Crm()
    outcome = crm_push.execute_push(
        configured,
        lead,
        reader=crm.reader(),
        writer=crm.writer(),
        confirmation="PUSH TO CRM",
        settings=app_settings(crm_writes_enabled=False),
    )
    assert outcome.reason == "writes_disabled"
    assert crm.writes == []


def test_the_queue_explains_every_waiting_lead(db, make_lead):
    ready = make_lead("Ready Seller")
    no_phone = make_lead("No Phone Seller", phone=None)
    restricted = make_lead("Restricted Seller")
    restricted.local_do_not_contact = True
    db.commit()
    crm_push.save_push_settings(db, DEFAULTS)

    rows = {row.lead_id: row for row in crm_push.queue(db)}
    assert rows[ready.id].reason is None
    assert rows[no_phone.id].reason == "needs_phone"
    assert rows[restricted.id].reason == "do_not_contact"


def test_an_unconfigured_account_blocks_the_queue_with_one_clear_reason(db, make_lead):
    lead = make_lead("Unconfigured Seller")
    rows = {row.lead_id: row for row in crm_push.queue(db)}
    assert rows[lead.id].reason == "missing_crm_defaults"
    assert "Settings" in rows[lead.id].message


def test_a_pushed_lead_leaves_the_queue(configured, make_lead):
    lead = make_lead()
    crm = Crm()
    crm_push.execute_push(
        configured, lead, reader=crm.reader(), writer=crm.writer(), confirmation="PUSH TO CRM", settings=app_settings()
    )
    assert [row.lead_id for row in crm_push.queue(configured)] == []


def test_linking_an_existing_lead_resolves_its_conflict(configured, make_lead):
    lead = make_lead()
    crm = Crm(existing=[{"id": "crm-existing", "name": "Same Seller", "phone": "2025550199"}])
    crm_push.execute_push(
        configured, lead, reader=crm.reader(), writer=crm.writer(), confirmation="PUSH TO CRM", settings=app_settings()
    )
    mapping = crm_push.link_existing(configured, lead, "crm-existing")
    assert mapping.state == "pushed" and mapping.resimpli_lead_id == "crm-existing"
    conflict = configured.scalar(select(SyncConflict).where(SyncConflict.lead_id == lead.id))
    assert conflict.resolved is True and conflict.resolution == "linked_existing"
    assert [row.lead_id for row in crm_push.queue(configured)] == []


def test_a_note_for_an_existing_lead_is_kept_with_the_reason_it_cannot_be_sent(configured, make_lead):
    lead = make_lead()
    row = crm_push.note_for_existing_lead(configured, lead, "[GreenSeed] enrichment summary")
    assert row.state == "blocked"
    assert "no note endpoint" in row.blocked_reason
    again = crm_push.note_for_existing_lead(configured, lead, "[GreenSeed] enrichment summary")
    assert again.id == row.id, "the same note is stored once"


def test_auto_mode_supplies_its_own_confirmation(configured, make_lead):
    lead = make_lead()
    crm = Crm()
    outcome = crm_push.execute_push(
        configured,
        lead,
        reader=crm.reader(),
        writer=crm.writer(),
        confirmation="PUSH TO CRM",
        settings=app_settings(),
        auto=True,
    )
    assert outcome.state == "pushed"


def test_an_outcome_unknown_push_is_recorded_and_never_retried(configured, make_lead):
    lead = make_lead()
    crm = Crm(write_responses=[httpx.ReadTimeout("timed out")])
    outcome = crm_push.execute_push(
        configured, lead, reader=crm.reader(), writer=crm.writer(), confirmation="PUSH TO CRM", settings=app_settings()
    )
    assert outcome.state == "outcome_unknown"
    assert len(crm.writes) == 1
    mapping = configured.scalar(select(CrmPush).where(CrmPush.lead_id == lead.id))
    assert mapping.state == "failed" and mapping.blocked_reason == "outcome_unknown"
    assert "may exist" in mapping.last_error
