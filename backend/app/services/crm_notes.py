"""One concise, structured note about a lead, and where it can go.

REsimpli's v6 Open API has no note endpoint. The note therefore has exactly two
destinations: ``comment`` when the lead is created, and the lead profile in Green Seed,
where it can be read and copied. Anything else would be an invented endpoint.

What the note contains is controlled per field in Settings, with the approved defaults:
property facts, Data Syndicate flags, lead type, tier and priority reasons are included;
owner contact data and internal notes are not. The text always carries the same prefix,
so a note written by this application is recognisable in a CRM that has no idea it was
ours, and the same facts always produce the same text -- which is what makes the hash
idempotent.
"""

import hashlib
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CrmNoteOutbox
from .crm_push import NOTE_PREFIX, PushSettings

MAX_NOTE = 2000
FLAG_LABELS = {
    "free_and_clear": "free and clear",
    "high_equity": "high equity",
    "low_equity": "low equity",
    "owner_occupied": "owner occupied",
    "absentee_in_state": "absentee owner (in state)",
    "absentee_out_of_state": "absentee owner (out of state)",
    "senior_owner": "senior owner",
    "corporate_owned": "corporate owned",
    "trust_owned": "trust owned",
    "cash_buyer": "cash buyer",
    "failed_listing": "failed listing",
    "expired_listing": "expired listing",
    "below_market_listing": "below market listing",
    "recently_sold": "recently sold",
    "for_sale_by_owner": "for sale by owner",
    "involuntary_lien": "involuntary lien",
    "hoa_fees": "HOA fees",
    "sleeper": "sleeper",
}


def flag_names(lead) -> list[str]:
    """Every recorded flag, in a readable form; unknown flags are kept, never dropped."""
    names = []
    for key, value in (lead.ds_flags or {}).items():
        if not value:
            continue
        names.append(FLAG_LABELS.get(key, str(key).replace("_", " ")))
    names.extend(str(item) for item in (lead.ds_extra_flags or []) if str(item).strip())
    seen, ordered = set(), []
    for name in names:
        if name.lower() not in seen:
            seen.add(name.lower())
            ordered.append(name)
    return ordered


def priority_reasons(lead) -> list[str]:
    """Why this lead sits where it does. Thresholds match the importer's tiering."""
    reasons = []
    score, heat = lead.score, (lead.heat or "").upper()
    if lead.priority_tier:
        reasons.append(f"{lead.priority_tier} tier")
    if score is not None:
        reasons.append(f"score {round(float(score), 1)}")
    if heat:
        reasons.append(f"heat {lead.heat}")
    if lead.equity_pct is not None and float(lead.equity_pct) < 20:
        reasons.append(f"equity {lead.equity_pct}% is below the 20% threshold")
    if "recently_sold" in (lead.ds_flags or {}) or "recently sold" in {n.lower() for n in flag_names(lead)}:
        reasons.append("recently sold, which caps the priority")
    if lead.lead_type:
        reasons.append(f"lead type {lead.lead_type}")
    return reasons


def skip_trace_line(lead) -> Optional[str]:
    if lead.needs_skip_trace:
        return "Address-only lead: no verified phone at import, skip trace still required"
    traced = [phone for phone in (lead.phones or []) if phone.source_column == "skip_trace"]
    if traced:
        return f"Phones confirmed by a reviewed skip-trace run ({len(traced)})"
    return None


def structured_note(lead, settings: PushSettings, *, ai_summary=None, skip_trace=None) -> str:
    """Build the note text from the lead. Pure: same lead and settings, same string."""
    lines = [f"{NOTE_PREFIX} Green Seed lead record"]
    if lead.lead_type and settings.note_field("lead_type"):
        lines.append(f"Lead type: {lead.lead_type}")
    if lead.equity_pct is not None and settings.note_field("equity"):
        equity = float(lead.equity_pct)
        lines.append(f"Estimated equity: {equity:g}%")
    flags = flag_names(lead)
    if flags and settings.note_field("flags"):
        lines.append(f"Flags: {', '.join(flags[:20])}")
    if settings.note_field("priority"):
        reasons = priority_reasons(lead)
        if reasons:
            lines.append(f"Priority: {'; '.join(reasons)}")
    trace = skip_trace or skip_trace_line(lead)
    if trace:
        lines.append(trace)
    if settings.note_field("owner_contact"):
        contact = [part for part in (lead.full_name, lead.primary_phone, lead.email) if part]
        if contact:
            lines.append(f"Owner contact: {' | '.join(str(part) for part in contact)}")
    if settings.note_field("internal"):
        internal = [part for part in (lead.assigned_manager, lead.lead_source, lead.source_status) if part]
        if internal:
            lines.append(f"Internal: {' | '.join(str(part) for part in internal)}")
    if ai_summary:
        lines.append(f"AI summary (draft, reviewed by a person): {ai_summary.strip()[:600]}")
    lines.append("Prepared by Green Seed from reviewed local data. No message was sent to the seller.")
    text = "\n".join(lines)
    if len(text) > MAX_NOTE:
        text = text[: MAX_NOTE - 3].rstrip() + "..."
    return text


def note_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def ensure_note(db: Session, lead, settings: PushSettings, *, ai_summary=None, source="import", skip_trace=None):
    """Store the note once. The same facts produce the same row, not a second one."""
    text = structured_note(lead, settings, ai_summary=ai_summary, skip_trace=skip_trace)
    digest = note_hash(text)
    row = db.scalar(select(CrmNoteOutbox).where(CrmNoteOutbox.lead_id == lead.id, CrmNoteOutbox.note_hash == digest))
    if row is not None:
        return row
    row = CrmNoteOutbox(lead_id=lead.id, note_hash=digest, body=text, source=source, state="pending")
    db.add(row)
    db.flush()
    return row


def notes_for_lead(db: Session, lead_id) -> list[dict]:
    """The Notes card on the lead profile: what was written, and what happened to it."""
    rows = db.scalars(
        select(CrmNoteOutbox).where(CrmNoteOutbox.lead_id == lead_id).order_by(CrmNoteOutbox.created_at.desc())
    ).all()
    return [
        {
            "id": row.id,
            "body": row.body,
            "state": row.state,
            "reason": row.blocked_reason,
            "delivered_via": row.delivered_via,
            "created_at": row.created_at,
            "delivered_at": row.delivered_at,
            "note_hash": row.note_hash,
        }
        for row in rows
    ]


def note_for_new_lead(db: Session, lead, settings: PushSettings, *, ai_summary=None) -> str:
    """The note that travels in ``comment`` when this lead is created."""
    text = structured_note(lead, settings, ai_summary=ai_summary)
    ensure_note(db, lead, settings, ai_summary=ai_summary)
    db.flush()
    return text


def note_for_existing_lead(db: Session, lead, settings: PushSettings, *, ai_summary=None) -> dict:
    """A note about a lead the CRM already holds: kept locally, marked with the reason.

    The row is *not* presented as delivered. REsimpli documents no way to add it, so the
    profile shows the text with a copy button and the reason it is still local.
    """
    row = ensure_note(db, lead, settings, ai_summary=ai_summary, source="enrichment")
    if row.state != "delivered":
        row.state = "blocked"
        row.blocked_reason = "REsimpli's v6 Open API has no note endpoint; copy this note from the lead profile"
    db.commit()
    return {
        "id": row.id,
        "body": row.body,
        "state": row.state,
        "reason": row.blocked_reason,
        "note_hash": row.note_hash,
    }
