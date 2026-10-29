import hashlib
import json
import threading
from datetime import timedelta
from sqlalchemy import select, func
from ..config import get_settings
from ..db import SessionLocal, utcnow
from ..models import Lead, Activity, Appointment, Followup, SyncRun, AuditLog
from ..seed import record_source_status, stage_mapping
from .normalization import normalize_record, parse_datetime, FIELDS
from .imports import create_local_lead, attach_property
from .leads import (
    apply_contact_outcome,
    set_stage,
    update_next_followup,
    source_date_is_connection,
    NON_CONTACT_ACTIVITY_TYPES,
    CONTACTED,
    ATTEMPTED,
)
from .resimpli import ResimpliClient, IntegrationError

SYNC_LOCK = threading.Lock()


def begin_sync(db, settings):
    running = db.scalar(select(SyncRun).where(SyncRun.result == "running"))
    if running:
        raise ValueError("A sync is already running. Wait for it to finish.")
    run = SyncRun(mode=settings.resimpli_mode)
    db.add(run)
    db.commit()
    return run


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _normalize_record(raw, settings):
    data, errors, _ = normalize_record(raw, {k: k for k in raw if k in FIELDS}, settings.app_timezone, "reject")
    if not data.get("external_id"):
        raise IntegrationError("Stable external lead ID missing; record was not inserted")
    # REsimpli is the system of record and this sync is a read-only local mirror,
    # so a record it already holds is never dropped wholesale. When a single
    # optional field fails to normalize (an invalid or placeholder phone, an
    # out-of-range year, a malformed amount) normalize_record leaves exactly that
    # field unset and appends a message; nothing is fabricated. Likewise a lead
    # carrying only a phone number (no seller name and no property address yet)
    # is kept as-is. Drafting and outreach already require a full_name together
    # with a normalized primary_phone and a reviewed-clear restriction status, so
    # an incomplete lead is stored for reference but is not cleared for contact.
    # Field-level messages are retained on the record for audit.
    if errors:
        data["_sync_warnings"] = errors
    return data


def apply_source_outcome(db, lead, outcome, occurred_at):
    previous_outcome = lead.contact_outcome
    latest_event = db.scalar(
        select(func.max(Activity.occurred_at)).where(
            Activity.lead_id == lead.id,
            Activity.activity_type.notin_(NON_CONTACT_ACTIVITY_TYPES),
            Activity.outcome.in_(CONTACTED | ATTEMPTED | {"Do Not Contact"}),
        )
    )
    known_dates = [value for value in (latest_event, lead.last_contact_at) if value is not None]
    apply_contact_outcome(lead, outcome, occurred_at)
    if previous_outcome and known_dates and (occurred_at is None or max(known_dates) > occurred_at):
        lead.contact_outcome = previous_outcome


def upsert_lead(db, raw, settings, list_hash):
    data = _normalize_record(raw, settings)
    lead = db.scalar(select(Lead).where(Lead.external_id == str(data["external_id"])))
    is_new = lead is None
    if is_new:
        lead = create_local_lead(
            db, data, raw, source_kind="resimpli_fixture" if settings.resimpli_mode == "fixture" else "resimpli"
        )
    else:
        for field in [
            "first_name",
            "last_name",
            "full_name",
            "primary_phone",
            "email",
            "lead_source",
            "assigned_manager",
            "source_status",
        ]:
            # Missing source fields do not erase populated local values.
            if data.get(field) not in (None, ""):
                setattr(lead, field, data[field])
        if data.get("original_created_at"):
            lead.original_created_at = parse_datetime(data["original_created_at"], settings.app_timezone)
        if data.get("last_contact_at") and source_date_is_connection(data.get("contact_outcome")):
            incoming_contact_date = parse_datetime(data["last_contact_at"], settings.app_timezone)
            if not lead.last_contact_at or incoming_contact_date > lead.last_contact_at:
                lead.last_contact_at = incoming_contact_date
            lead.contact_status = "contacted"
        if data.get("source_do_not_contact") is not None:
            # Do not silently lift a previously verified source restriction.
            if lead.source_do_not_contact is True and data["source_do_not_contact"] is False:
                db.add(
                    AuditLog(
                        lead_id=lead.id,
                        action="source_restriction_conflict",
                        details={"preserved_restriction": True, "incoming": False},
                    )
                )
            else:
                lead.source_do_not_contact = data["source_do_not_contact"]
        record_source_status(db, data.get("source_status"))
        if not lead.local_stage_override:
            set_stage(db, lead, stage_mapping(db, data.get("source_status")), source="resimpli")
        attach_property(db, lead, data, {"source": "resimpli"}, update_from_source=True)
        prior_contact = lead.source_data.get("normalized", {})
        if (data.get("contact_outcome") or data.get("last_contact_at")) and any(
            data.get(field) != prior_contact.get(field) for field in ("contact_outcome", "last_contact_at")
        ):
            contact_id = (
                "lead_contact:"
                + lead.external_id
                + ":"
                + digest([data.get("contact_outcome"), data.get("last_contact_at")])[:20]
            )
            if not db.scalar(
                select(Activity.id).where(Activity.source == "resimpli", Activity.external_id == contact_id)
            ):
                db.add(
                    Activity(
                        external_id=contact_id,
                        lead_id=lead.id,
                        activity_type="historical_contact",
                        source="resimpli",
                        outcome=data.get("contact_outcome"),
                        occurred_at=parse_datetime(data["last_contact_at"], settings.app_timezone)
                        if data.get("last_contact_at")
                        else None,
                        summary="Source-provided contact metadata; no conversation transcript is implied.",
                        source_metadata={
                            "source_snapshot": True,
                            "original_last_contact_value": data.get("last_contact_at"),
                        },
                    )
                )
        old_notes = lead.source_data.get("normalized", {}).get("notes")
        if data.get("notes") and data["notes"] != old_notes:
            db.add(
                Activity(
                    lead_id=lead.id,
                    activity_type="source_note_snapshot",
                    source="resimpli",
                    summary=data["notes"],
                    source_metadata={"snapshot_at": utcnow().isoformat(), "original_note_time_unknown": True},
                )
            )
        lead.source_data = {
            **lead.source_data,
            "normalized": {
                **lead.source_data.get("normalized", {}),
                **{k: v for k, v in data.items() if v is not None},
            },
            "crm_fields": raw,
        }
        lead.source_kind = "resimpli_fixture" if settings.resimpli_mode == "fixture" else "resimpli"
    if data.get("contact_outcome") == "Do Not Contact":
        lead.source_do_not_contact = True
    if data.get("contact_outcome"):
        apply_source_outcome(
            db,
            lead,
            data["contact_outcome"],
            parse_datetime(data["last_contact_at"], settings.app_timezone) if data.get("last_contact_at") else None,
        )
    # A supported relationship array can be explicitly mapped to standardized property fields.
    for prop in raw.get("properties") or []:
        if not isinstance(prop, dict):
            raise IntegrationError("Malformed mapped property relationship")
        propdata, errors, _ = normalize_record(
            {**prop, "full_name": lead.full_name},
            {k: k for k in {**prop, "full_name": lead.full_name} if k in FIELDS},
            settings.app_timezone,
            "reject",
        )
        if errors:
            raise IntegrationError("Malformed mapped property relationship fields")
        attach_property(
            db, lead, propdata, {"source": "resimpli", "explicit_relationship": True}, update_from_source=True
        )
    lead.source_hash = list_hash
    lead.synced_at = utcnow()
    lead.detail_synced_at = utcnow()
    # Imported source follow-up dates are not repeatedly recreated after completion.
    if not is_new and data.get("next_followup_at"):
        due = parse_datetime(data["next_followup_at"], settings.app_timezone)
        existing = db.scalar(
            select(Followup).where(
                Followup.lead_id == lead.id,
                Followup.creation_source.in_(["resimpli", "resimpli_fixture"]),
                Followup.due_at == due,
            )
        )
        if not existing:
            db.add(
                Followup(
                    lead_id=lead.id,
                    due_at=due,
                    reason="Explicit follow-up date from REsimpli source",
                    creation_source="resimpli",
                )
            )
    update_next_followup(db, lead)
    db.flush()
    return lead, is_new


def upsert_activity(db, lead, record, kind, adapter, zone):
    if record.get("lead_external_id") is not None and str(record["lead_external_id"]) != str(lead.external_id):
        raise IntegrationError("Source activity relationship does not match the requested seller lead")
    external_id = record.get("external_id")
    if not external_id:
        raise IntegrationError(f"{kind} record missing stable external ID")
    external_id = f"{kind}:{external_id}"
    source = "resimpli"
    activity = db.scalar(select(Activity).where(Activity.source == source, Activity.external_id == external_id))
    if not activity:
        incoming_type = "call" if kind == "call" else (record.get("activity_type") or "source_activity")
        migrated = db.scalars(
            select(Activity).where(
                Activity.lead_id == lead.id,
                Activity.source.in_(["legacy_github", "resimpli"]),
                Activity.activity_type == incoming_type,
                Activity.source_metadata["legacy_external_id"].as_string() == str(record["external_id"]),
            )
        ).all()
        if len(migrated) == 1:
            activity = migrated[0]
            activity.source = "resimpli"
            # Retain this stable alias so both documented resources reconcile
            # the migrated event instead of duplicating it after the first sync.
            activity.external_id = external_id
    if not activity:
        activity = Activity(
            external_id=external_id,
            lead_id=lead.id,
            activity_type="call" if kind == "call" else (record.get("activity_type") or "source_activity"),
            source=source,
            summary="",
        )
        db.add(activity)
    activity.summary = str(record.get("summary") or "Source activity; message body/summary unavailable.")
    activity.direction = record.get("direction")
    # Only explicit, configured outcome mappings are contact evidence.
    raw_outcome = record.get("outcome")
    activity.outcome = adapter.contact_outcomes.get(str(raw_outcome)) if raw_outcome is not None else None
    activity.occurred_at = parse_datetime(record["occurred_at"], zone) if record.get("occurred_at") else None
    activity.source_metadata = {
        **(activity.source_metadata or {}),
        "mapped_source": record,
        "full_transcript_available": False,
    }
    if activity.outcome == "Do Not Contact":
        lead.source_do_not_contact = True
    if activity.activity_type not in NON_CONTACT_ACTIVITY_TYPES:
        apply_source_outcome(db, lead, activity.outcome, activity.occurred_at)


def sync_run(run_id, session_factory=SessionLocal, settings=None, client_factory=ResimpliClient):
    settings = settings or get_settings()
    if not SYNC_LOCK.acquire(blocking=False):
        with session_factory() as db:
            run = db.get(SyncRun, run_id)
            run.result, run.finished_at, run.errors = "failed", utcnow(), ["Concurrent sync prevented"]
            db.commit()
        return
    client = None
    try:
        with session_factory() as db:
            run = db.get(SyncRun, run_id)
            errors, resources = [], {"leads": 0, "activities": 0, "calls": 0, "appointments": 0}
            processed_ids = []
            try:
                client = client_factory(settings)
                client.request("/getUserInfo")
                for record in client.pages("/lead/list", client.adapter.leads):
                    run.fetched += 1
                    db.commit()
                    try:
                        ext = record.get("external_id")
                        if not ext:
                            raise IntegrationError("Lead ID missing in configured response mapping")
                        lead = db.scalar(select(Lead).where(Lead.external_id == str(ext)))
                        changed = not lead or lead.source_hash != digest(record)
                        deep_refresh = (
                            not lead
                            or not lead.detail_synced_at
                            or lead.detail_synced_at < utcnow() - timedelta(hours=settings.sync_deep_refresh_hours)
                        )
                        if changed or deep_refresh:
                            detail = client.details(str(ext))
                            # Missing optional detail fields must not erase list fields.
                            merged = {**record, **{k: v for k, v in detail.items() if v is not None}}
                            original_outcome = merged.get("contact_outcome")
                            if (
                                original_outcome is not None
                                and str(original_outcome) in client.adapter.contact_outcomes
                            ):
                                merged["source_original_contact_outcome"] = original_outcome
                                merged["contact_outcome"] = client.adapter.contact_outcomes[str(original_outcome)]
                            lead, is_new = upsert_lead(db, merged, settings, digest(record))
                            if is_new:
                                run.created += 1
                            else:
                                run.updated += 1
                        else:
                            lead.synced_at = utcnow()
                            run.skipped += 1
                        resources["leads"] += 1
                        processed_ids.append(lead.id)
                        db.commit()
                        for path, resource, kind in [
                            ("/activityList", client.adapter.activities, "activity"),
                            ("/callLogList", client.adapter.calls, "call"),
                        ]:
                            try:
                                for entry in client.pages(
                                    path, resource, {"moduleId": 1, "subModuleId": str(ext), "type": 1}
                                ):
                                    upsert_activity(db, lead, entry, kind, client.adapter, settings.app_timezone)
                                    resources["activities" if kind == "activity" else "calls"] += 1
                                db.commit()
                            except Exception as exc:
                                db.rollback()
                                errors.append(
                                    str(exc)
                                    if isinstance(exc, (IntegrationError, ValueError))
                                    else f"Local {kind} storage failed"
                                )
                                run.failed += 1
                                db.commit()
                    except Exception as exc:
                        db.rollback()
                        run = db.get(SyncRun, run_id)
                        run.failed += 1
                        errors.append(
                            str(exc) if isinstance(exc, (IntegrationError, ValueError)) else "Local lead storage failed"
                        )
                        db.commit()
                # Only seller appointments: request each documented seller subtype.
                for subtype in (0, 1, 2):
                    try:
                        for entry in client.pages(
                            "/appointmentList",
                            client.adapter.appointments,
                            {
                                "appointmentType": 0,
                                "appointmentSubType": subtype,
                                "appointmentStatus": 9,
                                "qualification": 9,
                            },
                        ):
                            if (
                                not entry.get("external_id")
                                or not entry.get("lead_external_id")
                                or not entry.get("starts_at")
                            ):
                                raise IntegrationError("Appointment mapping lacks ID, related lead ID or date")
                            lead = db.scalar(select(Lead).where(Lead.external_id == str(entry["lead_external_id"])))
                            if not lead:
                                raise IntegrationError(
                                    "Appointment references an unavailable seller lead; record left unlinked"
                                )
                            a = db.scalar(
                                select(Appointment).where(Appointment.external_id == str(entry["external_id"]))
                            )
                            if not a:
                                a = Appointment(
                                    external_id=str(entry["external_id"]),
                                    lead_id=lead.id,
                                    starts_at=utcnow(),
                                    source="resimpli",
                                )
                                db.add(a)
                            a.starts_at = parse_datetime(entry["starts_at"], settings.app_timezone)
                            a.source_status = str(entry.get("status")) if entry.get("status") is not None else None
                            a.status = client.adapter.appointment_statuses.get(str(entry.get("status")), "unknown")
                            a.notes = entry.get("notes")
                            a.source_metadata = {**(a.source_metadata or {}), "mapped_source": entry}
                            resources["appointments"] += 1
                        db.commit()
                    except Exception as exc:
                        db.rollback()
                        run.failed += 1
                        errors.append(
                            str(exc)
                            if isinstance(exc, (IntegrationError, ValueError))
                            else "Local appointment storage failed"
                        )
                        db.commit()
                # Analyze after ALL source resources, including appointments, are committed.
                # Evidence hashing avoids a model call when meaningful context is unchanged.
                from .ai import analyze_lead

                for lead_id in processed_ids:
                    analyze_lead(db, db.get(Lead, lead_id), settings)
                run.result = "partial" if errors else "success"
            except Exception as exc:
                db.rollback()
                run = db.get(SyncRun, run_id)
                errors.append(
                    str(exc)
                    if isinstance(exc, (IntegrationError, ValueError))
                    else "Unexpected synchronization failure; inspect local configuration"
                )
                run.result = "partial" if resources["leads"] else "failed"
                run.failed += 1
            run.errors, run.resources, run.finished_at = errors[:100], resources, utcnow()
            db.add(
                AuditLog(
                    action="sync_finished",
                    actor="scheduler",
                    details={"run_id": run.id, "result": run.result, "mode": run.mode},
                )
            )
            db.commit()
    finally:
        if client:
            client.close()
        SYNC_LOCK.release()
