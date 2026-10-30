"""Copy the old Acquisition CRM Hub SQLite workspace into the unified database.

The old project used a different schema (single address, ``status`` strings, its own
call log and assignment tables). This script reads it read-only and creates unified
leads through the same ``create_local_lead`` path as an import, preserving source id,
owner, tags, follow-ups and the original row as provenance.

Safe by default: run with ``--dry-run`` first. Writes only when ``--apply`` is passed,
and is idempotent by ``external_id`` (or a synthetic ``legacy:<id>`` key).

    python scripts/migrate_hub_to_unified.py --source ..\\acquisition-crm-hub\\backend\\data\\acquisition_crm.db --dry-run
    DATABASE_URL=postgresql://... python scripts/migrate_hub_to_unified.py --source ... --apply
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

STAGE_MAP = {
    "New Leads": "new",
    "New Lead": "new",
    "Not Contacted": "not_contacted",
    "Attempting Contact": "attempting_contact",
    "Contacted": "contacted",
    "Qualified": "qualified",
    "Follow Up": "follow_up",
    "Follow-up": "follow_up",
    "interested add to follow up": "follow_up",
    "callback later ( date in the comments )": "follow_up",
    "long term follow up": "nurture",
    "hands off": "nurture",
    "Offers Made": "offer_made",
    "Offer Made": "offer_made",
    "Negotiation": "negotiation",
    "Under Contract": "under_contract",
    "Closed": "closed",
    "Dead Lead": "dead",
    "Dead": "dead",
}
CONTACTED_STAGES = {"contacted", "qualified", "follow_up", "offer_made", "negotiation", "under_contract", "closed"}


def iso_utc(value):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def dt_utc(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def full_name(row):
    name = " ".join(part for part in (row["first_name"], row["last_name"]) if part).strip()
    if name:
        return name
    if row["address_line1"]:
        return f"Owner — {row['address_line1']}"
    if row["phone"]:
        return f"Owner — {row['phone']}"
    return "Unknown owner"


def source_row(row):
    return {key: row[key] for key in row.keys()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Path to the old acquisition_crm.db")
    parser.add_argument("--apply", action="store_true", help="Write to the destination database")
    parser.add_argument("--dry-run", action="store_true", help="Explicit no-write mode (the default)")
    parser.add_argument("--limit", type=int, default=0, help="Only the first N leads (testing)")
    args = parser.parse_args()

    source_path = Path(args.source).resolve()
    if not source_path.exists():
        raise SystemExit(f"Source database not found: {source_path}")

    from app import models  # noqa: F401
    from app.db import SessionLocal, engine
    from app.models import AuditLog, Followup, Lead, LeadTag, PipelineStage, StageHistory
    from app.seed import initialize_defaults
    from app.services.imports import create_local_lead

    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    db = SessionLocal()
    initialize_defaults(db)

    lead_rows = source.execute("SELECT * FROM leads ORDER BY id").fetchall()
    if args.limit:
        lead_rows = lead_rows[: args.limit]

    assignments = {}
    for row in source.execute(
        "SELECT lead_id, assigned_to FROM lead_assignments ORDER BY assigned_at, id"
    ):
        assignments[row["lead_id"]] = row["assigned_to"]

    tags = {}
    for row in source.execute("SELECT lead_id, tag FROM lead_tags"):
        tags.setdefault(row["lead_id"], []).append(row["tag"])

    followups = {}
    for row in source.execute("SELECT * FROM followups ORDER BY id"):
        followups.setdefault(row["lead_id"], []).append(row)

    created = skipped = failed = 0
    old_to_new = {}
    created_old_ids = set()
    errors = []

    for row in lead_rows:
        external = row["external_id"] or f"legacy:{row['id']}"
        existing = db.query(Lead).filter(Lead.external_id == external).one_or_none()
        if existing:
            old_to_new[row["id"]] = existing.id
            skipped += 1
            continue

        stage = STAGE_MAP.get((row["pipeline_stage"] or "").strip(), "unmapped")
        if not db.get(PipelineStage, stage):
            stage = "unmapped"
        data = {
            "external_id": external,
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "full_name": full_name(row),
            "primary_phone": row["phone"],
            "phones": [{"number": row["phone"]}] if row["phone"] else [],
            "email": row["email"],
            "street_address": row["address_line1"],
            "city": row["city"],
            "state": (row["state"] or "")[:2] or None,
            "zip_code": row["postal_code"],
            "lead_source": row["source_system"] or "REsimpli",
            "source_status": row["pipeline_stage"],
            "source_do_not_contact": bool(row["do_not_call"]),
            "score": row["score"],
            "notes": row["notes"],
            "original_created_at": iso_utc(row["created_at"]),
            "next_followup_at": iso_utc(row["next_followup_date"]),
            "assigned_manager": assignments.get(row["id"]),
            "dedupe_key": external,
        }
        try:
            lead = create_local_lead(
                db,
                data,
                {"legacy": source_row(row), "source_db": str(source_path)},
                source_kind="legacy_import",
            )
            lead.stage_code = stage
            lead.local_stage_override = True
            if stage in CONTACTED_STAGES:
                lead.contact_status = "contacted"
            elif stage == "attempting_contact":
                lead.contact_status = "attempted"
            db.add(StageHistory(lead_id=lead.id, to_stage=stage, source="legacy_import"))
            if args.apply:
                db.commit()
            old_to_new[row["id"]] = lead.id
            created_old_ids.add(row["id"])
            created += 1
            if created % 50 == 0:
                print(f"  {created} leads...", flush=True)
        except Exception as exc:
            if args.apply:
                db.rollback()
            failed += 1
            errors.append({"legacy_id": row["id"], "error": f"{type(exc).__name__}: {exc}"[:300]})
            continue

    # Follow-ups and tags only for leads this run created; a rerun must not duplicate them.
    if not args.apply:
        db.rollback()
        print(f"DRY RUN: would create {created}, skip {skipped}, fail {failed}")
        for error in errors[:10]:
            print(error)
        return

    for old_id, rows in followups.items():
        if old_id not in created_old_ids:
            continue
        new_id = old_to_new.get(old_id)
        for row in rows:
            status = "completed" if (row["status"] or "").lower() == "completed" else "pending"
            db.add(
                Followup(
                    lead_id=new_id,
                    due_at=dt_utc(row["due_date"]),
                    priority=50,
                    reason=row["notes"] or f"Legacy {row['type'] or 'Follow-up'}",
                    suggested_action=row["type"],
                    status=status,
                    completed_at=dt_utc(row["completed_at"]),
                    creation_source="legacy_import",
                )
            )

    for old_id, names in tags.items():
        new_id = old_to_new.get(old_id)
        if not new_id:
            continue
        for tag in names:
            if not db.query(LeadTag).filter(LeadTag.lead_id == new_id, LeadTag.tag == tag).one_or_none():
                db.add(LeadTag(lead_id=new_id, tag=tag[:60]))

    db.add(
        AuditLog(
            action="legacy_hub_migrated",
            details={"source_db": str(source_path), "created": created, "skipped": skipped, "failed": failed},
        )
    )
    db.commit()
    print(f"Created {created}, skipped {skipped}, failed {failed}")
    for error in errors[:20]:
        print(error)
    print(f"Destination: {engine.url.render_as_string(hide_password=True)}")
    db.close()
    source.close()


if __name__ == "__main__":
    main()
