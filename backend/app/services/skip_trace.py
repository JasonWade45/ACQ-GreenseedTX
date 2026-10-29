"""Skip-trace loop for address-only Data Syndicate leads.

Three reviewed steps, each explicit:

1. Export a skip-trace file (CSV) containing only the address fields and the local
   lead key. Nothing else leaves the app and nothing is sent anywhere by the app.
2. Jason runs the export through a skip-trace provider himself, then imports the
   result file here.
3. The preview matches every row to a local lead by lead key or normalized address
   and shows conflicts before a single field changes. Applying requires the same
   ``IMPORT LOCAL`` confirmation as every other local write.

A row that cannot be matched, or whose phone numbers fail validation, is rejected
with a reason and never creates a new lead.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import AuditLog, ImportBatch, ImportRow, Lead, LeadPhone, Property
from .normalization import (
    normalize_phone,
    normalize_address,
    csv_bytes,
)

CONFIRMATION = "IMPORT LOCAL"
EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+$")
SKIP_TRACE_PROFILE = "skip_trace_results"
EXPORT_HEADERS = ["lead_key", "address", "city", "state", "zip", "county", "lead_type", "recorded_date"]
RESULT_HEADERS = ["lead_key", "address", "city", "state", "zip", "owner_name", "phone1", "phone2", "phone3", "email"]


def _header_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


RESULT_ALIASES = {
    "leadkey": "lead_key",
    "key": "lead_key",
    "externalid": "lead_key",
    "address": "address",
    "propertyaddress": "address",
    "street": "address",
    "streetaddress": "address",
    "city": "city",
    "state": "state",
    "zip": "zip",
    "zipcode": "zip",
    "ownername": "owner_name",
    "owner": "owner_name",
    "fullname": "owner_name",
    "name": "owner_name",
    "phone1": "phone1",
    "phone": "phone1",
    "primaryphone": "phone1",
    "mobile": "phone1",
    "phone2": "phone2",
    "phone3": "phone3",
    "email": "email",
    "emailaddress": "email",
}


def export_rows(db: Session) -> list[dict]:
    """Address-only rows for leads that still need a skip trace."""
    rows = []
    leads = db.scalars(
        select(Lead)
        .where(Lead.needs_skip_trace.is_(True), Lead.in_license.is_(True), Lead.local_do_not_contact.is_(False))
        .order_by(Lead.priority_rank.desc().nullslast(), Lead.id)
    ).all()
    for lead in leads:
        prop = lead.properties[0] if lead.properties else None
        if prop is None or not prop.street_address:
            continue
        rows.append(
            {
                "lead_key": lead.external_id or f"local:{lead.id}",
                "address": prop.street_address,
                "city": prop.city,
                "state": prop.state,
                "zip": prop.zip_code,
                "county": lead.county,
                "lead_type": lead.lead_type,
                "recorded_date": lead.recorded_date.date().isoformat() if lead.recorded_date else None,
            }
        )
    return rows


def export_csv(db: Session) -> bytes:
    rows = export_rows(db)
    db.add(AuditLog(action="skip_trace_exported", details={"rows": len(rows)}))
    db.commit()
    return csv_bytes(rows, EXPORT_HEADERS)


def _split_csv_row(original: dict) -> dict:
    mapped = {}
    for header, value in original.items():
        key = RESULT_ALIASES.get(_header_key(header))
        if key:
            text = "" if value is None else str(value).strip()
            if text:
                mapped[key] = text
    return mapped


def prepare_preview(db: Session, batch: ImportBatch) -> dict:
    """Match every result row to a local lead without writing any lead field."""
    for row in db.scalars(select(ImportRow).where(ImportRow.batch_id == batch.id).order_by(ImportRow.id)):
        mapped = _split_csv_row(row.original)
        errors: list[str] = []
        lead = None
        if mapped.get("lead_key"):
            lead = db.scalar(select(Lead).where(Lead.external_id == mapped["lead_key"]))
            if lead is None:
                errors.append("Lead key does not match any local lead")
        if lead is None and mapped.get("address"):
            address_key = normalize_address(
                {
                    "street_address": mapped.get("address"),
                    "city": mapped.get("city"),
                    "state": mapped.get("state"),
                    "zip_code": mapped.get("zip"),
                }
            )
            property_row = db.scalar(select(Property).where(Property.normalized_address == address_key)) if address_key else None
            if property_row is not None:
                lead = db.scalar(
                    select(Lead).join(Lead.properties).where(Property.id == property_row.id)  # type: ignore[attr-defined]
                )
            if lead is None:
                errors.append("Address does not match any local lead")
        phones = []
        for key in ("phone1", "phone2", "phone3"):
            raw = mapped.get(key)
            if not raw:
                continue
            try:
                phones.append(normalize_phone(raw))
            except ValueError:
                errors.append(f"{key} is not a valid US phone number")
        email = mapped.get("email")
        if email and not EMAIL.fullmatch(email.lower()):
            errors.append("Email address is not valid")
        conflicts = []
        if lead is not None:
            if lead.source_kind == "resimpli" and phones and lead.primary_phone and lead.primary_phone not in phones:
                conflicts.append(
                    {
                        "field": "primary_phone",
                        "local": lead.primary_phone,
                        "incoming": phones[0],
                        "reason": "A CRM-synced phone number would be replaced by skip-trace data",
                    }
                )
            if lead.full_name and mapped.get("owner_name") and lead.full_name.strip().lower() != mapped["owner_name"].strip().lower():
                conflicts.append(
                    {
                        "field": "full_name",
                        "local": lead.full_name,
                        "incoming": mapped["owner_name"],
                        "reason": "A different owner name is already recorded",
                    }
                )
        row.normalized = {
            "lead_key": mapped.get("lead_key"),
            "owner_name": mapped.get("owner_name"),
            "phones": phones,
            "email": email.lower() if email else None,
            "address": mapped.get("address"),
            "city": mapped.get("city"),
            "state": mapped.get("state"),
            "zip": mapped.get("zip"),
        }
        row.candidates = [{"lead_id": lead.id, "name": lead.full_name}] if lead else []
        row.duplicate_kind = "matched_lead" if lead else "unmatched"
        row.errors = errors
        row.error = None
        row.state = "invalid" if errors else "ready"
    batch.state = "previewed"
    batch.counts = {
        "matched": db.query(ImportRow).filter_by(batch_id=batch.id, state="ready").count(),
        "rejected": db.query(ImportRow).filter_by(batch_id=batch.id, state="invalid").count(),
    }
    db.add(AuditLog(action="skip_trace_previewed", details={"batch_id": batch.id, **batch.counts}))
    db.commit()
    return preview_view(db, batch)


def preview_view(db: Session, batch: ImportBatch) -> dict:
    rows = db.scalars(select(ImportRow).where(ImportRow.batch_id == batch.id).order_by(ImportRow.id)).all()
    return {
        "batch_id": batch.id,
        "profile": batch.profile,
        "state": batch.state,
        "counts": {
            "rows": len(rows),
            "matched": sum(1 for r in rows if r.state == "ready"),
            "rejected": sum(1 for r in rows if r.state == "invalid"),
        },
        "rows": [
            {
                "id": row.id,
                "row_number": row.row_number,
                "state": row.state,
                "lead": (row.candidates or [None])[0],
                "incoming": row.normalized,
                "errors": row.errors,
                "original": row.original,
            }
            for row in rows
        ],
    }


def apply_results(db: Session, batch: ImportBatch, confirmation: str, resolutions: dict | None = None) -> dict:
    """Write matched owner/phone/email data after the explicit confirmation."""
    if confirmation != CONFIRMATION:
        raise ValueError(f"Type {CONFIRMATION} to confirm local writes")
    resolutions = resolutions or {}
    applied, skipped = 0, 0
    for row in db.scalars(select(ImportRow).where(ImportRow.batch_id == batch.id).order_by(ImportRow.id)):
        if row.state in {"imported", "skipped", "failed"}:
            continue
        if row.state != "ready" or not row.candidates:
            continue
        lead = db.get(Lead, row.candidates[0]["lead_id"])
        if lead is None:
            row.state, row.error = "failed", "Lead no longer exists"
            db.commit()
            continue
        decision = resolutions.get(str(row.id), "keep")
        incoming = row.normalized or {}
        crm_conflict = lead.source_kind == "resimpli" and lead.primary_phone and incoming.get("phones")
        if crm_conflict and decision != "overwrite":
            # Never replace a CRM-synced contact field without an explicit overwrite.
            _attach_phones(db, lead, incoming.get("phones") or [], make_primary=None)
            row.warnings = list(row.warnings or []) + ["Kept the CRM-synced primary phone; skip-trace phones were added"]
            skipped += 1
        else:
            _attach_phones(
                db,
                lead,
                incoming.get("phones") or [],
                make_primary=(incoming.get("phones") or [None])[0],
            )
            applied += 1
        if incoming.get("owner_name") and (decision == "overwrite" or not lead.full_name):
            lead.full_name = incoming["owner_name"].strip()[:300]
            parts = lead.full_name.split()
            lead.first_name = parts[0] if parts else lead.first_name
            lead.last_name = " ".join(parts[1:]) if len(parts) > 1 else lead.last_name
        if incoming.get("email") and (decision == "overwrite" or not lead.email):
            lead.email = incoming["email"]
        if lead.primary_phone:
            lead.needs_skip_trace = False
            lead.outreach_mode = "cold"
            from ..seed import stage_mapping

            if lead.stage_code in {"new", "unmapped", "not_contacted"} and not lead.local_stage_override:
                lead.stage_code = stage_mapping(db, "not contacted")
                lead.contact_status = lead.contact_status or "unknown"
        lead.updated_at = utcnow()
        lead.import_batch_id = str(batch.id)
        row.state = "imported"
        row.lead_id = lead.id
        db.add(
            AuditLog(
                lead_id=lead.id,
                action="skip_trace_applied",
                details={
                    "batch_id": batch.id,
                    "row": row.row_number,
                    "phones": len(incoming.get("phones") or []),
                    "overwrote_crm_phone": bool(crm_conflict and decision == "overwrite"),
                },
            )
        )
        db.commit()
    batch.state = "completed"
    batch.finished_at = utcnow()
    batch.counts = {"applied": applied, "kept_crm_phone": skipped}
    db.add(AuditLog(action="skip_trace_imported", details={"batch_id": batch.id, "applied": applied, "skipped": skipped}))
    db.commit()
    return {"batch_id": batch.id, "applied": applied, "kept_crm_phone": skipped, "external_writes": 0}


def _attach_phones(db: Session, lead: Lead, phones: list[str], make_primary: str | None) -> None:
    existing = {p.phone_normalized for p in lead.phones}
    for index, phone in enumerate(phones):
        if not phone or phone in existing:
            continue
        db.add(
            LeadPhone(
                lead_id=lead.id,
                phone=phone,
                phone_normalized=phone,
                is_primary=bool(make_primary and phone == make_primary and not lead.primary_phone),
                position=len(existing) + index,
                source_column="skip_trace",
            )
        )
        existing.add(phone)
    if make_primary and not lead.primary_phone:
        lead.primary_phone = make_primary
        lead.primary_phone_type = "skip_trace"
