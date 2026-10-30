"""Deciding whether a lead may be created in REsimpli, and doing it exactly once.

The queue is local: eligibility is computed from the lead itself, without a network
call, so the Push Queue can render instantly and say *why* a lead is waiting. The plan
is where the CRM is consulted: before any create, ``/lead/list`` is searched by phone
and by street address, and a plausible match blocks the push and records a conflict
instead. That search is the reason losing the local mapping -- a restore, a wiped
database -- cannot produce a duplicate lead.

Modes:

* ``review`` (default) -- every lead is prepared, shown, and sent only on an explicit
  confirmation string. The same path serves a single lead, which is how a first live
  push should be tested.
* ``auto`` -- the caller is the import/sync job; the plan is unchanged, only the
  confirmation is supplied by that job rather than typed by a person.

A dry run is the same plan with the writer left out. It writes nothing -- no mapping, no
conflict, no audit row -- and shows the exact body the CRM would receive.
"""

import hashlib
import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..db import utcnow
from ..models import AuditLog, CrmNoteOutbox, CrmPush, Lead, SyncConflict
from .resimpli import IntegrationError, at_path, mapped_record
from .resimpli_write import (
    CrmDefaults,
    CrmPushBlocked,
    CrmWriteError,
    build_lead_payload,
    lead_address,
    lead_phones,
    payload_hash,
    ten_digit_phone,
)

CONFIRMATION = "PUSH TO CRM"
MODES = ("review", "auto")
NOTE_PREFIX = "[GreenSeed]"
MAX_SEARCHES = 3

# Which parts of a note are shared with the CRM. Defaults follow the approved scope:
# the property and priority facts yes, owner contact data and internal notes no.
NOTE_FIELDS = {
    "equity": True,
    "flags": True,
    "lead_type": True,
    "priority": True,
    "owner_contact": False,
    "internal": False,
}


class PushSettings(BaseModel):
    """Settings-screen values for the push, stored in ``app_settings`` under ``crm_push``."""

    model_config = ConfigDict(extra="forbid")
    mode: str = "review"
    marketing_campign_id: str = ""
    market_id: str = ""
    pipeline_id: str = ""
    main_status_id: str = ""
    note_fields: dict[str, bool] = Field(default_factory=lambda: dict(NOTE_FIELDS))

    @field_validator("mode")
    @classmethod
    def known_mode(cls, value):
        if value not in MODES:
            raise ValueError("Mode must be review or auto")
        return value

    def defaults(self):
        """The account IDs as a validated object, or a blocked reason when they are unset."""
        try:
            return CrmDefaults(
                marketing_campign_id=self.marketing_campign_id,
                market_id=self.market_id,
                pipeline_id=self.pipeline_id,
                main_status_id=self.main_status_id,
            )
        except ValueError as exc:
            raise CrmPushBlocked(
                "missing_crm_defaults",
                "Load the marketing campaign, market, pipeline and status IDs from REsimpli in Settings",
            ) from exc

    def note_field(self, name):
        return bool(self.note_fields.get(name, NOTE_FIELDS.get(name, False)))


def load_push_settings(db: Session) -> PushSettings:
    from ..models import AppSetting

    row = db.get(AppSetting, "crm_push")
    values = row.value if row else {}
    return PushSettings(**{key: value for key, value in (values or {}).items() if key in PushSettings.model_fields})


def save_push_settings(db: Session, updates: dict) -> PushSettings:
    from ..models import AppSetting

    current = load_push_settings(db).model_dump()
    merged = {**current, **{key: value for key, value in updates.items() if key in PushSettings.model_fields}}
    validated = PushSettings(**merged)
    row = db.get(AppSetting, "crm_push")
    if row:
        row.value = validated.model_dump()
    else:
        db.add(AppSetting(key="crm_push", value=validated.model_dump()))
    db.commit()
    return validated


class QueueRow(BaseModel):
    lead_id: int
    full_name: str
    address: Optional[str] = None
    state: str = "pending"
    reason: Optional[str] = None
    message: Optional[str] = None
    resimpli_lead_id: Optional[str] = None
    pushed_at: Optional[datetime] = None


class PushPlan(BaseModel):
    lead_id: int
    eligible: bool
    reason: Optional[str] = None
    message: str = ""
    body: Optional[dict] = None
    payload_hash: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    matches: list[dict] = Field(default_factory=list)
    searches: list[str] = Field(default_factory=list)
    note: Optional[str] = None
    note_hash: Optional[str] = None
    mode: str = "review"
    dry_run: bool = True


class PushOutcome(BaseModel):
    lead_id: int
    state: str
    reason: Optional[str] = None
    message: str = ""
    resimpli_lead_id: Optional[str] = None
    payload_hash: Optional[str] = None
    attempts: int = 0
    dry_run: bool = True
    plan: PushPlan


def address_key(street, city, state, zip_code):
    """A conservative comparison key: same street, same town, same ZIP."""
    parts = [street, city, state, zip_code]
    text = "|".join(re.sub(r"[^a-z0-9#]", "", str(part).lower()) for part in parts if part)
    return text or None


def _conflict(db, lead, crm_value, field="existing_lead"):
    """Record one unresolved conflict, without piling up duplicates on every look."""
    existing = db.scalar(
        select(SyncConflict).where(
            SyncConflict.lead_id == lead.id,
            SyncConflict.field == field,
            SyncConflict.crm_value == crm_value,
            SyncConflict.resolved.is_(False),
        )
    )
    if existing:
        return existing
    conflict = SyncConflict(
        lead_id=lead.id,
        field=field,
        local_value=lead_address(lead) or "",
        crm_value=crm_value,
    )
    db.add(conflict)
    return conflict


def local_blocker(lead, push_settings):
    """Everything that can be decided without the network. Returns ``(reason, message)``."""
    mapping = getattr(lead, "_crm_push", None)
    if mapping is not None and mapping.state == "pushed":
        return "already_pushed", "This lead already exists in REsimpli"
    try:
        push_settings.defaults()
    except CrmPushBlocked as exc:
        return exc.reason, str(exc)
    try:
        build_lead_payload(lead, push_settings.defaults())
    except CrmPushBlocked as exc:
        return exc.reason, str(exc)
    return None, None


def _mapping(db, lead_id):
    return db.scalar(select(CrmPush).where(CrmPush.lead_id == lead_id))


def _flat_address(*parts):
    """One normalized token for an address, whatever shape it arrived in.

    The CRM returns the whole address as a single line on list endpoints; the local
    store keeps street, city, state and ZIP as separate columns. Comparing the pipe
    key against the flat string always lost. Flattening both into one token makes the
    two shapes comparable and still ignores formatting noise (punctuation, casing,
    # signs are kept so apartment numbers stay distinctive).
    """
    text = " ".join(str(part) for part in parts if part)
    flat = re.sub(r"[^a-z0-9#]", "", text.lower())
    return flat or ""


def _matches(mapped, phones, key):
    """Compare one mapped CRM record with the local lead on phone digits and address."""
    found = []
    remote_phone = ""
    for value in (mapped.get("primary_phone"), mapped.get("phone2")):
        if value:
            digits = ten_digit_phone(value)
            if digits and digits in phones:
                remote_phone = digits
                break
    if remote_phone:
        found.append((mapped, "phone"))
        return found
    remote_key = address_key(
        mapped.get("street_address"), mapped.get("city"), mapped.get("state"), mapped.get("zip_code")
    )
    if key and remote_key and (key == remote_key or key.startswith(remote_key) or remote_key.startswith(key)):
        found.append((mapped, "address"))
        return found
    # Same property seen in the CRM's single-line form against the local split form.
    flat_local = key.replace("|", "") if key else ""
    flat_remote = _flat_address(
        mapped.get("street_address"), mapped.get("city"), mapped.get("state"), mapped.get("zip_code")
    )
    if flat_local and flat_remote and (
        flat_remote.startswith(flat_local) or flat_local.startswith(flat_remote)
    ):
        found.append((mapped, "address"))
    return found


def search_existing(reader, lead, phones, key):
    """Search the CRM by phone and street before creating anything.

    Raises ``IntegrationError`` when the search itself fails: a push that cannot check
    for an existing lead is not allowed to proceed, because the check is what makes the
    push idempotent.
    """
    queries = []
    for phone in phones[:2]:
        queries.append(phone)
    street = (lead_address(lead) or "").split(",")[0].strip()
    if street:
        queries.append(street)
    queries = queries[:MAX_SEARCHES]
    matches, searched = [], []
    for query in queries:
        if not query:
            continue
        data = reader.request("/lead/list", {"searchStr": query, "page": 1, "limit": 100})
        records = at_path(data, reader.adapter.leads.list_path)
        if records is None:
            raise IntegrationError("The lead list response did not contain the configured record path")
        if not isinstance(records, list):
            raise IntegrationError("The lead list response was not a list; the adapter needs verifying")
        searched.append(query)
        for record in records:
            mapped = mapped_record(record, reader.adapter.leads)
            for hit, signal in _matches(mapped, phones, key):
                for existing in matches:
                    if existing["resimpli_lead_id"] == hit.get("external_id"):
                        break
                else:
                    matches.append(
                        {
                            "resimpli_lead_id": hit.get("external_id"),
                            "full_name": hit.get("full_name"),
                            "address": hit.get("street_address"),
                            "matched_on": signal,
                        }
                    )
    return matches, searched


def plan_push(db: Session, lead, reader, *, note=None, dry_run=True, searches=True):
    """Build the plan for one lead: local gates, then the duplicate search."""
    settings = load_push_settings(db)
    plan = PushPlan(lead_id=lead.id, eligible=False, mode=settings.mode, dry_run=dry_run)
    reason, message = local_blocker(lead, settings)
    if reason:
        plan.reason, plan.message = reason, message
        return plan
    phones = lead_phones(lead)
    built = build_lead_payload(lead, settings.defaults(), comment=note)
    plan.body = built["body"]
    plan.payload_hash = payload_hash(built["body"])
    plan.warnings = list(built["warnings"])
    plan.note = note
    plan.note_hash = hashlib.sha256(note.encode()).hexdigest() if note else None
    if searches and reader is not None:
        try:
            matches, searched = search_existing(reader, lead, phones, lead_address_key(lead))
        except IntegrationError as exc:
            plan.reason = "crm_search_failed"
            plan.message = f"The CRM could not be checked for an existing lead, so nothing was sent: {exc}"
            return plan
        plan.matches, plan.searches = matches, searched
        if matches:
            plan.reason = "exists_in_crm"
            plan.message = (
                "A matching lead already exists in REsimpli; nothing was created. Review the match and link "
                "it to this lead if it is the same property."
            )
            return plan
    plan.eligible = True
    plan.message = "Ready to create in REsimpli"
    return plan


def lead_address_key(lead):
    properties = list(lead.properties or [])
    for prop in properties:
        key = address_key(prop.street_address, prop.city, prop.state, prop.zip_code)
        if key:
            return key
    return None


def record_blocked(db: Session, lead, plan: PushPlan):
    """Keep the visible reason on the mapping row so the queue can show it."""
    mapping = _mapping(db, lead.id)
    if mapping is None:
        mapping = CrmPush(lead_id=lead.id)
        db.add(mapping)
    if mapping.state == "pushed":
        return mapping
    mapping.state = "blocked"
    mapping.blocked_reason = plan.reason
    mapping.last_error = plan.message if plan.reason not in {"already_pushed", None} else None
    db.flush()
    return mapping


def _audit(db, lead_id, action, details):
    db.add(AuditLog(lead_id=lead_id, action=action, details=details, actor="local_user"))


def execute_push(db: Session, lead, *, reader, writer, confirmation=None, note=None, settings=None, auto=False):
    """Prepare and (when confirmed) create one lead. Returns the outcome that is shown.

    ``writer`` is None for a dry run. Nothing is written to the database in that case.
    """
    settings = settings or config.get_settings()
    push_settings = load_push_settings(db)
    dry_run = writer is None
    plan = plan_push(db, lead, reader, note=note, dry_run=dry_run)
    outcome = PushOutcome(lead_id=lead.id, state="blocked", dry_run=dry_run, plan=plan)

    if not plan.eligible:
        outcome.reason, outcome.message = plan.reason, plan.message
        outcome.payload_hash = plan.payload_hash
        if not dry_run:
            record_blocked(db, lead, plan)
            for match in plan.matches:
                if match.get("resimpli_lead_id"):
                    _conflict(db, lead, str(match["resimpli_lead_id"]))
            db.commit()
        return outcome

    if dry_run:
        outcome.state, outcome.message = "dry_run", "Dry run only: nothing was sent and nothing was written"
        return outcome

    if not settings.crm_writes_enabled:
        outcome.reason = "writes_disabled"
        outcome.message = "CRM writes are switched off in the environment (CRM_WRITES_ENABLED)"
        record_blocked(db, lead, plan)
        db.commit()
        return outcome
    if push_settings.mode == "review" and not auto and confirmation != CONFIRMATION:
        outcome.reason = "confirmation_required"
        outcome.message = f"Type {CONFIRMATION} to create this lead in REsimpli"
        return outcome

    mapping = _mapping(db, lead.id)
    if mapping is None:
        mapping = CrmPush(lead_id=lead.id)
        db.add(mapping)
    mapping.state = "pushing"
    mapping.attempts = (mapping.attempts or 0) + 1
    mapping.blocked_reason = None
    mapping.last_error = None
    mapping.payload_hash = plan.payload_hash
    db.commit()

    try:
        result = writer.add_lead(plan.body)
    except CrmWriteError as exc:
        mapping.state = "failed"
        mapping.blocked_reason = exc.code
        mapping.last_error = str(exc)[:2000]
        # REsimpli enforces its own dedupe: "Address is already associated with other
        # property" means the record already exists there and nothing was created.
        # Surface that as a resolvable situation, not an error pile-up.
        if "already associated" in str(exc).lower():
            mapping.state = "blocked"
            mapping.blocked_reason = "address_exists_in_crm"
            mapping.last_error = (
                "REsimpli refused the create because this property already exists in the CRM; nothing "
                "was created twice. Find the existing lead in REsimpli and use Link to connect it."
            )
            outcome.message = mapping.last_error
        if plan.note and plan.note_hash:
            _queue_note(db, lead, plan.note, plan.note_hash, state="blocked", reason=str(exc)[:500])
        _audit(
            db,
            lead.id,
            "crm_lead_create_failed",
            {"code": exc.code, "payload_hash": plan.payload_hash, "attempts": mapping.attempts},
        )
        db.commit()
        if "already associated" in str(exc).lower():
            outcome.state = "blocked"
            outcome.reason = "address_exists_in_crm"
        else:
            outcome.state = "failed" if exc.code != "outcome_unknown" else "outcome_unknown"
            outcome.reason, outcome.message = exc.code, str(exc)
        outcome.payload_hash, outcome.attempts = plan.payload_hash, mapping.attempts
        return outcome

    mapping.state = "pushed"
    mapping.resimpli_lead_id = result.resimpli_lead_id
    mapping.note_hash = plan.note_hash
    mapping.pushed_at = utcnow()
    mapping.last_error = None
    mapping.blocked_reason = None
    if plan.note and plan.note_hash:
        _queue_note(db, lead, plan.note, plan.note_hash, state="delivered", via="lead_add_comment")
    _audit(
        db,
        lead.id,
        "crm_lead_created",
        {
            "resimpli_lead_id": result.resimpli_lead_id,
            "payload_hash": plan.payload_hash,
            "note_hash": plan.note_hash,
            "attempts": result.attempts,
            "response_keys": result.response_keys,
        },
    )
    db.commit()
    outcome.state = "pushed"
    outcome.message = "Created in REsimpli"
    outcome.resimpli_lead_id = result.resimpli_lead_id
    outcome.payload_hash = plan.payload_hash
    outcome.attempts = result.attempts
    return outcome


def _queue_note(db: Session, lead, note, note_hash, *, state, reason=None, via=None):
    row = db.scalar(select(CrmNoteOutbox).where(CrmNoteOutbox.lead_id == lead.id, CrmNoteOutbox.note_hash == note_hash))
    if row is None:
        row = CrmNoteOutbox(lead_id=lead.id, note_hash=note_hash, body=note, source="import")
        db.add(row)
    row.state = state
    row.blocked_reason = reason
    row.delivered_via = via
    if state == "delivered":
        row.delivered_at = utcnow()
    return row


def note_for_existing_lead(db: Session, lead, note):
    """A note about a lead the CRM already has cannot be written: there is no endpoint.

    It is stored anyway, marked with the reason, so it can be sent the day REsimpli adds
    one -- or copied by hand from the lead profile today.
    """
    note_hash = hashlib.sha256(note.encode()).hexdigest()
    row = _queue_note(
        db,
        lead,
        note,
        note_hash,
        state="blocked",
        reason="REsimpli's v6 Open API has no note endpoint; copy this note from the lead profile",
    )
    db.commit()
    return row


def queue(db: Session, *, limit=200) -> list[QueueRow]:
    """The Push Queue: leads with no completed push, each with its local reason."""
    push_settings = load_push_settings(db)
    rows, statement = [], (
        select(Lead, CrmPush)
        .outerjoin(CrmPush, CrmPush.lead_id == Lead.id)
        .order_by(Lead.priority_rank.is_(None), Lead.priority_rank, Lead.id)
        .limit(limit)
    )
    for lead, mapping in db.execute(statement).all():
        if mapping is not None and mapping.state == "pushed":
            continue
        setattr(lead, "_crm_push", mapping)
        reason, message = local_blocker(lead, push_settings)
        rows.append(
            QueueRow(
                lead_id=lead.id,
                full_name=lead.full_name,
                address=lead_address(lead),
                state=(mapping.state if mapping else "pending"),
                reason=reason,
                message=message,
                resimpli_lead_id=mapping.resimpli_lead_id if mapping else None,
                pushed_at=mapping.pushed_at if mapping else None,
            )
        )
    return rows


def push_batch(db: Session, leads, *, reader, writer, settings, note_for=None, auto=False, confirmation=None):
    """Push several leads. One confirmation covers the batch; one failure never stops it."""
    results = []
    for lead in leads:
        try:
            note = note_for(lead) if note_for else None
            results.append(
                execute_push(
                    db,
                    lead,
                    reader=reader,
                    writer=writer,
                    note=note,
                    settings=settings,
                    confirmation=confirmation or (CONFIRMATION if auto else None),
                    auto=auto,
                )
            )
        except Exception as exc:  # a broken lead must not stop the queue
            db.rollback()
            results.append(
                PushOutcome(
                    lead_id=getattr(lead, "id", 0),
                    state="failed",
                    reason="unexpected_error",
                    message=f"{type(exc).__name__}: {exc}"[:500],
                    dry_run=writer is None,
                    plan=PushPlan(lead_id=getattr(lead, "id", 0), eligible=False),
                )
            )
    return results


def link_existing(db: Session, lead, resimpli_lead_id: str, actor="local_user"):
    """Record that a matching CRM lead *is* this lead, resolving the conflict by hand."""
    if not resimpli_lead_id or not str(resimpli_lead_id).strip():
        raise ValueError("A REsimpli lead id is required to link")
    mapping = _mapping(db, lead.id)
    if mapping is None:
        mapping = CrmPush(lead_id=lead.id)
        db.add(mapping)
    if mapping.state == "pushed" and mapping.resimpli_lead_id not in {None, resimpli_lead_id}:
        raise ValueError("This lead is already linked to a different REsimpli lead")
    mapping.state = "pushed"
    mapping.resimpli_lead_id = str(resimpli_lead_id).strip()
    mapping.blocked_reason = None
    mapping.last_error = None
    mapping.pushed_at = mapping.pushed_at or utcnow()
    db.execute(
        SyncConflict.__table__.update()
        .where(SyncConflict.lead_id == lead.id, SyncConflict.field == "existing_lead")
        .values(resolved=True, resolution="linked_existing")
    )
    _audit(db, lead.id, "crm_lead_linked", {"resimpli_lead_id": mapping.resimpli_lead_id, "actor": actor})
    db.commit()
    return mapping


def sync_status(db: Session, lead_id):
    """What the lead profile's CRM Sync card shows."""
    mapping = _mapping(db, lead_id)
    if mapping is None:
        return {"state": "not_pushed", "resimpli_lead_id": None, "reason": None, "message": None, "pushed_at": None}
    return {
        "state": mapping.state,
        "resimpli_lead_id": mapping.resimpli_lead_id,
        "reason": mapping.blocked_reason,
        "message": mapping.last_error,
        "pushed_at": mapping.pushed_at,
        "attempts": mapping.attempts,
        "payload_hash": mapping.payload_hash,
    }


def failed_count(db: Session) -> int:
    return len(db.scalars(select(CrmPush).where(CrmPush.state == "failed")).all())
