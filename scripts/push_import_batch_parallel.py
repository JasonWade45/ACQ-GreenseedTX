"""Parallel operator push for a large import batch (dedupe + create + link)."""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def push_one(lead_id: int, settings):
    db = SessionLocal()
    reader = writer = None
    try:
        lead = db.get(Lead, lead_id)
        if lead is None:
            return lead_id, "missing", ""
        mapping = db.query(CrmPush).filter(CrmPush.lead_id == lead_id).one_or_none()
        if mapping is not None and mapping.state == "pushed":
            return lead_id, "already", ""
        reader = ResimpliClient(settings)
        writer = ResimpliWriter(settings)
        note = crm_notes.note_for_new_lead(db, lead, crm_push.load_push_settings(db))
        outcome = crm_push.execute_push(
            db,
            lead,
            reader=reader,
            writer=writer,
            confirmation=crm_push.CONFIRMATION,
            note=note,
            settings=settings,
        )
        if outcome.state == "pushed":
            return lead_id, "pushed", ""
        if outcome.reason == "exists_in_crm" and outcome.plan.matches:
            crm_push.link_existing(db, lead, outcome.plan.matches[0]["resimpli_lead_id"], actor="operator")
            return lead_id, "linked", ""
        return lead_id, outcome.state or "blocked", str(outcome.reason or "")[:120]
    except Exception as exc:
        db.rollback()
        return lead_id, "error", f"{type(exc).__name__}: {exc}"[:160]
    finally:
        if reader is not None:
            reader.close()
        if writer is not None:
            writer.close()
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    settings = get_settings()
    if not settings.crm_writes_enabled or not settings.resimpli_api_key:
        raise SystemExit("CRM writes and REsimpli API key are required")
    with SessionLocal() as db:
        leads = db.query(Lead).filter(Lead.import_batch_id == str(args.batch_id)).order_by(Lead.id).all()
        done = {row[0] for row in db.query(CrmPush.lead_id).filter(CrmPush.state == "pushed").all()}
        ids = [lead.id for lead in leads if lead.id not in done]
    print(f"Batch {args.batch_id}: {len(ids)} remaining of {len(leads)}", flush=True)
    counts = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(push_one, lid, settings) for lid in ids]
        for index, future in enumerate(as_completed(futures), start=1):
            lead_id, state, reason = future.result()
            counts[state] = counts.get(state, 0) + 1
            if state not in {"pushed", "already", "linked"} or index % 10 == 0:
                print(f"[{index}/{len(ids)}] {lead_id} {state} {reason}", flush=True)
    print("SUMMARY", counts, flush=True)


if __name__ == "__main__":
    main()
