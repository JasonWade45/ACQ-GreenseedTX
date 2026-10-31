"""Rebuild the follow-up queue as one global cadence.

Cancels the legacy pending rows (which were imported one per source date and left many
leads without any task), then creates exactly one pending first-touch task per active
lead, staggered at a manageable daily volume. Completed history is never touched.
"""

import argparse
import sys
from datetime import timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import models  # noqa: F401, E402
from app.db import SessionLocal, utcnow  # noqa: E402
from app.models import AuditLog, Followup, Lead  # noqa: E402

DAILY_CAP = 50
ACTIVE_STAGES = {"new", "not_contacted", "attempting_contact", "contacted", "qualified", "follow_up", "appointment_set", "offer_made", "negotiation", "nurture", "unmapped"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    active = (
        db.query(Lead)
        .filter(
            Lead.stage_code.in_(ACTIVE_STAGES),
            (Lead.source_do_not_contact.is_(None)) | (Lead.source_do_not_contact.is_(False)),
            Lead.local_do_not_contact.is_(False),
        )
        .order_by(Lead.score.desc().nullslast(), Lead.id)
        .all()
    )
    print(f"Active leads: {len(active)}")
    pending = db.query(Followup).filter(Followup.status == "pending").all()
    print(f"Pending rows to cancel: {len(pending)}")
    if not args.apply:
        print(f"DRY RUN: would create {len(active)} first-touch task(s), {DAILY_CAP}/day")
        return

    for f in pending:
        f.status = "cancelled"
    db.commit()

    now = utcnow()
    created = 0
    for index, lead in enumerate(active):
        day = index // DAILY_CAP
        due = now + timedelta(days=day)
        priority = 90 if (lead.heat or "").upper() == "VERY_HOT" else 75 if (lead.heat or "").upper() == "HOT" else 50
        db.add(
            Followup(
                lead_id=lead.id,
                due_at=due,
                priority=priority,
                reason=f"GreenSeedTX global cadence — first touch (day {day + 1})",
                suggested_action="Call" if lead.primary_phone else "Skip trace",
                status="pending",
                creation_source="followup_strategy",
            )
        )
        lead.next_followup_at = due
        created += 1
        if created % 50 == 0:
            db.commit()
            print(f"  {created} tasks...", flush=True)
    db.add(
        AuditLog(
            action="followup_queue_rebuilt",
            details={"created": created, "cancelled": len(pending), "daily_cap": DAILY_CAP},
        )
    )
    db.commit()
    print(f"Created {created} first-touch tasks; cancelled {len(pending)} legacy pending rows")
    db.close()


if __name__ == "__main__":
    main()
