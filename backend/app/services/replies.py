"""Reply classification and suggested actions (Phase 6).

Rules run first and are always used for the literal opt-out keywords. The result is a
*suggestion*: this module never changes a stage and never adds a suppression by itself.
The one thing it does immediately is pause the cadence, because continuing to prepare
messages for someone who just replied would be wrong.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import Activity, Lead, LeadSequenceState, Message, SuggestedAction, Task
from .templates import OPT_OUT_LINE, validate_message, sender_identity

STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}
LABELS = [
    "INTERESTED",
    "WANTS_PRICE",
    "NOT_NOW",
    "NOT_INTERESTED",
    "WRONG_NUMBER",
    "STOP",
    "QUESTION",
    "OTHER",
]
LOW_CONFIDENCE = 0.7
REVIEW_NOTE = "Low confidence: a person must read this reply before any action"


def _evidence(text: str, needle: str | None = None, limit: int = 160) -> str:
    """Quote the part of the message that drove the classification."""
    if not text:
        return ""
    if needle:
        index = text.lower().find(needle.lower())
        if index >= 0:
            start = max(0, index - 40)
            return text[start : start + limit].strip()
    return text[:limit].strip()


def classify_rule_based(text: str) -> tuple[str | None, float]:
    if not text or not text.strip():
        return None, 0.0
    low = text.strip().lower()
    tokens = low.replace(",", " ").replace(".", " ").split()
    if tokens and tokens[0] in STOP_WORDS:
        return "STOP", 1.0
    if any(k in low for k in STOP_WORDS):
        return "STOP", 0.95
    if "wrong number" in low:
        return "WRONG_NUMBER", 0.95
    if any(w in low for w in ("not interested", "no thanks", "remove me", "don't text", "do not text", "sell my number")):
        return "NOT_INTERESTED", 0.9
    if any(w in low for w in ("how much", "price", "offer", "worth", "cost", "pay")):
        return "WANTS_PRICE", 0.85
    if any(w in low for w in ("yes", "interested", "tell me more", "call me", "sure", "i'm open", "sounds good")):
        return "INTERESTED", 0.85
    if any(w in low for w in ("later", "not now", "maybe", "next month", "busy", "not yet", "after the holidays")):
        return "NOT_NOW", 0.8
    if "?" in low:
        return "QUESTION", 0.7
    return "OTHER", 0.45


def classify(db: Session | None, text: str, use_ai: bool = False) -> tuple[str, float]:
    """Rules first. AI is optional and never overrides a literal STOP."""
    cls, conf = classify_rule_based(text)
    if cls is None:
        return "OTHER", 0.4
    if cls == "STOP":
        return cls, conf
    if use_ai and db is not None:
        # A cloud/local rewrite may only confirm the rule result here; the reviewed
        # Groq flow stays the only place seller text leaves the device.
        return cls, conf
    return cls, conf


def suggestion_kind(classification: str) -> str:
    return {
        "STOP": "suppress",
        "WRONG_NUMBER": "suppress",
        "NOT_INTERESTED": "suppress",
        "INTERESTED": "reply",
        "WANTS_PRICE": "price_question",
        "NOT_NOW": "follow_up_later",
        "QUESTION": "review",
    }.get(classification, "review")


def handle_inbound(db: Session, lead: Lead, text: str, source: str = "local") -> dict:
    """Classify an inbound message and record suggestions that Jason must confirm."""
    classification, confidence = classify(db, text)
    evidence = _evidence(text, None)
    now = datetime.now(timezone.utc)

    # Pausing the cadence is immediate and needs no confirmation: nothing sends either way.
    paused = 0
    for state in (
        db.query(LeadSequenceState)
        .filter(LeadSequenceState.lead_id == lead.id, LeadSequenceState.status == "active")
        .all()
    ):
        state.status = "stopped"
        state.stop_reason = classification.lower()[:80]
        paused += 1

    message = Message(
        lead_id=lead.id,
        direction="inbound",
        body=text,
        status="RECEIVED",
        classification=classification,
        confidence=confidence,
    )
    db.add(message)
    db.flush()

    kind = suggestion_kind(classification)
    action = SuggestedAction(
        lead_id=lead.id,
        message_id=message.id,
        kind=kind,
        classification=classification,
        confidence=confidence,
        evidence=evidence,
        payload={
            "text": text,
            "needs_review": confidence < LOW_CONFIDENCE,
            "note": REVIEW_NOTE if confidence < LOW_CONFIDENCE else None,
        },
        requires_confirmation=True,
    )
    db.add(action)

    # A literal stop keyword blocks outreach immediately. Adding the number to the
    # suppression list still requires Jason's confirmation, so the list stays a record
    # of decisions rather than guesses.
    if classification == "STOP":
        lead.local_do_not_contact = True
    if classification in {"INTERESTED", "WANTS_PRICE"}:
        lead.contact_status = "contacted"
        lead.last_contact_at = now

    task = Task(
        lead_id=lead.id,
        title=f"Reply: {classification}",
        description=text[:2000],
        priority=1 if classification in {"INTERESTED", "WANTS_PRICE", "STOP"} else 3,
        due_at=now,
        source="reply",
    )
    db.add(task)
    db.commit()

    draft = None
    if classification in {"INTERESTED", "WANTS_PRICE"}:
        draft = _suggested_reply(db, lead, classification)

    return {
        "classification": classification,
        "confidence": confidence,
        "evidence": evidence,
        "needs_review": confidence < LOW_CONFIDENCE,
        "suggested_action_id": action.id,
        "suggested_kind": kind,
        "task_id": task.id,
        "message_id": message.id,
        "suggested_draft_id": draft.get("id") if draft else None,
        "suggested_draft": draft,
        "cadence_paused": paused,
        "contact_blocked": bool(classification == "STOP"),
        "never_sent": True,
    }


def _suggested_reply(db: Session, lead: Lead, classification: str) -> dict | None:
    """A validated draft reply. It never quotes a price: Jason types any number."""
    sender_name, company = sender_identity()
    first = (lead.first_name or (lead.full_name or "").split()[0] if lead.full_name else "") or "there"
    if classification == "WANTS_PRICE":
        body = (
            f"Hi {first}, thanks for getting back to me. I do not want to guess at a number without seeing the "
            f"property and hearing what matters to you. Would a short call this week work? "
            f"{sender_name} with {company}. {OPT_OUT_LINE}"
        )
    else:
        body = (
            f"Hi {first}, thanks for the reply. I'm glad to walk you through how a simple as-is sale works, with "
            f"no repairs and no agent fees. Would a quick call this week be useful? "
            f"{sender_name} with {company}. {OPT_OUT_LINE}"
        )
    ok, reasons = validate_message(body, bool(first and first != "there"), sender_name=sender_name, company=company)
    record = Message(
        lead_id=lead.id,
        direction="outbound",
        body=body,
        status="DRAFT",
        validator_result={"ok": ok, "reasons": reasons},
        reason_tags=[f"reply:{classification.lower()}"],
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {
        "id": record.id,
        "body": record.body,
        "validator_result": record.validator_result,
        "status": record.status,
    }


def confirm_action(db: Session, action: SuggestedAction, decision: str = "confirm") -> dict:
    """Apply one suggested action after an explicit human confirmation."""
    if action.status != "pending":
        raise ValueError("This suggestion has already been handled")
    lead = db.get(Lead, action.lead_id)
    if lead is None:
        raise ValueError("Lead no longer exists")
    if decision == "dismiss":
        action.status = "dismissed"
        action.resolved_at = datetime.now(timezone.utc)
        db.commit()
        return {"id": action.id, "status": action.status, "applied": None}
    applied = None
    if action.kind == "suppress":
        from .compliance import add_suppression

        phone = lead.primary_phone
        if not phone:
            raise ValueError("This lead has no phone number to suppress")
        add_suppression(
            db,
            phone,
            "stop" if action.classification == "STOP" else "manual",
            f"reply_{action.classification.lower()}",
            lead_id=lead.id,
            notes=action.evidence,
        )
        lead.local_do_not_contact = True
        applied = "suppressed"
    elif action.kind == "follow_up_later":
        due = db.query(Task).filter(Task.lead_id == lead.id, Task.status == "open").first()
        if due is None:
            due = Task(lead_id=lead.id, title="Revisit after the seller's timing", source="reply", priority=3)
            db.add(due)
        applied = "task_kept"
    elif action.kind == "price_question":
        applied = "price_entered_by_hand"
    else:
        applied = "reviewed"
    action.status = "confirmed"
    action.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": action.id, "status": action.status, "applied": applied}


def classify_inbound_activities(db: Session, limit: int = 50) -> list[dict]:
    """Classify inbound activity text that read-only sync already stored.

    Sync summaries are short, not transcripts, so anything that cannot be matched by
    rule stays unclassified and visible for a human instead of being guessed.
    """
    classified = []
    rows = (
        db.query(Activity)
        .filter(Activity.direction == "inbound", Activity.lead_id.isnot(None))
        .order_by(Activity.id.desc())
        .limit(limit)
        .all()
    )
    for activity in rows:
        text = (activity.summary or "").strip()
        if not text:
            continue
        cls, conf = classify_rule_based(text)
        if cls is None or conf < 0.85:
            continue
        exists = (
            db.query(SuggestedAction.id)
            .filter(SuggestedAction.lead_id == activity.lead_id, SuggestedAction.evidence == _evidence(text))
            .first()
        )
        if exists:
            continue
        lead = db.get(Lead, activity.lead_id)
        if lead is None:
            continue
        action = SuggestedAction(
            lead_id=lead.id,
            kind=suggestion_kind(cls),
            classification=cls,
            confidence=conf,
            evidence=_evidence(text),
            payload={"activity_id": activity.id, "source": "sync_activity"},
        )
        db.add(action)
        if cls == "STOP":
            lead.local_do_not_contact = True
        classified.append({"lead_id": lead.id, "classification": cls, "confidence": conf})
    db.commit()
    return classified
