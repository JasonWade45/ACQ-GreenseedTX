"""Call outcomes that already happened, and the next step they imply.

A call is recorded *after* the fact. The only thing this module creates on its own is a
local follow-up task and a stage/contact note; it never dials, texts, emails or posts to
the CRM. Every rule here is deterministic so the same outcome always means the same next
step, and the caller can see why the due date was chosen.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import (
    Activity,
    AuditLog,
    CallLog,
    Followup,
    Lead,
    StageHistory,
    Suppression,
)

# outcome -> what it means, where the lead moves, and when to look again.
OUTCOMES = {
    "connected": {
        "label": "Connected",
        "contact_status": "contacted",
        "followup_days": 2,
        "followup_type": "Call",
        "reason": "Connected call — confirm next step in two days",
        "stage": None,
    },
    "interested": {
        "label": "Interested",
        "contact_status": "contacted",
        "followup_days": 1,
        "followup_type": "Call",
        "reason": "Interested seller — follow up tomorrow while intent is warm",
        "stage": "qualified",
    },
    "wants_offer": {
        "label": "Wants an Offer",
        "contact_status": "contacted",
        "followup_days": 1,
        "followup_type": "Offer",
        "reason": "Seller asked for an offer — prepare numbers and respond tomorrow",
        "stage": "qualified",
    },
    "no_answer": {
        "label": "No Answer",
        "contact_status": "attempted",
        "followup_days": 1,
        "followup_type": "Call",
        "reason": "No answer — try a different time tomorrow",
        "stage": None,
    },
    "voicemail": {
        "label": "Left Voicemail",
        "contact_status": "attempted",
        "followup_days": 2,
        "followup_type": "Call",
        "reason": "Voicemail left — give the seller two days before retrying",
        "stage": None,
    },
    "callback": {
        "label": "Call Back Later",
        "contact_status": "attempted",
        "followup_days": 1,
        "followup_type": "Call",
        "reason": "Seller asked for a callback — keep the promised window",
        "stage": None,
    },
    "not_interested": {
        "label": "Not Interested",
        "contact_status": "contacted",
        "followup_days": None,
        "followup_type": None,
        "reason": "Seller declined — no automatic follow-up; move to Dead unless a review says otherwise",
        "stage": "dead",
    },
    "dnc": {
        "label": "Asked to Stop Contact",
        "contact_status": "contacted",
        "followup_days": None,
        "followup_type": None,
        "reason": "Seller opted out — suppressed locally, no follow-up",
        "stage": "dead",
        "do_not_contact": True,
    },
    "wrong_number": {
        "label": "Wrong Number",
        "contact_status": "attempted",
        "followup_days": None,
        "followup_type": None,
        "reason": "Wrong number — needs a new contact route before any follow-up",
        "stage": None,
    },
}

OUTCOME_CODES = tuple(OUTCOMES)


def _as_utc(value: Optional[datetime]) -> datetime:
    if value is None:
        return utcnow()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _set_stage(db: Session, lead: Lead, code: Optional[str], source: str) -> bool:
    """Move a lead only when the target stage exists and it is not already there."""
    if not code or lead.stage_code == code:
        return False
    from ..models import PipelineStage

    if db.get(PipelineStage, code) is None:
        return False
    db.add(
        StageHistory(
            lead_id=lead.id,
            from_stage=lead.stage_code,
            to_stage=code,
            changed_at=utcnow(),
            source=source,
        )
    )
    lead.stage_code = code
    lead.local_stage_override = True
    return True


def _add_suppression(db: Session, lead: Lead, reason: str, source: str) -> None:
    phone = (lead.primary_phone or "").strip()
    if not phone:
        return
    existing = db.scalar(select(Suppression).where(Suppression.phone == phone))
    if existing:
        return
    db.add(
        Suppression(
            phone=phone,
            phone_normalized=phone,
            reason=reason,
            source=source,
            lead_id=lead.id,
        )
    )


def _has_pending_followup(db: Session, lead_id: int) -> bool:
    return (
        db.scalar(
            select(Followup).where(
                Followup.lead_id == lead_id,
                Followup.status == "pending",
            )
        )
        is not None
    )


def suggest_followup(outcome: str, occurred_at: Optional[datetime] = None) -> dict:
    """What the outcome implies, without writing anything."""
    config = OUTCOMES.get(outcome)
    if config is None:
        raise ValueError(f"Unknown call outcome: {outcome}")
    days = config["followup_days"]
    if days is None:
        return {
            "should_schedule": False,
            "reason": config["reason"],
            "label": config["label"],
            "followup_type": None,
            "due_at": None,
        }
    base = _as_utc(occurred_at)
    due_at = base + timedelta(days=days)
    return {
        "should_schedule": True,
        "reason": config["reason"],
        "label": config["label"],
        "followup_type": config["followup_type"],
        "due_at": due_at,
    }


def record_call(
    db: Session,
    lead: Lead,
    *,
    outcome: str,
    direction: str = "outbound",
    duration_seconds: Optional[int] = None,
    notes: Optional[str] = None,
    next_step: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
) -> dict:
    """Store one call, update the lead, and return the call plus the implied next step."""
    config = OUTCOMES.get(outcome)
    if config is None:
        raise ValueError(f"Unknown call outcome: {outcome}")
    if direction not in ("outbound", "inbound"):
        raise ValueError("direction must be outbound or inbound")
    if duration_seconds is not None and duration_seconds < 0:
        raise ValueError("duration_seconds cannot be negative")

    when = _as_utc(occurred_at)
    call = CallLog(
        lead_id=lead.id,
        outcome=outcome,
        direction=direction,
        duration_seconds=duration_seconds,
        notes=notes,
        next_step=next_step,
        occurred_at=when,
    )
    db.add(call)
    db.flush()

    lead.contact_status = config["contact_status"]
    lead.contact_outcome = config["label"]
    lead.last_contact_at = when

    if config.get("do_not_contact"):
        lead.local_do_not_contact = True
        _add_suppression(db, lead, "asked_to_stop", "call_log")

    _set_stage(db, lead, config.get("stage"), "call_log")

    suggestion = suggest_followup(outcome, when)
    followup = None
    if suggestion["should_schedule"] and not _has_pending_followup(db, lead.id):
        followup = Followup(
            lead_id=lead.id,
            due_at=suggestion["due_at"],
            priority=50,
            reason=suggestion["reason"],
            suggested_action=next_step or config["label"],
            status="pending",
            creation_source="call_log",
            ai_suggested=False,
        )
        db.add(followup)
        db.flush()
        call.followup_id = followup.id
        lead.next_followup_at = suggestion["due_at"]

    db.add(
        Activity(
            lead_id=lead.id,
            activity_type="call",
            direction=direction,
            outcome=config["label"],
            occurred_at=when,
            source="local",
            summary=(notes or config["reason"])[:20000],
        )
    )
    db.add(
        AuditLog(
            lead_id=lead.id,
            action="call_logged",
            details={
                "outcome": outcome,
                "label": config["label"],
                "duration_seconds": duration_seconds,
                "followup_id": followup.id if followup else None,
            },
        )
    )
    db.commit()
    db.refresh(call)

    return {
        "call": call_dict(call),
        "suggestion": {
            "should_schedule": suggestion["should_schedule"],
            "reason": suggestion["reason"],
            "followup_type": suggestion["followup_type"],
            "due_at": suggestion["due_at"],
            "followup_id": followup.id if followup else None,
        },
        "lead": {
            "contact_status": lead.contact_status,
            "contact_outcome": lead.contact_outcome,
            "stage_code": lead.stage_code,
            "last_contact_at": lead.last_contact_at,
            "next_followup_at": lead.next_followup_at,
            "do_not_contact": lead.do_not_contact,
        },
    }


def call_dict(call: CallLog) -> dict:
    return {
        "id": call.id,
        "lead_id": call.lead_id,
        "outcome": call.outcome,
        "label": OUTCOMES.get(call.outcome, {}).get("label", call.outcome),
        "direction": call.direction,
        "duration_seconds": call.duration_seconds,
        "notes": call.notes,
        "next_step": call.next_step,
        "occurred_at": call.occurred_at,
        "followup_id": call.followup_id,
    }


def _address(lead: Lead) -> str:
    prop = lead.properties[0] if lead.properties else None
    if prop is None:
        return "the property"
    parts = [prop.street_address, prop.city, prop.state]
    return ", ".join(part for part in parts if part) or "the property"


def build_live_script(lead: Lead) -> dict:
    """A deterministic in-call script. No model call, no invented numbers."""
    name = lead.first_name or lead.full_name or "the owner"
    address = _address(lead)
    price = getattr(lead.properties[0], "asking_price", None) if lead.properties else None
    price_line = (
        f"The recorded asking price is {price:,.0f} dollars."
        if price
        else "No asking price is recorded, so ask for their number before discussing ours."
    )
    return {
        "objective": f"Confirm motivation, condition and timeline for {address}, and book the next concrete step.",
        "steps": [
            {
                "step_number": 1,
                "title": "Opening",
                "content": (
                    f"Hi {name}, this is Jason with GreenSeedTX. I'm calling about {address}. "
                    "Is now still a good time for two minutes?"
                ),
                "tips": "If it is not a good time, ask for a specific callback window instead of pushing.",
            },
            {
                "step_number": 2,
                "title": "Confirm the situation",
                "content": (
                    "I buy houses as-is for cash. Before I ask anything else — is the property still "
                    "something you would consider selling this year?"
                ),
                "tips": "A clear no ends the call politely; a maybe is the real start of the conversation.",
            },
            {
                "step_number": 3,
                "title": "Discovery",
                "content": (
                    "What would need to happen for you to be open to selling? "
                    "How soon are you hoping to close? "
                    "What condition is the property in today? "
                    "Is there a mortgage or lien on it?"
                ),
                "tips": "Write the seller's own words down; do not translate them into a score yet.",
            },
            {
                "step_number": 4,
                "title": "Numbers",
                "content": (
                    f"{price_line} I will not throw out a number I cannot support — I would rather "
                    "look at the condition and recent sales and come back with a real range."
                ),
                "tips": "Never invent ARV or repair numbers on the call.",
            },
            {
                "step_number": 5,
                "title": "Close for the next step",
                "content": (
                    "Based on what you told me, the next step is for me to review the numbers and "
                    "come back to you. Would tomorrow afternoon or the morning after work better?"
                ),
                "tips": "A booked time is the win; a 'sounds good' is not.",
            },
        ],
        "key_objections": [
            {
                "objection": "I want full retail price.",
                "response": "I understand. A cash offer has to account for repairs and closing costs, so it will not match retail. If retail is the goal, an agent may serve you better and I will say so.",
            },
            {
                "objection": "I need to think about it.",
                "response": "Of course. What is the one thing you need to know before you can decide? I can get you that answer instead of calling you again with nothing new.",
            },
            {
                "objection": "I already have an agent.",
                "response": "That is fine. I am not asking you to break that relationship. If the listing expires or the timeline changes, you can keep my number.",
            },
            {
                "objection": "How did you get my information?",
                "response": "Your property came up in public records and marketing data. If you would rather I not call again, tell me now and I will record it.",
            },
        ],
        "next_step": "Record the outcome immediately, then keep the follow-up the app suggests or replace it with the seller's chosen time.",
    }
