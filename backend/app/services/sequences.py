"""Follow-up cadence (Phase 6).

The cadence only ever creates *draft* messages and follow-up tasks. Nothing here can
send anything, and every stop condition is checked from stored facts, never inferred.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import AppSetting, Lead, LeadSequenceState, Message, Sequence, SequenceStep, Task

DEFAULT_CADENCE_DAYS = [0, 3, 7, 14, 30, 60, 90, 120]
FIRST_STEP_CATEGORY = "GENERIC_OPENER"
DAY_CATEGORIES = {3: "FOLLOWUP_D3", 7: "FOLLOWUP_D7", 14: "FOLLOWUP_D14", 30: "CHECKIN_D30"}
MAX_STEPS = 24

# Stage codes that end a cadence. These are code values, not display labels.
STOP_STAGES = {"under_contract", "closed", "dead", "contract_sent"}


def cadence_days(db: Session) -> list[int]:
    row = db.get(AppSetting, "cadence")
    value = row.value if row and isinstance(row.value, dict) else {}
    days = value.get("days")
    if isinstance(days, list) and days and all(isinstance(d, int) for d in days):
        return sorted(dict.fromkeys(days))
    return list(DEFAULT_CADENCE_DAYS)


def save_cadence(db: Session, days: list[int]) -> list[int]:
    if not days or len(days) > MAX_STEPS:
        raise ValueError(f"Use between 1 and {MAX_STEPS} cadence days")
    if any(not isinstance(day, int) or not 0 <= day <= 365 for day in days):
        raise ValueError("Cadence days must be whole numbers between 0 and 365")
    cleaned = sorted(dict.fromkeys(days))
    row = db.get(AppSetting, "cadence")
    if row is None:
        db.add(AppSetting(key="cadence", value={"days": cleaned}))
    else:
        row.value = {"days": cleaned}
    # Existing sequences follow the new cadence from the next run.
    for sequence in db.query(Sequence).filter(Sequence.active.is_(True)):
        _rebuild_steps(db, sequence, cleaned)
    db.commit()
    return cleaned


def _category_for(day: int, index: int) -> str:
    if index == 0:
        return FIRST_STEP_CATEGORY
    return DAY_CATEGORIES.get(day, "MONTHLY_TOUCH")


def _rebuild_steps(db: Session, sequence: Sequence, days: list[int]) -> None:
    db.query(SequenceStep).filter(SequenceStep.sequence_id == sequence.id).delete()
    for index, day in enumerate(days):
        db.add(
            SequenceStep(
                sequence_id=sequence.id,
                day_offset=day,
                template_category=_category_for(day, index),
                sort_order=index,
            )
        )
    sequence.cadence = [[day, _category_for(day, index)] for index, day in enumerate(days)]


def default_sequence(db: Session, lead_type: str | None = None) -> Sequence:
    days = cadence_days(db)
    seq = db.query(Sequence).filter(Sequence.active.is_(True), Sequence.lead_type.is_(None)).first()
    if seq is None:
        seq = Sequence(name="Default cold cadence", lead_type=None, cadence=[], active=True)
        db.add(seq)
        db.flush()
        _rebuild_steps(db, seq, days)
        db.commit()
        db.refresh(seq)
    elif not db.query(SequenceStep).filter(SequenceStep.sequence_id == seq.id).first():
        _rebuild_steps(db, seq, days)
        db.commit()
    return seq


def start_sequence(db: Session, lead: Lead) -> LeadSequenceState:
    """Start (or restart) the cadence for one lead. Never sends anything."""
    existing = (
        db.query(LeadSequenceState)
        .filter(LeadSequenceState.lead_id == lead.id, LeadSequenceState.status == "active")
        .first()
    )
    if existing:
        return existing
    seq = default_sequence(db, getattr(lead, "lead_type", None))
    now = datetime.now(timezone.utc)
    state = LeadSequenceState(
        lead_id=lead.id, sequence_id=seq.id, current_step=0, next_due_at=now, status="active"
    )
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def pause_sequence(db: Session, lead_id: int, reason: str) -> int:
    """Stop every active cadence for a lead (a reply pauses it, nothing sends)."""
    states = (
        db.query(LeadSequenceState)
        .filter(LeadSequenceState.lead_id == lead_id, LeadSequenceState.status == "active")
        .all()
    )
    for state in states:
        state.status = "stopped"
        state.stop_reason = reason[:80]
    return len(states)


def stop_conditions_met(db: Session, lead: Lead, now: datetime | None = None) -> str | None:
    from .compliance import is_suppressed

    now = now or datetime.now(timezone.utc)
    if is_suppressed(db, getattr(lead, "primary_phone", None)):
        return "suppressed"
    if getattr(lead, "in_license", True) is False:
        return "out_of_license"
    if getattr(lead, "do_not_contact", False):
        return "dnc"
    if getattr(lead, "stage_code", None) in STOP_STAGES:
        return "stage"
    if getattr(lead, "needs_skip_trace", False):
        return "needs_skip_trace"
    appointment = db.execute(
        __import__("sqlalchemy").text(
            "SELECT 1 FROM appointments WHERE lead_id = :lead AND status = 'scheduled' "
            "AND starts_at >= :now LIMIT 1"
        ),
        {"lead": lead.id, "now": now},
    ).first()
    if appointment:
        return "appointment_set"
    # A reply pauses the cadence until Jason decides what to do.
    replied = (
        db.query(Message.id)
        .filter(Message.lead_id == lead.id, Message.direction == "inbound")
        .first()
    )
    if replied:
        return "replied"
    return None


def runner_due_today(db: Session, now: datetime | None = None) -> list[dict]:
    """Create draft messages + follow-up tasks for the steps that are due."""
    from .templates import create_draft

    now = now or datetime.now(timezone.utc)
    items: list[dict] = []
    states = db.query(LeadSequenceState).filter(LeadSequenceState.status == "active").all()
    for state in states:
        lead = db.get(Lead, state.lead_id)
        if lead is None:
            state.status, state.stop_reason = "stopped", "lead_deleted"
            db.commit()
            continue
        reason = stop_conditions_met(db, lead, now)
        if reason:
            state.status, state.stop_reason = "stopped", reason
            db.commit()
            continue
        if state.next_due_at is None or state.next_due_at > now:
            continue
        seq = db.get(Sequence, state.sequence_id)
        if seq is None or not seq.active:
            continue
        steps = (
            db.query(SequenceStep)
            .filter(SequenceStep.sequence_id == seq.id)
            .order_by(SequenceStep.sort_order)
            .all()
        )
        if state.current_step >= len(steps):
            state.status, state.next_due_at = "completed", None
            db.commit()
            continue
        step = steps[state.current_step]
        try:
            draft = create_draft(db, lead, variant="A")
            message_id = draft.id
            blocked = None
        except ValueError as error:
            # A gate (skip trace, DNC, restrictions, licence) stops the cadence instead
            # of producing a draft Jason cannot use.
            state.status, state.stop_reason = "stopped", str(error)[:80]
            db.commit()
            items.append({"lead_id": lead.id, "status": "blocked", "reason": str(error)})
            continue
        task = Task(
            lead_id=lead.id,
            title=f"Follow-up draft ready (day {step.day_offset})",
            description=f"Review the prepared draft #{message_id}. Nothing was sent.",
            priority=2,
            due_at=now,
            source="cadence",
        )
        db.add(task)
        state.current_step += 1
        next_step = steps[state.current_step] if state.current_step < len(steps) else None
        if next_step is not None:
            gap = max(1, next_step.day_offset - step.day_offset)
            state.next_due_at = now + timedelta(days=gap)
        else:
            state.status, state.next_due_at = "completed", None
        db.commit()
        items.append(
            {
                "lead_id": lead.id,
                "message_id": message_id,
                "task_id": task.id,
                "status": "drafted",
                "step": state.current_step - 1,
                "category": step.template_category,
                "blocked": blocked,
            }
        )
    return items
