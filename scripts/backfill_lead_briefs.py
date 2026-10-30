"""Give every existing lead the same brief that future CRM pushes will carry.

The brief is local because REsimpli v6 has no note endpoint. It appears on the lead
profile and is copied into the CRM ``comment`` only when a *new* lead is created.
Safe to re-run: the (lead_id, note_hash) pair is unique.
"""

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import models  # noqa: F401
from app.db import SessionLocal
from app.models import CrmNoteOutbox, Lead
from app.services.crm_notes import structured_note
from app.services.crm_push import PushSettings

REASON = "REsimpli's v6 Open API has no note endpoint; the brief is available in the app"


def main():
    db = SessionLocal()
    db.autoflush = False
    settings = PushSettings()
    created = skipped = 0
    existing_pairs = set(db.query(CrmNoteOutbox.lead_id, CrmNoteOutbox.note_hash).all())
    leads = db.query(Lead).order_by(Lead.id).all()
    for index, lead in enumerate(leads, start=1):
        text = structured_note(lead, settings)
        digest = hashlib.sha256(text.encode()).hexdigest()
        if (lead.id, digest) in existing_pairs:
            skipped += 1
            continue
        db.add(
            CrmNoteOutbox(
                lead_id=lead.id,
                note_hash=digest,
                body=text,
                source="enrichment",
                state="blocked",
                blocked_reason=REASON,
            )
        )
        existing_pairs.add((lead.id, digest))
        created += 1
        if created % 25 == 0:
            db.commit()
            print(f"  {created} briefs...", flush=True)
    db.commit()
    print(f"Created {created}, skipped {skipped}, total leads {len(leads)}")
    db.close()


if __name__ == "__main__":
    main()
