"""Fill missing owner names from the REsimpli contact attached to each lead.

The old workspace stored only address and phone, while the CRM already holds the seller's
name in ``leadData.contactData``. This script reads it (never writes to the CRM) and fills
only placeholder names, so follow-up messages can address the owner personally.
"""

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import models  # noqa: F401, E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Lead  # noqa: E402

URL = "https://api.resimpli.com/api/v6/openapi/lead/details"
_thread = threading.local()


def _client():
    if not hasattr(_thread, "client"):
        _thread.client = httpx.Client(timeout=45)
    return _thread.client


def _placeholder(value):
    text = (value or "").strip().lower()
    return not text or text.startswith("owner") or text.startswith("seller") or text in {"unknown", "n a", "null"}


def _fetch(key, crm_id):
    for attempt in (1, 2):
        r = _client().post(URL, headers={"Authorization": key}, json={"leadId": crm_id})
        if r.status_code == 200:
            data = r.json().get("data") or {}
            lead = data.get("leadData") or {}
            contacts = lead.get("contactData") or []
            primary_ids = [c.get("contactId") for c in (lead.get("contactInfo") or []) if c.get("contactId")]
            contact = None
            if primary_ids:
                contact = next((c for c in contacts if c.get("_id") == primary_ids[0]), None)
            contact = contact or (contacts[0] if contacts else None)
            if not contact:
                return None
            first = (contact.get("firstName") or "").strip()
            last = (contact.get("lastName") or "").strip()
            full = (contact.get("fullName") or f"{first} {last}".strip()).strip()
            email = None
            emails = contact.get("emails") or []
            if emails and isinstance(emails[0], dict):
                email = emails[0].get("email")
            if full or first:
                return {"first_name": first or None, "last_name": last or None, "full_name": full or None, "email": email}
            return None
        if r.status_code == 429 and attempt == 1:
            time.sleep(2)
            continue
        return None
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    settings = get_settings()
    if not settings.resimpli_api_key:
        raise SystemExit("RESIMPLI_API_KEY is missing")

    db = SessionLocal()
    leads = [
        lead
        for lead in db.query(Lead).order_by(Lead.id).all()
        if lead.external_id and len(str(lead.external_id)) == 24 and (_placeholder(lead.full_name) or not lead.first_name)
    ]
    if args.limit:
        leads = leads[: args.limit]
    print(f"Leads to name: {len(leads)}", flush=True)
    jobs = [(lead.id, str(lead.external_id)) for lead in leads]
    updated = failed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(_fetch, settings.resimpli_api_key, cid): (lid, cid) for lid, cid in jobs}
        for future in as_completed(futures):
            lead_id, cid = futures[future]
            try:
                names = future.result()
            except Exception:
                names = None
            if not names:
                failed += 1
                continue
            lead = db.get(Lead, lead_id)
            if lead is None:
                continue
            changed = False
            if names["first_name"] and not lead.first_name:
                lead.first_name = names["first_name"]
                changed = True
            if names["last_name"] and not lead.last_name:
                lead.last_name = names["last_name"]
                changed = True
            if names["full_name"] and _placeholder(lead.full_name):
                lead.full_name = names["full_name"]
                changed = True
            if names.get("email") and not lead.email:
                lead.email = names["email"]
                changed = True
            if changed:
                updated += 1
                if updated % 25 == 0:
                    db.commit()
                    print(f"  {updated} names...", flush=True)
    db.commit()
    print(f"Updated {updated}, no name {failed}, considered {len(leads)}", flush=True)
    db.close()


if __name__ == "__main__":
    main()
