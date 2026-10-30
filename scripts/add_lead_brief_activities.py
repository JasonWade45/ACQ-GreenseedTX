"""Write the per-lead brief into REsimpli's activity history for existing leads.

REsimpli's Open API added ``POST /activity/add`` (module 1 = lead). This script uses it
to attach the same brief that new leads receive as a creation comment. It is idempotent:
a note row is marked ``delivered`` with ``delivered_via = "activity"`` and skipped next
time. Requests run in a small pool; the database is only touched on the main thread.
"""

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import models  # noqa: F401, E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import CrmNoteOutbox, CrmPush, Lead  # noqa: E402

URL = "https://api.resimpli.com/api/v6/openapi/activity/add"
_thread = threading.local()


def _client():
    if not hasattr(_thread, "client"):
        _thread.client = httpx.Client(timeout=45)
    return _thread.client


def _post(key, crm_id, body):
    headers = {"Authorization": key}
    for attempt in (1, 2):
        response = _client().post(URL, headers=headers, json={"moduleId": 1, "subModuleId": crm_id, "comment": body})
        if response.status_code == 200:
            return 200, ""
        if response.status_code == 429 and attempt == 1:
            time.sleep(2)
            continue
        return response.status_code, response.text[:180]
    return 429, "rate limited"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    settings = get_settings()
    if not settings.resimpli_api_key:
        raise SystemExit("RESIMPLI_API_KEY is missing")

    db = SessionLocal()
    leads = db.query(Lead).order_by(Lead.id).all()
    if args.limit:
        leads = leads[: args.limit]
    jobs = []
    no_crm = skipped = 0
    crm_ids = {lead_id: crm_id for lead_id, crm_id in db.query(CrmPush.lead_id, CrmPush.resimpli_lead_id).all()}
    latest_note = {}
    for note in db.query(CrmNoteOutbox).order_by(CrmNoteOutbox.created_at.asc()).all():
        latest_note[note.lead_id] = note
    for lead in leads:
        crm_id = crm_ids.get(lead.id) or lead.external_id
        if not crm_id or len(str(crm_id)) != 24:
            no_crm += 1
            continue
        note = latest_note.get(lead.id)
        if note is None or note.state == "delivered":
            skipped += 1
            continue
        jobs.append((lead.id, str(crm_id), note.id, note.body))
    print(f"Leads {len(leads)}; jobs {len(jobs)}; skipped {skipped}; no CRM id {no_crm}", flush=True)

    added = failed = 0
    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(_post, settings.resimpli_api_key, j[1], j[3]): j for j in jobs}
        for future in as_completed(futures):
            lead_id, crm_id, note_id, _body = futures[future]
            completed += 1
            try:
                status, text = future.result()
            except Exception as exc:
                status, text = 0, f"{type(exc).__name__}: {exc}"
            if status == 200:
                note = db.get(CrmNoteOutbox, note_id)
                if note is not None:
                    note.state = "delivered"
                    note.delivered_via = "activity"
                    note.delivered_at = datetime.now(timezone.utc)
                    note.blocked_reason = None
                added += 1
                if added % 25 == 0:
                    db.commit()
                    print(f"  {added} added ({completed}/{len(jobs)})...", flush=True)
            else:
                failed += 1
                print(f"  lead {lead_id} failed HTTP {status}: {text}", flush=True)
            if completed % 200 == 0:
                db.commit()
    db.commit()
    print(f"Added {added}, failed {failed}, skipped {skipped}, no CRM id {no_crm}, total {len(leads)}")
    db.close()


if __name__ == "__main__":
    main()
