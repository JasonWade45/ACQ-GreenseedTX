"""Periodic, read-only synchronisation with REsimpli.

Guarantees:
  * Never writes back to REsimpli (read-only by design).
  * Upserts on the stable REsimpli Object id — repeated syncs do not duplicate.
  * Distinguishes success / partial / failed / never-run.
  * Bounded retries with exponential backoff (inside the HTTP client).
  * Respects the documented rate limit with client-side throttling.
  * Pagination handled via {page, limit} with limit<=100.
  * There is no documented "modified since" filter, so a safe full
    reconciliation of the lead list is performed each run, while the expensive
    per-lead detail/activity calls are budgeted.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Activity, Appointment, Lead, SyncRun
from app.services.leads import link_property, primary_property, refresh_lead_rollups
from app.services.normalization import (
    clean_str,
    normalize_email,
    normalize_phone,
    parse_date_flexible,
    parse_datetime_flexible,
)
from app.services.pipeline import (
    ACTIVITY_TYPE_HINTS,
    infer_outcome_from_text,
    map_stage,
)
from app.services.property_extract import apply_property_data
from app.services.resimpli_client import (
    MockResimpliClient,
    ResimpliAuthError,
    ResimpliError,
    build_client,
    dig,
    normalize_activity_payload,
    normalize_appointment_payload,
    normalize_lead_payload,
    strip_html,
)
from app.services.settings_service import stage_mapping

logger = logging.getLogger("acquisitions.sync")

# Contact outcomes that count as real contact
CONTACT_OUTCOMES = {"connected", "callback_requested", "seller_not_interested", "appointment_scheduled"}


def get_client():
    """Build the appropriate client. Falls back to the mock when no key is set."""
    if settings.resimpli_mock:
        return MockResimpliClient()
    if not settings.resimpli_api_key.strip():
        return MockResimpliClient()
    return build_client(
        api_key=settings.resimpli_api_key,
        base_url=settings.resimpli_base_url,
        timeout=settings.resimpli_timeout_seconds,
        rate_limit=settings.resimpli_rate_limit_per_minute,
        max_retries=settings.resimpli_max_retries,
    )


def is_mock() -> bool:
    return settings.resimpli_mock or not settings.resimpli_api_key.strip()


# --------------------------------------------------------------------------- #
# Upserts
# --------------------------------------------------------------------------- #
def _looks_stringified_collection(value: str) -> bool:
    """True when a stored note is really `str(list)` / `str(dict)` garbage."""
    text = value.strip()
    if len(text) < 2 or text[0] not in "[{" or text[-1] not in "]}":
        return False
    return "':" in text or '":' in text


def upsert_lead_from_api(db: Session, normalized: dict[str, Any], mapping: dict[str, str]) -> tuple[Lead, bool]:
    external_id = normalized.get("external_id")
    lead: Optional[Lead] = None
    created = False
    if external_id:
        lead = db.query(Lead).filter(Lead.external_id == external_id).first()
    if lead is None:
        phone_norm, _, _ = normalize_phone(normalized.get("primary_phone"))
        email_norm = normalize_email(normalized.get("primary_email"))
        if phone_norm:
            lead = db.query(Lead).filter(Lead.phone_normalized == phone_norm).first()
        if lead is None and email_norm:
            lead = db.query(Lead).filter(Lead.email_normalized == email_norm).first()

    if lead is None:
        lead = Lead(origin="resimpli")
        db.add(lead)
        created = True

    lead.external_id = external_id or lead.external_id
    lead.first_name = clean_str(normalized.get("first_name")) or lead.first_name
    lead.last_name = clean_str(normalized.get("last_name")) or lead.last_name
    lead.full_name = clean_str(normalized.get("full_name")) or lead.full_name
    if not lead.full_name:
        # /lead/details often returns only first/last — compose a display name
        # so search, sorting and CSV export never show a blank seller name.
        composed = " ".join(p for p in (lead.first_name, lead.last_name) if p).strip()
        if composed:
            lead.full_name = composed
    phone_norm, phone_display, _ = normalize_phone(normalized.get("primary_phone"))
    if phone_norm:
        lead.primary_phone = phone_display or normalized.get("primary_phone")
        lead.phone_normalized = phone_norm
    email_norm = normalize_email(normalized.get("primary_email"))
    if email_norm:
        lead.email = normalized.get("primary_email")
        lead.email_normalized = email_norm
    lead.lead_source = clean_str(normalized.get("lead_source")) or lead.lead_source
    lead.assigned_manager = clean_str(normalized.get("assigned_manager")) or lead.assigned_manager
    lead.is_hot_lead = bool(normalized.get("is_hot_lead")) or lead.is_hot_lead

    source_status = clean_str(normalized.get("source_status"))
    if source_status:
        lead.source_status = source_status
        lead.pipeline_stage = map_stage(source_status, mapping)

    created_date, _w, _a = parse_date_flexible(normalized.get("original_creation_date"), "leadCreated")
    if created_date:
        lead.original_creation_date = created_date

    if normalized.get("do_not_contact"):
        lead.do_not_contact = True

    tags = normalized.get("tags") or []
    if tags:
        existing = lead.tags or []
        merged = list(dict.fromkeys([*existing, *[t for t in tags if isinstance(t, str)]]))
        lead.tags = merged

    notes = clean_str(normalized.get("notes"))
    if notes:
        if not lead.notes or _looks_stringified_collection(lead.notes):
            lead.notes = notes
    elif lead.notes and _looks_stringified_collection(lead.notes):
        # Structured note collections are stored as timeline activities; a
        # Python repr of a list/dict must never surface as a plain-text note.
        lead.notes = None

    if normalized.get("lead_id_override"):
        lead.id = normalized["lead_id_override"]

    # Keep the source record exactly as received — the field mappings above are
    # best-effort against an undocumented schema, so the raw payload is the
    # ground truth for re-mapping and debugging.
    raw = normalized.get("raw")
    if isinstance(raw, dict) and raw:
        lead.raw_payload = raw

    address = clean_str(normalized.get("address"))
    if address:
        link_property(db, lead, address_line1=address, replace=created)

    # Lift propertyInfo / valuation / taxInfo / mortgageInfo out of the raw
    # payload (local parse — no extra API calls) so beds/baths/value/etc.
    # are real columns instead of staying empty.
    apply_property_data(db, lead, raw if isinstance(raw, dict) else None)

    lead.last_synced_at = datetime.utcnow()
    lead.origin = "resimpli"
    db.flush()
    return lead, created


def upsert_activity_from_api(db: Session, lead: Lead, raw_activity: dict[str, Any]) -> tuple[Activity, bool]:
    norm = normalize_activity_payload(raw_activity, fallback_lead_id=lead.external_id)
    activity: Optional[Activity] = None
    created = False
    if norm["external_id"]:
        activity = db.query(Activity).filter(Activity.external_id == norm["external_id"]).first()
    if activity is None:
        occurred, _w, _a = parse_datetime_flexible(norm["occurred_at"], "activityDate")
        occurred = occurred or datetime.utcnow()
        # Skip obvious duplicates with identical timestamp + summary
        activity = (
            db.query(Activity)
            .filter(
                Activity.lead_id == lead.id,
                Activity.occurred_at == occurred,
                Activity.summary == norm["summary"],
            )
            .first()
        )
    if activity is None:
        activity = Activity(lead_id=lead.id, source="resimpli")
        db.add(activity)
        created = True

    activity.external_id = norm["external_id"] or activity.external_id
    atype = clean_str(norm["activity_type"]) or ""
    hints = ACTIVITY_TYPE_HINTS.get(atype.lower(), {})
    activity.activity_type = hints.get("activity_type") or (atype.lower() or "other")
    activity.direction = clean_str(norm["direction"]) or hints.get("direction")
    outcome = clean_str(norm["outcome"])
    activity.outcome = infer_outcome_from_text(outcome) or (outcome.lower() if outcome else None)
    occurred, _w, _a = parse_datetime_flexible(norm["occurred_at"], "activityDate")
    activity.occurred_at = occurred or activity.occurred_at or datetime.utcnow()
    recorded, _w, _a = parse_datetime_flexible(norm["recorded_at"], "createdDate")
    activity.recorded_at = recorded
    activity.summary = clean_str(norm["summary"])
    activity.detail = clean_str(norm["detail"]) or clean_str(norm["summary"])
    activity.raw_payload = norm["raw"]
    activity.lead_id = lead.id
    db.flush()
    return activity, created


def upsert_appointment_from_api(db: Session, raw: dict[str, Any], lead_lookup: dict[str, Lead]) -> tuple[Appointment, bool]:
    norm = normalize_appointment_payload(raw)
    appt: Optional[Appointment] = None
    created = False
    if norm["external_id"]:
        appt = db.query(Appointment).filter(Appointment.external_id == norm["external_id"]).first()
    if appt is None:
        appt = Appointment(source="resimpli")
        db.add(appt)
        created = True
    lead = lead_lookup.get(str(norm.get("lead_external_id") or ""))
    if lead is not None:
        appt.lead_id = lead.id
        prop = primary_property(lead)
        appt.property_id = prop.id if prop else None
    appt.external_id = norm["external_id"] or appt.external_id
    scheduled, _w, _a = parse_datetime_flexible(norm["scheduled_at"], "appointmentDateTime")
    appt.scheduled_at = scheduled or appt.scheduled_at or datetime.utcnow()
    end, _w, _a = parse_datetime_flexible(norm["end_at"], "endDateTime")
    appt.end_at = end
    status_raw = clean_str(norm["status"])
    appt.status = _map_appointment_status(status_raw, norm.get("appointment_status_raw"))
    appt.appointment_type = clean_str(norm["appointment_type"])
    appt.appointment_subtype = clean_str(norm["appointment_subtype"])
    appt.notes = clean_str(norm["notes"])
    appt.raw_payload = norm["raw"]
    db.flush()
    return appt, created


def _map_appointment_status(value: Optional[str], _extra: Any = None) -> str:
    if not value:
        return "scheduled"
    low = str(value).lower()
    if low in {"1", "kept", "confirmed"}:
        return "kept"
    if low in {"0", "no answer", "noanswer"}:
        return "no_answer"
    if low in {"2", "not kept", "missed", "no show"}:
        return "not_kept"
    if low in {"3", "dismiss", "dismissed", "cancelled", "canceled"}:
        return "dismissed"
    return low.replace(" ", "_")


# --------------------------------------------------------------------------- #
# Sync run
# --------------------------------------------------------------------------- #
def run_sync(db: Session, trigger: str = "manual") -> SyncRun:
    run = SyncRun(trigger=trigger, result="running", started_at=datetime.utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)

    client = get_client()
    mapping = stage_mapping(db)
    errors: list[str] = []
    fetched = created_count = updated_count = skipped = failed = 0
    detailed = activities_added = 0
    detail_budget = settings.sync_detail_budget

    try:
        # 0. Validate credentials before touching any data
        try:
            client.get_user_info()
        except ResimpliAuthError as exc:
            return _finish(db, run, "failed", str(exc), {})

        # 0b. Optional reference data: assignee id -> display name
        user_map: dict[str, str] = {}
        try:
            for user in client.users():
                if not isinstance(user, dict):
                    continue
                uid = dig(user, "_id", "id", "userId")
                name = dig(user, "fullName", "name") or " ".join(
                    p for p in (dig(user, "firstName"), dig(user, "lastName")) if p
                )
                if uid and name:
                    user_map[str(uid)] = str(name)
        except ResimpliError:
            logger.warning("Could not load /userList; assigned managers will show raw ids")

        def resolve_norm(norm: dict[str, Any]) -> dict[str, Any]:
            uid = norm.get("assigned_user_id")
            if uid and not norm.get("assigned_manager"):
                norm["assigned_manager"] = user_map.get(str(uid))
            return norm

        # 1. Paginated lead list (full reconciliation — no "modified since" filter
        #    is documented on /lead/list)
        page = 1
        seen_ids: set[str] = set()
        all_leads: list[Lead] = []
        while page <= settings.sync_max_pages:
            items, meta = client.list_leads(page=page, limit=settings.sync_page_limit)
            if not items:
                break
            for raw in items:
                fetched += 1
                try:
                    norm = resolve_norm(normalize_lead_payload(raw if isinstance(raw, dict) else {}))
                    if not norm.get("external_id") and not norm.get("primary_phone"):
                        skipped += 1
                        continue
                    lead, created = upsert_lead_from_api(db, norm, mapping)
                    if lead.external_id:
                        seen_ids.add(lead.external_id)
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                    all_leads.append(lead)
                except Exception as exc:  # noqa: BLE001 - isolate row failures
                    failed += 1
                    errors.append(f"Lead row failed: {exc.__class__.__name__}: {exc}")
            total_pages = meta.get("total_pages")
            if total_pages is not None and page >= int(total_pages):
                break
            if len(items) < settings.sync_page_limit:
                break
            page += 1

        db.commit()

        # 2. Budgeted enrichment: /lead/details + activity/call logs
        enrichable = [
            lead
            for lead in all_leads
            if lead.external_id and (lead.last_synced_at is None or lead.activities == [] or True)
        ]
        # Prefer leads with no activity yet, then oldest last_synced
        enrichable.sort(key=lambda lead: (len(lead.activities or []), lead.last_synced_at or datetime.min))
        for lead in enrichable[: max(0, detail_budget)]:
            if not lead.external_id:
                continue
            try:
                detail = client.lead_details(lead.external_id)
                payload = detail.get("data") if isinstance(detail, dict) and "data" in detail else detail
                if isinstance(payload, dict) and payload:
                    norm = resolve_norm(normalize_lead_payload(payload))
                    norm["external_id"] = lead.external_id
                    upsert_lead_from_api(db, norm, mapping)
                    # /lead/details nests notes under leadData; the mock keeps
                    # them at the top level — read both.
                    lead_obj = payload.get("leadData") if isinstance(payload.get("leadData"), dict) else payload
                    for note in lead_obj.get("notes") or []:
                        text = strip_html(note.get("text") if isinstance(note, dict) else str(note))
                        if not text:
                            continue
                        occurred, _w, _a = parse_datetime_flexible(
                            note.get("createdAt") if isinstance(note, dict) else None, "note.createdAt"
                        )
                        exists = (
                            db.query(Activity)
                            .filter(Activity.lead_id == lead.id, Activity.activity_type == "note", Activity.summary == text)
                            .first()
                        )
                        if not exists:
                            db.add(
                                Activity(
                                    lead_id=lead.id,
                                    activity_type="note",
                                    direction="internal",
                                    occurred_at=occurred or datetime.utcnow(),
                                    summary=text[:500],
                                    detail=text,
                                    source="resimpli",
                                )
                            )
                for raw_act in client.activity_list(lead.external_id):
                    try:
                        _, created = upsert_activity_from_api(db, lead, raw_act if isinstance(raw_act, dict) else {})
                        activities_added += 1 if created else 0
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"Activity failed for {lead.external_id}: {exc}")
                for raw_call in client.call_log_list(lead.external_id):
                    try:
                        _, created = upsert_activity_from_api(db, lead, raw_call if isinstance(raw_call, dict) else {})
                        activities_added += 1 if created else 0
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"Call log failed for {lead.external_id}: {exc}")
                detailed += 1
                db.commit()
            except ResimpliError as exc:
                errors.append(f"Detail fetch failed for {lead.external_id}: {exc}")
                db.rollback()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Detail fetch failed for {lead.external_id}: {exc}")
                db.rollback()

        # 3. Appointments (upcoming + recent past)
        lead_lookup = {lead.external_id: lead for lead in all_leads if lead.external_id}
        for upcoming in (True, False):
            try:
                for raw_appt in client.appointment_list(page=1, limit=100, is_upcoming=upcoming):
                    try:
                        upsert_appointment_from_api(db, raw_appt if isinstance(raw_appt, dict) else {}, lead_lookup)
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"Appointment failed: {exc}")
                db.commit()
            except ResimpliError as exc:
                errors.append(f"Appointment list failed (upcoming={upcoming}): {exc}")
                db.rollback()

        # 4. Rollups
        for lead in all_leads:
            try:
                refresh_lead_rollups(db, lead)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Rollup failed for {lead.id}: {exc}")
        db.commit()

        result = "success" if not errors else ("partial" if created_count + updated_count > 0 else "failed")
        detail = {
            "detailed": detailed,
            "activities_added": activities_added,
            "pages": page,
            "mock": is_mock(),
            "errors": errors[:25],
            "request_log": getattr(client, "request_log", [])[-10:],
        }
        return _finish(db, run, result, "; ".join(errors[:5]) or None, detail, fetched, created_count, updated_count, skipped, failed)
    except ResimpliError as exc:
        db.rollback()
        return _finish(db, run, "failed", str(exc), {"mock": is_mock()})
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("Sync failed")
        return _finish(db, run, "failed", f"{exc.__class__.__name__}: {exc}", {"mock": is_mock()})
    finally:
        client.close()


def _finish(
    db: Session,
    run: SyncRun,
    result: str,
    error: Optional[str],
    detail: dict[str, Any],
    fetched: int = 0,
    created: int = 0,
    updated: int = 0,
    skipped: int = 0,
    failed: int = 0,
) -> SyncRun:
    run.result = result
    run.error = error
    run.detail = detail
    run.records_fetched = fetched
    run.created_count = created
    run.updated_count = updated
    run.skipped_count = skipped
    run.failed_count = failed
    run.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    return run


def serialize_sync_run(run: SyncRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_seconds": (
            round((run.finished_at - run.started_at).total_seconds())
            if run.started_at and run.finished_at
            else None
        ),
        "result": run.result,
        "trigger": run.trigger,
        "records_fetched": run.records_fetched,
        "created_count": run.created_count,
        "updated_count": run.updated_count,
        "skipped_count": run.skipped_count,
        "failed_count": run.failed_count,
        "error": run.error,
        "detail": run.detail or {},
    }


def sync_state(db: Session) -> dict[str, Any]:
    """Explicit sync health — never pretends stale data is fresh."""
    from app.scheduler import scheduler_state
    from app.services.settings_service import get_setting

    stored_interval = get_setting(db, "sync_interval_minutes")
    interval_minutes = int(stored_interval or settings.sync_interval_minutes)

    last = db.query(SyncRun).order_by(SyncRun.started_at.desc()).first()
    leads_total = db.query(Lead).count()
    synced_leads = db.query(Lead).filter(Lead.last_synced_at.isnot(None)).count()
    if last is None:
        health = "never_run"
        last_success = None
    else:
        last_success_row = (
            db.query(SyncRun).filter(SyncRun.result.in_(["success", "partial"])).order_by(SyncRun.finished_at.desc()).first()
        )
        last_success = (
            serialize_sync_run(last_success_row) if last_success_row else None
        )
        if last.result == "failed":
            health = "failed"
        elif last.result == "partial":
            health = "partial"
        elif last.result == "running":
            health = "running"
        else:
            age_minutes = (datetime.utcnow() - (last.finished_at or datetime.utcnow())).total_seconds() / 60
            health = "healthy" if age_minutes <= max(60, interval_minutes * 2) else "stale"

    return {
        "health": health,
        "mock_mode": is_mock(),
        "api_key_configured": bool(settings.resimpli_api_key.strip()),
        "last_run": serialize_sync_run(last) if last else None,
        "last_success": last_success,
        "leads_in_database": leads_total,
        "leads_ever_synced": synced_leads,
        "data_is_live": bool(last and last.result in {"success", "partial"}),
        "scheduler": scheduler_state(),
        "rate_limit_per_minute": settings.resimpli_rate_limit_per_minute,
        "interval_minutes": interval_minutes,
        "sync_enabled": bool(get_setting(db, "sync_enabled")),
    }
