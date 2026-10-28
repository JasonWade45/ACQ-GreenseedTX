"""Sequences and follow-up cadence (Phase 4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from ..models import Sequence, SequenceStep, LeadSequenceState, Lead
from .compliance import is_suppressed, can_send
from .templates import create_draft


DEFAULT_CADENCE = [
    (0, "GENERIC_OPENER"),
    (3, "FOLLOWUP_D3"),
    (7, "FOLLOWUP_D7"),
    (14, "FOLLOWUP_D14"),
    (30, "CHECKIN_D30"),
    (60, "MONTHLY_TOUCH"),
    (90, "MONTHLY_TOUCH"),
    (120, "MONTHLY_TOUCH"),
]

STOP_STATUSES = {"Dead", "Under Contract", "Appointment Set"}


def default_sequence(db: Session, lead_type: str | None = None) -> Sequence:
    seq = db.query(Sequence).filter(Sequence.active.is_(True)).first()
    if seq is None:
        seq = Sequence(name="Default cadence", lead_type=lead_type, cadence=DEFAULT_CADENCE, active=True)
        db.add(seq)
        db.commit()
        db.refresh(seq)
        for i, (day, cat) in enumerate(DEFAULT_CADENCE):
            db.add(SequenceStep(sequence_id=seq.id, day_offset=day, template_category=cat, sort_order=i))
        db.commit()
    return seq


def start_sequence(db: Session, lead: Lead) -> LeadSequenceState:
    seq = default_sequence(db, getattr(lead, "lead_type", None))
    now = datetime.now(timezone.utc)
    state = LeadSequenceState(lead_id=lead.id, sequence_id=seq.id, current_step=0, next_due_at=now, status="active")
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def stop_conditions_met(db: Session, lead: Lead) -> str | None:
    if is_suppressed(db, getattr(lead, "primary_phone", None)):
        return "suppressed"
    if getattr(lead, "in_license", True) is False:
        return "out_of_license"
    if getattr(lead, "source_status", None) in STOP_STATUSES:
        return "status_change"
    if getattr(lead, "local_do_not_contact", False) or getattr(lead, "source_do_not_contact", False):
        return "dnc"
    return None


def runner_due_today(db: Session) -> list[dict]:
    """Compute due sequence items, creating DRAFT messages (never auto-sending)."""
    now = datetime.now(timezone.utc)
    items = []
    states = db.query(LeadSequenceState).filter(LeadSequenceState.status == "active").all()
    for st in states:
        lead = db.get(Lead, st.lead_id)
        if lead is None:
            st.status = "stopped"
            st.stop_reason = "lead_deleted"
            continue
        reason = stop_conditions_met(db, lead)
        if reason:
            st.status = "stopped"
            st.stop_reason = reason
            db.commit()
            continue
        if st.next_due_at is None or st.next_due_at > now:
            continue
        seq = db.get(Sequence, st.sequence_id)
        if seq is None or not seq.active:
            continue
        steps = db.query(SequenceStep).filter(SequenceStep.sequence_id == seq.id).order_by(SequenceStep.sort_order).all()
        if st.current_step >= len(steps):
            st.status = "completed"
            db.commit()
            continue
        step = steps[st.current_step]
        # check caps / quiet hours
        ok, why = can_send(db, lead, now)
        if not ok:
            items.append({"lead_id": lead.id, "status": "blocked", "reason": why, "step": st.current_step})
            continue
        # create draft
        cat = step.template_category
        tmpl = db.query(__import__("app.models", fromlist=["Template"]).Template).filter_by(category=cat, active=True).first()
        tmpl_id = tmpl.id if tmpl else None
        m = create_draft(db, lead, template_id=tmpl_id, variant="A")
        # advance
        st.current_step += 1
        # next due date
        next_step = steps[st.current_step] if st.current_step < len(steps) else None
        if next_step is not None:
            st.next_due_at = now + timedelta(days=next_step.day_offset - step.day_offset) if next_step.day_offset > step.day_offset else now + timedelta(days=1)
        else:
            st.status = "completed"
            st.next_due_at = None
        db.commit()
        items.append({"lead_id": lead.id, "message_id": m.id, "status": "drafted", "step": st.current_step - 1, "category": cat})
    return items