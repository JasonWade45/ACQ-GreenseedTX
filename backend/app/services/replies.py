"""Reply classification and suggested replies (Phase 6)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Lead, Message, Task
from .compliance import add_suppression
from .templates import validate_message

STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}


def classify_rule_based(text: str) -> tuple[str | None, float]:
    if not text:
        return None, 0.0
    low = text.strip().lower()
    tokens = low.replace(",", " ").replace(".", " ").split()
    if tokens and tokens[0] in STOP_WORDS:
        return "STOP", 1.0
    if any(k in low for k in STOP_WORDS):
        return "STOP", 0.95
    if "wrong number" in low:
        return "WRONG_NUMBER", 0.95
    if any(w in low for w in ("not interested", "no thanks", "remove me", "don't text", "do not text")):
        return "NOT_INTERESTED", 0.9
    if any(w in low for w in ("how much", "price", "offer", "worth", "cost")):
        return "WANTS_PRICE", 0.85
    if any(w in low for w in ("yes", "interested", "tell me more", "call me", "sure", "i'm open")):
        return "INTERESTED", 0.85
    if any(w in low for w in ("later", "not now", "maybe", "next month", "busy", "not yet")):
        return "NOT_NOW", 0.8
    if "?" in low:
        return "QUESTION", 0.7
    return "OTHER", 0.5


def classify(db: Session, text: str, use_ai: bool = False) -> tuple[str, float]:
    cls, conf = classify_rule_based(text)
    if cls is not None and conf >= 0.85:
        return cls, conf
    # AI classifier would go here; fall back to rule result or OTHER.
    if cls is None:
        return "OTHER", 0.4
    return cls, conf


def handle_inbound(db: Session, lead: Lead, text: str) -> dict:
    classification, confidence = classify(db, text)
    # pause/stop sequence
    from ..models import LeadSequenceState

    states = db.query(LeadSequenceState).filter(LeadSequenceState.lead_id == lead.id, LeadSequenceState.status == "active").all()
    for st in states:
        if classification in ("STOP", "NOT_INTERESTED", "WRONG_NUMBER"):
            st.status = "stopped"
            st.stop_reason = classification.lower()
    # suppression
    if classification == "STOP":
        add_suppression(db, lead.primary_phone or "", "stop", "inbound_reply")
    if classification == "WRONG_NUMBER":
        add_suppression(db, lead.primary_phone or "", "wrong_number", "inbound_reply")
    # stage update (best-effort, only if a matching stage exists)
    if classification in ("INTERESTED", "WANTS_PRICE"):
        lead.contact_status = "contacted"
    # create task
    task = Task(lead_id=lead.id, title=f"Reply: {classification}", description=text, priority=1 if classification in ("INTERESTED", "WANTS_PRICE") else 3, source="reply")
    db.add(task)
    # store message
    msg = Message(lead_id=lead.id, direction="inbound", body=text, status="RECEIVED", classification=classification, confidence=confidence)
    db.add(msg)
    db.commit()
    # suggested reply (draft) for interested/wants_price
    suggested = None
    if classification in ("INTERESTED", "WANTS_PRICE"):
        from .templates import create_draft

        suggested = create_draft(db, lead, variant="A")
        suggested.body = "Hi " + (lead.first_name or "there") + ", thanks for getting back to me. " + ("What price range were you thinking?" if classification == "WANTS_PRICE" else "Would a quick call this week work?") + "\nReply STOP to opt out"
        ok, reasons = validate_message(suggested.body, bool(lead.first_name or lead.full_name))
        suggested.validator_result = {"ok": ok, "reasons": reasons}
        suggested.status = "DRAFT"
        db.commit()
    return {"classification": classification, "confidence": confidence, "task_id": task.id, "suggested_draft_id": (suggested.id if suggested else None)}
