"""Reviewed GitHub/Next workspace migration into the unified schema.

Reads a consistent private SQLite snapshot, never writes the original DB, never
calls an AI/CRM, and never automatically resolves uncertain person matches.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from pathlib import Path
import sqlite3
import threading
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from .. import config
from ..db import utcnow
from ..models import Lead, Activity, Followup, Appointment, WorkspaceMerge, AuditLog
from .imports import create_local_lead, attach_property, DuplicateIndex
from .normalization import normalize_phone, normalize_address, parse_datetime
from .leads import NON_CONTACT_ACTIVITY_TYPES, update_next_followup
from .sync import apply_source_outcome
from .ai import context_for, context_hash

LOCK = threading.Lock()
OUTCOMES = {
    "connected": "Connected",
    "no_answer": "No Answer",
    "left_voicemail": "Left Voicemail",
    "callback_requested": "Callback Requested",
    "wrong_number": "Wrong Number",
    "do_not_contact": "Do Not Contact",
    "seller_not_interested": "Seller Not Interested",
    "appointment_scheduled": "Appointment Scheduled",
    "offer_accepted": "Offer Accepted",
    "offer_rejected": "Offer Rejected",
    "other": "Other",
}


def _decode(value, fallback=None):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return fallback


def _date(value):
    if not value:
        return None
    try:
        if len(str(value)) == 10:
            return parse_datetime(str(value), config.get_settings().app_timezone, "MDY")
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        # Source models use datetime.utcnow and store UTC without a SQLite offset.
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _read(path):
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA trusted_schema=OFF")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {row[1] for row in db.execute("PRAGMA table_info(leads)")}
        if not {"pipeline_stage", "phone_normalized", "origin"}.issubset(columns):
            raise ValueError(
                "This is not the GitHub/Next workspace schema. Do not run either app migrations on the other database."
            )
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Source database integrity failed")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError(
                "Source database has broken relationships; keep the original and review a trusted backup before conversion"
            )
        allowed = [
            "leads",
            "properties",
            "lead_properties",
            "activities",
            "appointments",
            "followups",
            "ai_insights",
            "message_drafts",
            "call_plans",
            "import_batches",
            "import_records",
            "mapping_templates",
            "sync_runs",
            "audit_log",
        ]
        data = {
            table: [dict(row) for row in db.execute('SELECT * FROM "' + table + '" ORDER BY id')]
            for table in allowed
            if table in tables
        }
        if any(
            isinstance(value, float) and not math.isfinite(value)
            for rows in data.values()
            for row in rows
            for value in row.values()
        ):
            raise ValueError(
                "Non-finite numbers in the legacy database require review in a trusted copy; no records were migrated"
            )
        return data


def _fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _lead_hash(db, lead):
    return hashlib.sha256(
        (
            context_hash(lead, context_for(db, lead))
            + "|"
            + str(lead.email)
            + "|"
            + str(lead.first_name)
            + "|"
            + str(lead.last_name)
        ).encode()
    ).hexdigest()


def _properties(data, source_id):
    by_id = {str(row["id"]): row for row in data.get("properties", [])}
    return [
        by_id[str(link["property_id"])]
        for link in data.get("lead_properties", [])
        if str(link["lead_id"]) == str(source_id) and str(link["property_id"]) in by_id
    ]


def _property(row):
    value = {
        k: row.get(v)
        for k, v in {
            "external_property_id": "external_id",
            "street_address": "address_line1",
            "city": "city",
            "state": "state",
            "zip_code": "zip_code",
            "property_type": "property_type",
            "bedrooms": "bedrooms",
            "bathrooms": "bathrooms",
            "square_feet": "square_footage",
            "year_built": "year_built",
            "asking_price": "asking_price",
            "estimated_value": "estimated_value",
            "repair_estimate": "repair_estimate",
            "county": "county",
            "lot_acres": "lot_acres",
        }.items()
    }
    if row.get("address_line2") and value["street_address"]:
        value["street_address"] += ", " + row["address_line2"]
    for key in ("bedrooms", "square_feet", "year_built"):
        if value.get(key) is not None:
            try:
                number = float(value[key])
                value[key] = int(number) if number.is_integer() and number >= 0 else None
            except (TypeError, ValueError):
                value[key] = None
    extra = _decode(row.get("extra"), {})
    from .property_facts import source_property_facts

    value.update(
        {
            k: v
            for k, v in source_property_facts(
                {
                    "propertyInfo": extra.get("property_info", {}),
                    "valuation": extra.get("valuation", {}),
                    "taxInfo": extra.get("tax", {}),
                    "mortgageInfo": extra.get("mortgage", {}),
                }
            ).items()
            if value.get(k) is None
        }
    )
    value["normalized_address"] = normalize_address(value)
    return value


def _lead_data(row, properties):
    phone = None
    try:
        phone = normalize_phone(row.get("primary_phone") or row.get("phone_normalized"))
    except ValueError:
        pass
    full = row.get("full_name") or " ".join(str(row.get(k) or "") for k in ("first_name", "last_name")).strip()
    value = {
        key: row.get(key)
        for key in (
            "external_id",
            "first_name",
            "last_name",
            "email",
            "lead_source",
            "source_status",
            "assigned_manager",
        )
    }
    value.update(
        notes=row.get("notes"),
        original_created_at=(
            _date(row.get("original_creation_date")).isoformat() if _date(row.get("original_creation_date")) else None
        ),
        full_name=full or "",
        primary_phone=phone,
        source_do_not_contact=True if row.get("do_not_contact") else None,
        record_kind="seller" if full else "property_only",
    )
    if value.get("email"):
        email = str(value["email"]).strip().lower()
        value["email"] = email if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) else None
    if properties:
        value.update(_property(properties[0]))
    # Neither pipeline nor legacy "never_contacted" proves a contact event.
    return value


def prepare_merge(db, source_path, storage_dir=None):
    if not LOCK.acquire(blocking=False):
        raise ValueError("Another workspace migration/review is running")
    try:
        return _prepare_merge(db, source_path, storage_dir)
    except sqlite3.Error:
        raise ValueError(
            "Could not safely snapshot/read that SQLite database. Check the selected file and permissions; keep both originals. No records were merged."
        ) from None
    finally:
        LOCK.release()


def _prepare_merge(db, source_path, storage_dir=None):
    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise ValueError("Select an existing local GitHub workspace SQLite database")
    destination = db.get_bind().url.database
    if destination and destination != ":memory:" and source == Path(destination).resolve():
        raise ValueError("Source and target must be different databases")
    default_folder = (
        Path(destination).resolve().parent / "workspace-merges"
        if destination and destination != ":memory:"
        else config.ROOT / "data/workspace-merges"
    )
    folder = Path(storage_dir or default_folder)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    job_id = str(uuid4())
    snapshot = folder / (job_id + "-source.db")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(snapshot) as dst:
        src.backup(dst)
    snapshot.chmod(0o600)
    try:
        data = _read(snapshot)
    except Exception:
        snapshot.unlink(missing_ok=True)
        raise
    fingerprint = _fingerprint(data)
    previous = db.scalar(
        select(WorkspaceMerge)
        .where(WorkspaceMerge.source_fingerprint == fingerprint)
        .order_by(WorkspaceMerge.created_at.desc())
    )
    if previous:
        snapshot.unlink()
        return previous
    # Recoverable target backup before any migration ledger or seller writes.
    if destination and destination != ":memory:" and Path(destination).exists():
        backup = folder / (job_id + "-target-before.db")
        with (
            sqlite3.connect(Path(destination).resolve().as_uri() + "?mode=ro", uri=True) as src,
            sqlite3.connect(backup) as dst,
        ):
            src.backup(dst)
        backup.chmod(0o600)
    previous_map = {}
    for old in db.scalars(select(WorkspaceMerge)):
        previous_map.update(old.mapping or {})
    index = DuplicateIndex(db)
    plan = []
    for row in data["leads"]:
        sid = str(row["id"])
        props = _properties(data, sid)
        value = _lead_data(row, props)
        kind, candidates = index.match(value)
        prior = previous_map.get(sid)
        if prior and db.get(Lead, prior):
            kind = "previously_migrated"
            candidates = [{"lead_id": prior}]
        normalized = []
        for candidate in candidates:
            target = db.get(Lead, candidate.get("lead_id"))
            if not target:
                continue
            conflicts = [
                field
                for field in ("full_name", "primary_phone", "email")
                if getattr(target, field)
                and value.get(field)
                and str(getattr(target, field)).lower() != str(value[field]).lower()
            ]
            normalized.append(
                {
                    "lead_id": target.id,
                    "name": target.full_name or "Owner unknown",
                    "address": target.properties[0].street_address if target.properties else None,
                    "conflicting_fields": conflicts,
                    "target_hash": _lead_hash(db, target),
                }
            )
        plan.append(
            {
                "source_id": sid,
                "name": value.get("full_name") or "Owner unknown (not an invented seller name)",
                "address": value.get("street_address"),
                "external_id": value.get("external_id"),
                "kind": kind,
                "candidates": normalized,
                "status": "pending",
                "warnings": [
                    "Legacy contact/pipeline classifications are not promoted without actual outcome evidence.",
                    "Original source DB and all historical artifacts remain preserved in the private snapshot.",
                ],
            }
        )
    job = WorkspaceMerge(
        id=job_id,
        source_fingerprint=fingerprint,
        source_name=source.name,
        snapshot_path=str(snapshot),
        plan=plan,
        mapping={},
        status="prepared" if plan else "completed",
        completed_at=None if plan else utcnow(),
        counts={
            "source_leads": len(plan),
            "source_tables": {name: len(rows) for name, rows in data.items()},
            "created": 0,
            "linked": 0,
            "skipped": 0,
            "failed": 0,
        },
    )
    db.add(job)
    db.add(
        AuditLog(
            action="workspace_merge_prepared",
            details={"job_id": job_id, "source_leads": len(plan), "source_modified": False, "external_calls": 0},
        )
    )
    db.commit()
    return job


def refresh_review(db, job):
    if not LOCK.acquire(blocking=False):
        raise ValueError("Another workspace migration/review is running")
    try:
        return _refresh_review(db, job)
    finally:
        LOCK.release()


def _refresh_review(db, job):
    if job.status == "completed":
        return job
    data = _read(job.snapshot_path)
    if _fingerprint(data) != job.source_fingerprint:
        raise ValueError("Private snapshot changed; do not approve this review")
    by_id = {str(row["id"]): row for row in data["leads"]}
    index = DuplicateIndex(db)
    rows = deepcopy(job.plan)
    mapped = {}
    for old in db.scalars(select(WorkspaceMerge)):
        mapped.update(old.mapping or {})
    for item in rows:
        if item["status"] != "pending":
            continue
        sid = item["source_id"]
        value = _lead_data(by_id[sid], _properties(data, sid))
        kind, candidates = index.match(value)
        if mapped.get(sid) and db.get(Lead, mapped[sid]):
            kind = "previously_migrated"
            candidates = [{"lead_id": mapped[sid]}]
        item["kind"] = kind
        item["candidates"] = []
        for candidate in candidates:
            target = db.get(Lead, candidate.get("lead_id"))
            if not target:
                continue
            db.refresh(target)
            db.expire(target, ["properties"])
            conflicts = [
                field
                for field in ("full_name", "primary_phone", "email")
                if getattr(target, field)
                and value.get(field)
                and str(getattr(target, field)).lower() != str(value[field]).lower()
            ]
            item["candidates"].append(
                {
                    "lead_id": target.id,
                    "name": target.full_name or "Owner unknown",
                    "address": target.properties[0].street_address if target.properties else None,
                    "conflicting_fields": conflicts,
                    "target_hash": _lead_hash(db, target),
                }
            )
    job.plan = rows
    job.counts = {**job.counts, "review_revision": job.counts.get("review_revision", 0) + 1}
    db.add(
        AuditLog(
            action="workspace_pending_review_refreshed",
            details={"merge_id": job.id, "committed_records_unchanged": True},
        )
    )
    db.commit()
    return job


def _source_event_date(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        try:
            number = float(value)
            if not math.isfinite(number):
                return None
            if number >= 1e14:
                number /= 1000000
            elif number >= 1e11:
                number /= 1000
            return datetime.fromtimestamp(number, tz=timezone.utc) if 1000000000 <= number <= 4000000000 else None
        except (ValueError, OverflowError, OSError):
            return None
    try:
        return parse_datetime(str(value), config.get_settings().app_timezone, "reject")
    except ValueError:
        return None


def _legacy_contact(old):
    raw = _decode(old.get("raw_payload"), {})
    raw = raw if isinstance(raw, dict) else {}
    # Remote code inferred "disconnected" as "connected" and filled missing
    # event dates with now. Do not inherit either inference as verified evidence.
    if old.get("source") == "resimpli":
        evidence = raw.get("outcome") or raw.get("callOutcome") or raw.get("voiceCallStatus")
        if isinstance(evidence, dict):
            evidence = evidence.get("name") or evidence.get("title") or evidence.get("label")
        label = re.sub(r"[\s-]+", "_", str(evidence or "").strip().lower())
        explicit = {
            **OUTCOMES,
            "noanswer": "No Answer",
            "voicemail": "Left Voicemail",
            "answered": "Connected",
            "disconnected": "Wrong Number",
            "dnc": "Do Not Contact",
        }
        outcome = (
            "Connected" if raw.get("iscallConnected") is True or raw.get("isConnected") is True else explicit.get(label)
        )
        stamp = None
        for key in ("activityDate", "date", "calledAt", "occurredAt", "activityTime", "createdAt"):
            if raw.get(key):
                stamp = _source_event_date(raw[key])
                if stamp:
                    break
    else:
        outcome = OUTCOMES.get(old.get("outcome"), old.get("outcome"))
        stamp = _date(old.get("occurred_at"))
    from ..schemas import OUTCOMES as canonical

    if outcome not in canonical:
        outcome = None
    if old.get("outcome") == "do_not_contact":
        outcome = "Do Not Contact"
    return outcome, stamp


def merge_dict(job, detail=False):
    result = {key: getattr(job, key) for key in ("id", "source_name", "status", "counts", "created_at", "completed_at")}
    result["pending"] = sum(item["status"] == "pending" for item in job.plan)
    if detail:
        result["records"] = job.plan
    result["privacy"] = (
        "Local-only review. Source snapshots/backups contain confidential seller data; no provider/CRM request is made."
    )
    return result


def _transplant_children(db, lead, row, data, job, allow_fill=False):
    sid = str(row["id"])
    marker = "legacy_github"
    # Keep complete historical lead/AI/draft/preparation provenance, not active unverified output.
    archive = {
        "lead": row,
        "insights": [r for r in data.get("ai_insights", []) if str(r["lead_id"]) == sid],
        "drafts": [r for r in data.get("message_drafts", []) if str(r["lead_id"]) == sid],
        "call_plans": [r for r in data.get("call_plans", []) if str(r["lead_id"]) == sid],
    }
    legacy = deepcopy(lead.source_data.get("legacy_workspaces", {}))
    legacy[sid] = {"job_id": job.id, "archive": archive}
    lead.source_data = {**lead.source_data, "legacy_workspaces": legacy}
    if row.get("do_not_contact"):
        lead.local_do_not_contact = True
    for prop_row in _properties(data, sid):
        values = _property(prop_row)
        current = next(
            (
                p
                for p in lead.properties
                if (values.get("external_property_id") and p.external_id == values["external_property_id"])
                or (values.get("normalized_address") and p.normalized_address == values["normalized_address"])
            ),
            None,
        )
        prop = (
            current
            if current and not allow_fill
            else attach_property(
                db, lead, values, {"source": "legacy_github", "legacy_property_id": str(prop_row["id"])}
            )
        )
        if current and allow_fill:
            from .research import fill_empty_fields

            fill_empty_fields(
                db, lead, values, {"workspace_merge_id": job.id, "legacy_property_id": str(prop_row["id"])}
            )
        if prop:
            prop.property_metadata = {**prop.property_metadata, "legacy_property": prop_row}
    existing = set(db.scalars(select(Activity.external_id).where(Activity.source == marker)).all())
    for old in data.get("activities", []):
        if str(old.get("lead_id")) != sid:
            continue
        key = "legacy-activity:" + str(old["id"])
        if key in existing:
            continue
        source_type = old.get("activity_type") or "other"
        if source_type in {"task", "status_change", "followup_completed"}:
            source_type = "stage_change" if source_type == "status_change" else "note"
        outcome, stamp = _legacy_contact(old)
        if outcome == "Do Not Contact":
            lead.local_do_not_contact = True
        if source_type in NON_CONTACT_ACTIVITY_TYPES and outcome != "Do Not Contact":
            outcome = None
        crm_id = str(old.get("external_id") or "")
        # Stable official event IDs outrank a second workspace's local UUID.
        if crm_id and old.get("source") == "resimpli":
            candidates = {crm_id, "activity:" + crm_id, "call:" + crm_id}
            existing_official = db.scalar(
                select(Activity).where(Activity.source == "resimpli", Activity.external_id.in_(candidates))
            )
            if existing_official:
                if existing_official.lead_id != lead.id:
                    raise ValueError(
                        "Official CRM activity is already attached to a different seller; review this identity conflict"
                    )
                existing_official.source_metadata = {
                    **existing_official.source_metadata,
                    "legacy_record": old,
                    "merge_id": job.id,
                }
                continue
        activity = Activity(
            lead_id=lead.id,
            external_id=key,
            activity_type=source_type,
            direction=old.get("direction"),
            outcome=outcome,
            occurred_at=stamp,
            recorded_at=_date(old.get("recorded_at") or old.get("created_at")) or utcnow(),
            summary=old.get("summary") or old.get("detail") or "Legacy activity record (summary unavailable)",
            source=marker,
            source_metadata={
                "legacy_record": old,
                "merge_id": job.id,
                "legacy_external_id": str(old.get("external_id"))
                if old.get("external_id") and old.get("source") == "resimpli"
                else None,
                "legacy_utc_storage": True,
                "original_date_preserved_in_archive": old.get("occurred_at"),
                "date_evidence_missing": stamp is None,
            },
        )
        db.add(activity)
        existing.add(key)
        if source_type not in NON_CONTACT_ACTIVITY_TYPES | {"task", "status_change", "followup_completed"} and outcome:
            # Explicit canonical outcomes are evidence; legacy stage/contact labels alone are not.
            apply_source_outcome(db, lead, outcome, stamp)
    # Legacy UUIDs are stable across snapshots, so resuming/re-importing avoids duplicate tasks.
    prior_tasks = {
        str(r)
        for r in db.scalars(
            select(Followup.reason).where(Followup.lead_id == lead.id, Followup.creation_source == marker)
        )
    }
    for old in data.get("followups", []):
        if str(old.get("lead_id")) != sid:
            continue
        key = "[Legacy " + str(old["id"]) + "] "
        reason = key + (old.get("reason") or "Imported follow-up")
        if any(reason_text.startswith(key) for reason_text in prior_tasks):
            continue
        status = {"open": "pending", "completed": "completed", "cancelled": "cancelled"}.get(
            old.get("status"), "pending"
        )
        db.add(
            Followup(
                lead_id=lead.id,
                due_at=_date(old.get("due_at")),
                priority=max(0, min(100, int(old.get("priority") or 1) * 20)),
                reason=reason,
                suggested_action=old.get("suggested_next_action"),
                status=status,
                completed_at=_date(old.get("completed_at")),
                completion_outcome=OUTCOMES.get(old.get("completion_outcome"), old.get("completion_outcome")),
                creation_source=marker,
                ai_suggested=bool(old.get("ai_suggested")),
                created_at=_date(old.get("created_at")) or utcnow(),
            )
        )
    for old in data.get("appointments", []):
        if str(old.get("lead_id")) != sid:
            continue
        key = (
            str(old["external_id"])
            if old.get("source") == "resimpli" and old.get("external_id")
            else "legacy-appointment:" + str(old["id"])
        )
        existing_appointment = db.scalar(select(Appointment).where(Appointment.external_id == key))
        if existing_appointment:
            if existing_appointment.lead_id != lead.id:
                raise ValueError("Official CRM appointment belongs to another seller; review before linking")
            existing_appointment.source_metadata = {
                **existing_appointment.source_metadata,
                "legacy_record": old,
                "merge_id": job.id,
            }
            continue
        stamp = _date(old.get("scheduled_at"))
        if not stamp:
            continue
        db.add(
            Appointment(
                lead_id=lead.id,
                external_id=key,
                starts_at=stamp,
                status="scheduled" if old.get("status") == "scheduled" else "unknown",
                source_status=old.get("status"),
                notes=old.get("notes"),
                source=marker,
                source_metadata={"legacy_record": old, "merge_id": job.id},
            )
        )
    db.flush()
    update_next_followup(db, lead)


def commit_merge(db, job, confirmation, decisions):
    if confirmation != "MERGE REVIEWED RECORDS":
        raise ValueError(
            "Type MERGE REVIEWED RECORDS; originals remain untouched and no automatic person merge is allowed"
        )
    if not LOCK.acquire(blocking=False):
        raise ValueError("Another workspace merge is running")
    try:
        data = _read(job.snapshot_path)
        if _fingerprint(data) != job.source_fingerprint:
            raise ValueError("Private snapshot changed; prepare a fresh review")
        source_rows = {str(row["id"]): row for row in data["leads"]}
        already_mapped = {}
        for prior in db.scalars(select(WorkspaceMerge)):
            already_mapped.update(prior.mapping or {})
        rows = deepcopy(job.plan)
        by_id = {item["source_id"]: item for item in rows}
        if len({item["source_id"] for item in decisions}) != len(decisions):
            raise ValueError("Choose each source record at most once")
        for decision in decisions:
            sid = decision["source_id"]
            item = by_id.get(sid)
            if not item:
                raise ValueError("Unknown source record")
            if item["status"] != "pending":
                continue
            action = decision["action"]
            source = source_rows[sid]
            value = _lead_data(source, _properties(data, sid))
            if action == "link":
                candidate = next((c for c in item["candidates"] if c["lead_id"] == decision.get("target_id")), None)
                if not candidate:
                    raise ValueError("Link only to a reviewed candidate from this preview")
                target = db.get(Lead, decision["target_id"])
                if target:
                    db.refresh(target)
                    db.expire(target, ["properties"])
                if not target or _lead_hash(db, target) != candidate["target_hash"]:
                    raise ValueError(
                        "Target changed after preview. Refresh pending matches and review again before linking"
                    )
                if value.get("external_id") and target.external_id and value["external_id"] != target.external_id:
                    raise ValueError("Different CRM identities must remain separate")
                known_phone = value.get("primary_phone") and value["primary_phone"] == target.primary_phone
                known_email = value.get("email") and value["email"] == target.email
                known_id = value.get("external_id") and value["external_id"] == target.external_id
                if "full_name" in candidate["conflicting_fields"] and not (known_phone or known_email or known_id):
                    raise ValueError(
                        "Same property is not the same seller. Keep these known conflicting people separate"
                    )
            elif action == "separate":
                if item["kind"] == "previously_migrated" or (
                    already_mapped.get(sid) and db.get(Lead, already_mapped[sid])
                ):
                    raise ValueError(
                        "This stable legacy identity was already migrated; link/review or skip instead of duplicating it"
                    )
                if value.get("external_id") and db.scalar(
                    select(Lead.id).where(Lead.external_id == value["external_id"])
                ):
                    raise ValueError("CRM identity already exists; review/link it rather than duplicate it")
            elif action != "skip":
                raise ValueError("Choose separate, link or skip explicitly")
        for decision in decisions:
            sid = decision["source_id"]
            item = by_id[sid]
            if item["status"] != "pending":
                continue
            action = decision["action"]
            old = source_rows[sid]
            if action == "skip":
                item["status"] = "skipped"
                job.counts = {**job.counts, "skipped": job.counts.get("skipped", 0) + 1}
            else:
                value = _lead_data(old, _properties(data, sid))
                if action == "link":
                    lead = db.get(Lead, decision["target_id"])
                    if value.get("external_id") and not lead.external_id:
                        # Explicit person-link approval also binds an available stable
                        # CRM identity, preventing the next read-only sync duplicating it.
                        lead.external_id = value["external_id"]
                        lead.source_data = {
                            **lead.source_data,
                            "legacy_crm_binding": {
                                "external_id": value["external_id"],
                                "merge_id": job.id,
                                "source_id": sid,
                                "approved_link": True,
                            },
                        }
                    if decision.get("fill_missing"):
                        from .research import fill_empty_fields

                        fill_empty_fields(db, lead, value, {"workspace_merge_id": job.id, "legacy_id": sid})
                    count_key = "linked"
                else:
                    lead = create_local_lead(db, value, old, source_kind="legacy_github")
                    stage = old.get("pipeline_stage")
                    from ..models import PipelineStage

                    if db.get(PipelineStage, stage):
                        lead.stage_code = stage
                        lead.local_stage_override = True
                    lead.original_created_at = _date(old.get("original_creation_date"))
                    if _date(old.get("created_at")):
                        lead.created_at = _date(old["created_at"])
                    count_key = "created"
                _transplant_children(
                    db, lead, old, data, job, allow_fill=action == "separate" or decision.get("fill_missing", False)
                )
                job.mapping = {**job.mapping, sid: lead.id}
                item["status"] = "linked" if action == "link" else "imported"
                item["target_id"] = lead.id
                job.counts = {**job.counts, count_key: job.counts.get(count_key, 0) + 1}
            job.plan = deepcopy(rows)
            job.status = "partial"
            db.add(
                AuditLog(
                    action="legacy_record_migrated",
                    lead_id=item.get("target_id"),
                    details={"merge_id": job.id, "source_id": sid, "action": action, "crm_write": False},
                )
            )
            db.commit()
        job.status = "completed" if all(item["status"] != "pending" for item in rows) else "partial"
        if job.status == "completed":
            job.completed_at = utcnow()
        db.commit()
        return job
    except SQLAlchemyError:
        db.rollback()
        raise ValueError(
            "Local migration stopped on a database constraint. Earlier committed rows remain preserved; review the pending records and private backups. No CRM request was made."
        ) from None
    except Exception:
        db.rollback()
        raise
    finally:
        LOCK.release()
