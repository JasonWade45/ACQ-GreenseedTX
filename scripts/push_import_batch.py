"""Push one import batch into REsimpli, with duplicate checks and explicit linking.

This is an operator tool, not an automatic job. For every lead it runs the same plan as
the Push Queue: search the CRM by phone and address, create only when no match exists,
and link the existing CRM lead when a match is found. Nothing is sent to a seller.

    DATABASE_URL=... RESIMPLI_MODE=live RESIMPLI_API_KEY=... \
    RESIMPLI_ADAPTER_PATH=... RESIMPLI_ADAPTER_VERIFIED=true CRM_WRITES_ENABLED=true \
    python scripts/push_import_batch.py --batch-id 2 --apply

Use --dry-run first; it performs the read-only searches and writes nothing at all.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import models  # noqa: F401, E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import CrmPush, Lead  # noqa: E402
from app.services import crm_notes, crm_push  # noqa: E402
from app.services.resimpli import ResimpliClient  # noqa: E402
from app.services.resimpli_write import ResimpliWriter  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--link-existing", action="store_true", default=True)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.crm_writes_enabled:
        raise SystemExit("CRM_WRITES_ENABLED is false; refusing to write. Use --dry-run to preview.")
    if not settings.resimpli_api_key:
        raise SystemExit("RESIMPLI_API_KEY is missing")

    db = SessionLocal()
    leads = list(
        db.query(Lead)
        .filter(Lead.import_batch_id == str(args.batch_id))
        .order_by(Lead.id)
        .all()
    )
    if args.limit:
        leads = leads[: args.limit]
    print(f"Batch {args.batch_id}: {len(leads)} lead(s); apply={args.apply}", flush=True)

    reader = ResimpliClient(settings)
    writer = ResimpliWriter(settings) if args.apply else None
    counts = Counter()
    results = []
    try:
        for index, lead in enumerate(leads, start=1):
            try:
                mapping = db.query(CrmPush).filter(CrmPush.lead_id == lead.id).one_or_none()
                if mapping is not None and mapping.state == "pushed":
                    counts["already"] += 1
                    continue
                outcome = crm_push.execute_push(
                    db,
                    lead,
                    reader=reader,
                    writer=writer,
                    confirmation=crm_push.CONFIRMATION,
                    note=crm_notes.note_for_new_lead(db, lead, crm_push.load_push_settings(db)),
                    settings=settings,
                )
                state = outcome.state
                reason = outcome.reason
                if state == "pushed":
                    counts["created"] += 1
                elif reason == "exists_in_crm" and outcome.plan.matches:
                    counts["existing"] += 1
                    if args.apply and args.link_existing:
                        match = outcome.plan.matches[0]
                        crm_push.link_existing(db, lead, match["resimpli_lead_id"], actor="operator")
                        state = "linked"
                        counts["linked"] += 1
                elif reason == "already_pushed":
                    counts["already"] += 1
                elif state == "blocked":
                    counts["blocked"] += 1
                elif state == "failed":
                    counts["failed"] += 1
                else:
                    counts[state or "unknown"] += 1
                results.append((lead.id, state, reason))
                print(f"[{index}/{len(leads)}] lead {lead.id}: {state} {reason or ''}", flush=True)
            except Exception as exc:
                db.rollback()
                counts["error"] += 1
                results.append((lead.id, "error", f"{type(exc).__name__}: {exc}"[:200]))
                print(f"[{index}/{len(leads)}] lead {lead.id}: ERROR {type(exc).__name__}: {exc}"[:240], flush=True)
    finally:
        reader.close()
        if writer is not None:
            writer.close()
        db.close()

    print("SUMMARY", dict(counts), flush=True)
    failures = [row for row in results if row[1] in {"failed", "error"}]
    for row in failures[:20]:
        print("  failure", row)
    return 1 if counts["error"] or counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
