"""Daily work queue, follow-up actions, activities and appointments."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Activity, Appointment, Followup, Lead
from app.services.audit import audit
from app.services.leads import (
    primary_property,
    refresh_lead_rollups,
    serialize_appointment,
    serialize_followup,
)
from app.services.pipeline import COMPLETION_OUTCOMES, local_today, today_bounds
from app.services.workqueue import build_work_queue, completion_denominator

router = APIRouter(tags=["work queue"])


class FollowupCreate(BaseModel):
    lead_id: str
    due_at: datetime
    reason: Optional[str] = None
    suggested_next_action: Optional[str] = None
    priority: int = Field(3, ge=1, le=5)
    ai_suggested: bool = False


class FollowupUpdate(BaseModel):
    due_at: Optional[datetime] = None
    priority: Optional[int] = Field(None, ge=1, le=5)
    reason: Optional[str] = None
    suggested_next_action: Optional[str] = None


class FollowupComplete(BaseModel):
    outcome: str
    notes: Optional[str] = None
    schedule_next_at: Optional[datetime] = None
    next_reason: Optional[str] = None


class AppointmentCreate(BaseModel):
    lead_id: str
    scheduled_at: datetime
    appointment_type: Optional[str] = "seller appointment"
    appointment_subtype: Optional[str] = None
    notes: Optional[str] = None


class AppointmentUpdate(BaseModel):
    status: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    notes: Optional[str] = None


@router.get("/work-queue")
def work_queue(db: Session = Depends(get_db)):
    return build_work_queue(db)


@router.get("/work-queue/stats")
def work_queue_stats(db: Session = Depends(get_db)):
    return completion_denominator(db)


# --------------------------------------------------------------------------- #
# Follow-ups
# --------------------------------------------------------------------------- #
@router.get("/followups")
def list_followups(
    status: Optional[str] = "open",
    lead_id: Optional[str] = None,
    due: Optional[str] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    from app.config import settings

    query = db.query(Followup)
    if status and status != "all":
        query = query.filter(Followup.status == status)
    if lead_id:
        query = query.filter(Followup.lead_id == lead_id)
    day_start, day_end = today_bounds(settings.timezone)
    if due == "overdue":
        query = query.filter(Followup.due_at < day_start)
    elif due == "today":
        query = query.filter(Followup.due_at >= day_start, Followup.due_at < day_end)
    elif due == "upcoming":
        query = query.filter(Followup.due_at >= day_end)
    items = query.order_by(Followup.due_at.asc()).limit(limit).all()
    out = []
    for f in items:
        data = serialize_followup(f)
        lead = db.get(Lead, f.lead_id)
        prop = primary_property(lead) if lead else None
        data["lead"] = {
            "id": lead.id if lead else None,
            "name": lead.display_name if lead else None,
            "phone": lead.primary_phone if lead else None,
            "stage": lead.pipeline_stage if lead else None,
            "do_not_contact": lead.do_not_contact if lead else False,
            "property_address": prop.formatted_address if prop else None,
        }
        out.append(data)
    return {"items": out, "total": len(out)}


@router.post("/followups", status_code=201)
def create_followup(payload: FollowupCreate, db: Session = Depends(get_db)):
    lead = db.get(Lead, payload.lead_id)
    if not lead:
        raise ValueError("Lead not found")
    fu = Followup(
        lead_id=lead.id,
        due_at=payload.due_at,
        priority=payload.priority,
        reason=payload.reason,
        suggested_next_action=payload.suggested_next_action,
        creation_source="ai" if payload.ai_suggested else "manual",
        ai_suggested=payload.ai_suggested,
        status="open",
    )
    prop = primary_property(lead)
    fu.property_id = prop.id if prop else None
    db.add(fu)
    refresh_lead_rollups(db, lead)
    db.commit()
    audit(db, "followup.create", "followup", fu.id, {"due_at": payload.due_at.isoformat(), "lead_id": lead.id})
    return serialize_followup(fu)


@router.patch("/followups/{followup_id}")
def update_followup(followup_id: str, payload: FollowupUpdate, db: Session = Depends(get_db)):
    fu = db.get(Followup, followup_id)
    if not fu:
        raise ValueError("Follow-up not found")
    if fu.status != "open":
        raise ValueError("Only open follow-ups can be edited")
    data = payload.model_dump(exclude_unset=True)
    if data.get("due_at") is not None:
        fu.due_at = data["due_at"]
    if data.get("priority") is not None:
        fu.priority = data["priority"]
    if data.get("reason") is not None:
        fu.reason = data["reason"]
    if data.get("suggested_next_action") is not None:
        fu.suggested_next_action = data["suggested_next_action"]
    lead = db.get(Lead, fu.lead_id)
    if lead:
        refresh_lead_rollups(db, lead)
    db.commit()
    audit(db, "followup.reschedule", "followup", fu.id, {"due_at": fu.due_at.isoformat()})
    return serialize_followup(fu)


@router.post("/followups/{followup_id}/complete")
def complete_followup(followup_id: str, payload: FollowupComplete, db: Session = Depends(get_db)):
    fu = db.get(Followup, followup_id)
    if not fu:
        raise ValueError("Follow-up not found")
    if fu.status != "open":
        raise ValueError("Follow-up is already closed")
    if payload.outcome not in COMPLETION_OUTCOMES:
        raise ValueError(f"Unknown outcome '{payload.outcome}'. Allowed: {COMPLETION_OUTCOMES}")

    fu.status = "completed"
    fu.completed_at = datetime.utcnow()
    fu.completion_outcome = payload.outcome
    fu.completion_notes = payload.notes
    lead = db.get(Lead, fu.lead_id)

    # A completed follow-up records what the USER did. It never implies that a
    # message was sent by this application.
    if lead:
        db.add(
            Activity(
                lead_id=lead.id,
                activity_type="call" if payload.outcome in {"connected", "no_answer", "left_voicemail", "callback_requested", "wrong_number"} else "note",
                direction="outbound" if payload.outcome in {"connected", "no_answer", "left_voicemail", "callback_requested", "wrong_number"} else "internal",
                outcome=payload.outcome,
                summary=f"Follow-up completed: {payload.outcome}",
                detail=payload.notes,
                occurred_at=datetime.utcnow(),
                source="local",
            )
        )
        if payload.outcome in {"connected", "callback_requested", "seller_not_interested", "appointment_scheduled"}:
            lead.contact_status = payload.outcome
            lead.last_contact_at = datetime.utcnow()
        elif lead.contact_status == "never_contacted":
            lead.contact_status = payload.outcome if payload.outcome in {"no_answer", "left_voicemail", "wrong_number"} else "no_answer"
        if payload.outcome == "do_not_contact":
            lead.do_not_contact = True
            lead.contact_status = "do_not_contact"
        if payload.schedule_next_at:
            db.add(
                Followup(
                    lead_id=lead.id,
                    property_id=fu.property_id,
                    due_at=payload.schedule_next_at,
                    reason=payload.next_reason or "Next step after completed follow-up",
                    suggested_next_action="Continue the conversation and record the outcome",
                    priority=fu.priority,
                    creation_source="manual",
                    status="open",
                )
            )
        refresh_lead_rollups(db, lead)
    db.commit()
    audit(
        db,
        "followup.complete",
        "followup",
        fu.id,
        {"outcome": payload.outcome, "note": "Local record only — no message was sent by this app"},
    )
    return {"followup": serialize_followup(fu), "note": "Recorded locally. No message was sent by this application."}


@router.post("/followups/{followup_id}/cancel")
def cancel_followup(followup_id: str, reason: Optional[str] = None, db: Session = Depends(get_db)):
    fu = db.get(Followup, followup_id)
    if not fu:
        raise ValueError("Follow-up not found")
    fu.status = "cancelled"
    fu.completion_notes = reason or "Cancelled by user"
    fu.completed_at = datetime.utcnow()
    lead = db.get(Lead, fu.lead_id)
    if lead:
        refresh_lead_rollups(db, lead)
    db.commit()
    audit(db, "followup.cancel", "followup", fu.id, {"reason": reason})
    return serialize_followup(fu)


# --------------------------------------------------------------------------- #
# Activities
# --------------------------------------------------------------------------- #
@router.get("/activities")
def list_activities(lead_id: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db)):
    query = db.query(Activity).order_by(Activity.occurred_at.desc())
    if lead_id:
        query = query.filter(Activity.lead_id == lead_id)
    items = query.limit(limit).all()
    out = []
    for a in items:
        lead = db.get(Lead, a.lead_id) if a.lead_id else None
        out.append(
            {
                "id": a.id,
                "lead_id": a.lead_id,
                "lead_name": lead.display_name if lead else None,
                "activity_type": a.activity_type,
                "direction": a.direction,
                "outcome": a.outcome,
                "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
                "source": a.source,
                "summary": a.summary,
                "detail": a.detail,
            }
        )
    return {"items": out, "total": len(out)}


# --------------------------------------------------------------------------- #
# Appointments
# --------------------------------------------------------------------------- #
@router.get("/appointments")
def list_appointments(
    upcoming: Optional[bool] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    from app.config import settings

    query = db.query(Appointment).join(Lead, Lead.id == Appointment.lead_id, isouter=True)
    day_start, day_end = today_bounds(settings.timezone)
    if upcoming is True:
        query = query.filter(Appointment.scheduled_at >= day_start)
    elif upcoming is False:
        query = query.filter(Appointment.scheduled_at < day_start)
    if start:
        try:
            query = query.filter(Appointment.scheduled_at >= datetime.fromisoformat(start))
        except ValueError:
            pass
    if end:
        try:
            query = query.filter(Appointment.scheduled_at <= datetime.fromisoformat(end))
        except ValueError:
            pass
    items = query.order_by(Appointment.scheduled_at.asc()).limit(limit).all()
    out = []
    for a in items:
        data = serialize_appointment(a)
        lead = db.get(Lead, a.lead_id) if a.lead_id else None
        prop = primary_property(lead) if lead else None
        data["lead"] = {
            "id": lead.id if lead else None,
            "name": lead.display_name if lead else None,
            "phone": lead.primary_phone if lead else None,
            "stage": lead.pipeline_stage if lead else None,
            "property_address": prop.formatted_address if prop else None,
        }
        data["is_today"] = bool(a.scheduled_at and day_start <= a.scheduled_at < day_end)
        out.append(data)
    return {"items": out, "total": len(out), "today": local_today(settings.timezone).isoformat()}


@router.post("/appointments", status_code=201)
def create_appointment(payload: AppointmentCreate, db: Session = Depends(get_db)):
    lead = db.get(Lead, payload.lead_id)
    if not lead:
        raise ValueError("Lead not found")
    prop = primary_property(lead)
    appt = Appointment(
        lead_id=lead.id,
        property_id=prop.id if prop else None,
        scheduled_at=payload.scheduled_at,
        appointment_type=payload.appointment_type,
        appointment_subtype=payload.appointment_subtype,
        notes=payload.notes,
        status="scheduled",
        source="local",
    )
    db.add(appt)
    if lead.pipeline_stage in {"contacted", "qualified", "follow_up"}:
        lead.pipeline_stage = "appointment_set"
    db.add(
        Activity(
            lead_id=lead.id,
            activity_type="appointment",
            direction="internal",
            occurred_at=datetime.utcnow(),
            summary=f"Appointment scheduled for {payload.scheduled_at.isoformat()}",
            detail=payload.notes,
            source="local",
        )
    )
    refresh_lead_rollups(db, lead)
    db.commit()
    audit(db, "appointment.create", "appointment", appt.id, {"lead_id": lead.id, "when": payload.scheduled_at.isoformat()})
    return serialize_appointment(appt)


@router.patch("/appointments/{appointment_id}")
def update_appointment(appointment_id: str, payload: AppointmentUpdate, db: Session = Depends(get_db)):
    appt = db.get(Appointment, appointment_id)
    if not appt:
        raise ValueError("Appointment not found")
    data = payload.model_dump(exclude_unset=True)
    if data.get("status"):
        allowed = {"scheduled", "kept", "not_kept", "no_answer", "dismissed"}
        if data["status"] not in allowed:
            raise ValueError(f"Unknown appointment status. Allowed: {sorted(allowed)}")
        appt.status = data["status"]
    if data.get("scheduled_at"):
        appt.scheduled_at = data["scheduled_at"]
    if data.get("notes") is not None:
        appt.notes = data["notes"]
    if appt.lead_id:
        lead = db.get(Lead, appt.lead_id)
        if lead:
            db.add(
                Activity(
                    lead_id=lead.id,
                    activity_type="appointment",
                    direction="internal",
                    occurred_at=datetime.utcnow(),
                    summary=f"Appointment {appt.status}",
                    detail=appt.notes,
                    source="local",
                )
            )
            refresh_lead_rollups(db, lead)
    db.commit()
    audit(db, "appointment.update", "appointment", appt.id, {"status": appt.status})
    return serialize_appointment(appt)
