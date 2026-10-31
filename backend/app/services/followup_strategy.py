"""The global follow-up strategy: cadence, message drafting and "sent" bookkeeping.

Messages are assembled locally from the lead's recorded facts and the last recorded
conversation. They are copy-only; the app never sends an SMS or an email. The company
name is always ``GreenSeedTX LLC``; the sender name appears only in the first message of
a sequence, as requested.
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Activity, AuditLog, Followup, Lead
from .lead_brief import playbook_for

COMPANY = "GreenSeedTX LLC"
SENDER = "Jason Wade, Acquisition Manager"
CADENCE_DAYS = [0, 1, 3, 7, 14, 30, 60, 90]
INTERVALS = [1, 3, 7, 14, 30, 60, 90]
MAX_CHARS = 320

STRATEGY = {
    "name": "GreenSeedTX 90-day seller cadence",
    "cadence_days": CADENCE_DAYS,
    "channels": ["Call", "SMS", "Email"],
    "rules": [
        "Day 0: call first; if no answer, send the first message the same day.",
        "Follow up on days 1, 3, 7, 14, 30, 60 and 90; stop after a clear outcome.",
        "Use the last recorded conversation in every message; never invent one.",
        "First message: Jason Wade, Acquisition Manager with GreenSeedTX LLC.",
        "Later messages: GreenSeedTX LLC only, without repeating the sender name.",
        "Stop immediately on a reply, opt-out, appointment, contract or dead lead.",
        "A message is copied and sent outside this app; the app records that it was sent.",
    ],
}

NON_CONVERSATION = (
    "Imported historical contact metadata",
    "Prepared by Green Seed",
    "Follow-up completed",
    "No message was sent",
)


def _clean(text: str | None, limit: int = 90) -> str:
    value = " ".join(str(text or "").split())
    if not value:
        return ""
    if any(value.startswith(prefix) for prefix in NON_CONVERSATION):
        return ""
    return value[:limit].rstrip(" ,.;") + ("…" if len(value) > limit else "")


def conversation_summary(activity: Activity | None, lead: Lead) -> str:
    if activity is None:
        return ""
    summary = _clean(activity.summary)
    if summary:
        return summary
    outcome = _clean(activity.outcome, 70)
    return outcome


def first_message(lead: Lead, db: Session) -> bool:
    sent = db.scalar(
        select(func.count())
        .select_from(Followup)
        .where(Followup.lead_id == lead.id, Followup.status == "completed")
    ) or 0
    messages = db.scalar(
        select(func.count())
        .select_from(Activity)
        .where(Activity.lead_id == lead.id, Activity.activity_type == "message")
    ) or 0
    return sent == 0 and messages == 0


def build_message(lead: Lead, activity: Activity | None = None, *, first: bool | None = None, db: Session | None = None) -> dict:
    name = (lead.first_name or "").strip()
    if not name:
        full = (lead.full_name or "").strip()
        name = full.split()[0] if full and not full.lower().startswith("owner") else "there"
    prop = lead.properties[0] if lead.properties else None
    address = ""
    if prop is not None:
        address = ", ".join(part for part in (prop.street_address, prop.city, prop.state) if part)
    if first is None and db is not None:
        first = first_message(lead, db)
    first = bool(first)
    conversation = conversation_summary(activity, lead)
    play = playbook_for(lead)
    angle = play["ask"][0] if play.get("ask") else "Is selling still something you would consider?"

    if first:
        opening = f"Hi {name}, this is {SENDER} with {COMPANY}."
    else:
        opening = f"Hi {name}, this is {COMPANY} following up on {address or 'the property'}."
    if conversation:
        body = f' You mentioned: "{conversation}". {angle}'
    else:
        body = f" I am checking in on {address or 'the property'}. {angle}"
    close = " Reply STOP to opt out."
    text = (opening + body + close).strip()
    if len(text) > MAX_CHARS:
        # Keep the company, the question and the opt-out; trim the middle.
        body_limit = max(40, MAX_CHARS - len(opening) - len(close) - 2)
        body = body[:body_limit].rstrip(" ,.;") + "…"
        text = (opening + body + close).strip()
    return {
        "text": text,
        "first_message": first,
        "basis": "last conversation" if conversation else f"{play['label']} playbook",
        "channel": "SMS",
        "conversation": conversation or None,
    }


def mark_sent(db: Session, followup: Followup, message: str, channel: str = "SMS") -> dict:
    if followup.status != "pending":
        raise ValueError("This follow-up is no longer pending")
    lead = db.get(Lead, followup.lead_id)
    if lead is None or lead.do_not_contact:
        raise ValueError("This lead is restricted; no message may be recorded")
    now = utcnow()
    followup.status = "completed"
    followup.completion_outcome = "Message Sent"
    followup.completed_at = now
    lead.contact_status = "attempted" if lead.contact_status in {"unknown", "not_contacted"} else lead.contact_status
    lead.last_contact_at = now
    db.add(
        Activity(
            lead_id=lead.id,
            activity_type="message",
            direction="outbound",
            outcome="Message Sent",
            occurred_at=now,
            summary=f"{channel}: {message[:1900]}",
            source="local",
            source_metadata={"followup_id": followup.id, "copy_only": True, "automated_send": False},
        )
    )
    completed = db.scalar(
        select(func.count())
        .select_from(Followup)
        .where(Followup.lead_id == lead.id, Followup.status == "completed")
    ) or 0
    next_due = None
    if lead.stage_code not in {"dead", "closed", "under_contract"}:
        interval = INTERVALS[min(max(completed - 1, 0), len(INTERVALS) - 1)]
        if completed >= len(CADENCE_DAYS):
            interval = 90
        next_due = now + timedelta(days=interval)
        db.add(
            Followup(
                lead_id=lead.id,
                due_at=next_due,
                priority=50,
                reason=f"GreenSeedTX cadence: touch {completed + 1}",
                suggested_action="Call" if lead.primary_phone else "Skip trace",
                status="pending",
                creation_source="followup_strategy",
            )
        )
        lead.next_followup_at = next_due
    db.add(
        AuditLog(
            lead_id=lead.id,
            action="followup_sent",
            details={"followup_id": followup.id, "channel": channel, "next_due": next_due.isoformat() if next_due else None},
        )
    )
    db.commit()
    return {
        "followup": followup,
        "next_due": next_due,
        "completed_count": completed,
    }
