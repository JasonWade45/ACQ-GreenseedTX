"""Backfill real contact phones/emails from REsimpli when the lead has a shared or empty phone."""

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import models  # noqa: F401, E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Lead  # noqa: E402

URL = "https://api.resimpli.com/api/v6/openapi/lead/details"
_thread = threading.local()


def client():
    if not hasattr(_thread, "client"):
        _thread.client = httpx.Client(timeout=45)
    return _thread.client


def fetch(key, crm_id):
    for attempt in (1, 2):
        response = client().post(URL, headers={"Authorization": key}, json={"leadId": crm_id})
        if response.status_code == 200:
            data = response.json().get("data") or {}
            lead = data.get("leadData") or {}
            contacts = lead.get("contactData") or []
            primary_ids = [c.get("contactId") for c in (lead.get("contactInfo") or []) if c.get("contactId")]
            contact = next((c for c in contacts if c.get("_id") == primary_ids[0]), None) if primary_ids else None
            contact = contact or (contacts[0] if contacts else None)
            if not contact:
                return None
            phones = contact.get("phoneNumbers") or []
            primary = next((p for p in phones if p.get("isPrimary")), phones[0] if phones else None)
            emails = contact.get("emails") or []
            email = emails[0].get("email") if emails and isinstance(emails[0], dict) else None
            return {
                "first_name": (contact.get("firstName") or "").strip() or None,
                "last_name": (contact.get("lastName") or "").strip() or None,
                "full_name": (contact.get("fullName") or "").strip() or None,
                "phone": (primary.get("phoneNumber") or "").strip() if primary else None,
                "email": email,
            }
        if response.status_code == 429 and attempt == 1:
            time.sleep(2)
            continue
        return None
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    db = SessionLocal()
    settings = get_settings()
    counts = dict(
        db.execute(
            select(Lead.primary_phone, func.count())
            .where(Lead.primary_phone.is_not(None), Lead.primary_phone != "")
            .group_by(Lead.primary_phone)
        ).all()
    )
    bad = {phone for phone, count in counts.items() if count > 20}
    print("shared placeholder phones:", bad, flush=True)
    leads = [
        lead
        for lead in db.query(Lead).order_by(Lead.id).all()
        if lead.external_id
        and len(str(lead.external_id)) == 24
        and (
            not lead.primary_phone
            or lead.primary_phone in bad
            or not lead.first_name
            or (lead.full_name or "").lower().startswith("owner")
        )
    ]
    print("leads to inspect:", len(leads), flush=True)
    updated = cleared = failed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(fetch, settings.resimpli_api_key, str(lead.external_id)): lead.id for lead in leads}
        for future in as_completed(futures):
            lead_id = futures[future]
            try:
                data = future.result()
            except Exception:
                data = None
            if not data:
                failed += 1
                continue
            lead = db.get(Lead, lead_id)
            changed = False
            if data["first_name"] and not lead.first_name:
                lead.first_name = data["first_name"]
                changed = True
            if data["last_name"] and not lead.last_name:
                lead.last_name = data["last_name"]
                changed = True
            if data["full_name"] and (not lead.full_name or lead.full_name.lower().startswith("owner")):
                lead.full_name = data["full_name"]
                changed = True
            if data["email"] and not lead.email:
                lead.email = data["email"]
                changed = True
            if data["phone"] and (not lead.primary_phone or lead.primary_phone in bad):
                lead.primary_phone = data["phone"]
                changed = True
            elif not data["phone"] and lead.primary_phone in bad:
                lead.primary_phone = None
                lead.needs_skip_trace = True
                cleared += 1
                changed = True
            if lead.primary_phone and lead.full_name and lead.needs_skip_trace:
                lead.needs_skip_trace = False
                changed = True
            if changed:
                updated += 1
                if updated % 25 == 0:
                    db.commit()
                    print(f"  {updated} contacts...", flush=True)
    db.commit()
    print(f"updated {updated}, cleared placeholders {cleared}, no contact {failed}, inspected {len(leads)}", flush=True)
    db.close()


if __name__ == "__main__":
    main()
