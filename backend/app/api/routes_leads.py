"""Lead list, detail, editing and export endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Activity, Followup, Lead
from app.services.audit import audit
from app.services.comps import comps_brief
from app.services.export import export_filename, rows_to_csv
from app.services.leads import (
    primary_property,
    refresh_lead_rollups,
    serialize_activity,
    serialize_lead,
)
from app.services.pipeline import COMPLETION_OUTCOMES, CONTACT_OUTCOMES, STAGE_ORDER, STAGES
from app.services.querying import apply_filters, apply_sort, base_query
from app.services.settings_service import followup_rules

router = APIRouter(tags=["leads"])


class LeadUpdate(BaseModel):
    pipeline_stage: Optional[str] = None
    source_status: Optional[str] = None
    contact_status: Optional[str] = None
    assigned_manager: Optional[str] = None
    lead_source: Optional[str] = None
    do_not_contact: Optional[bool] = None
    is_hot_lead: Optional[bool] = None
    notes: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    primary_phone: Optional[str] = None
    email: Optional[str] = None
    next_followup_at: Optional[datetime] = None
    clear_next_followup: bool = False


class ActivityCreate(BaseModel):
    activity_type: str = Field("note")
    direction: Optional[str] = "internal"
    outcome: Optional[str] = None
    summary: str
    detail: Optional[str] = None
    occurred_at: Optional[datetime] = None


@router.get("/leads")
def list_leads(
    q: Optional[str] = None,
    stage: Optional[list[str]] = Query(default=None),
    contact_status: Optional[list[str]] = Query(default=None),
    source: Optional[list[str]] = Query(default=None),
    manager: Optional[list[str]] = Query(default=None),
    state: Optional[list[str]] = Query(default=None),
    followup_state: Optional[str] = None,
    do_not_contact: Optional[bool] = None,
    never_contacted: Optional[bool] = None,
    missing: Optional[str] = None,
    origin: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort: Optional[str] = "updated",
    direction: str = "desc",
    page: int = 1,
    page_size: int = 25,
    db: Session = Depends(get_db),
):
    from app.config import settings

    rules = followup_rules(db)
    params: dict[str, Any] = {
        "q": q,
        "stage": stage,
        "contact_status": contact_status,
        "source": source,
        "manager": manager,
        "state": state,
        "followup_state": followup_state,
        "do_not_contact": do_not_contact,
        "never_contacted": never_contacted,
        "missing": missing,
        "origin": origin,
        "date_from": date_from,
        "date_to": date_to,
        "unscheduled_stage_keys": rules.get("unscheduled_stage_keys"),
        "upcoming_lookahead_days": rules.get("upcoming_lookahead_days"),
    }
    query = apply_sort(apply_filters(base_query(db), params, settings.timezone), sort, direction)
    total = query.count()
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, -(-total // page_size)),
        "items": [serialize_lead(lead, db) for lead in items],
    }


@router.get("/leads/export")
def export_leads(
    q: Optional[str] = None,
    stage: Optional[list[str]] = Query(default=None),
    contact_status: Optional[list[str]] = Query(default=None),
    source: Optional[list[str]] = Query(default=None),
    manager: Optional[list[str]] = Query(default=None),
    followup_state: Optional[str] = None,
    never_contacted: Optional[bool] = None,
    missing: Optional[str] = None,
    db: Session = Depends(get_db),
):
    from app.config import settings

    params = {
        "q": q,
        "stage": stage,
        "contact_status": contact_status,
        "source": source,
        "manager": manager,
        "followup_state": followup_state,
        "never_contacted": never_contacted,
        "missing": missing,
    }
    leads = apply_sort(apply_filters(base_query(db), params, settings.timezone), "name", "asc").limit(5000).all()
    headers = [
        "lead_id", "resimpli_id", "first_name", "last_name", "phone", "email", "stage", "source_status",
        "contact_status", "source", "manager", "created", "last_contact", "next_followup", "do_not_contact",
        "property_address", "city", "state", "zip", "origin",
    ]
    rows = []
    for lead in leads:
        prop = primary_property(lead)
        rows.append(
            [
                lead.id, lead.external_id, lead.first_name, lead.last_name, lead.primary_phone, lead.email,
                lead.pipeline_stage, lead.source_status, lead.contact_status, lead.lead_source, lead.assigned_manager,
                lead.original_creation_date.isoformat() if lead.original_creation_date else "",
                lead.last_contact_at.isoformat() if lead.last_contact_at else "",
                lead.next_followup_at.isoformat() if lead.next_followup_at else "",
                "yes" if lead.do_not_contact else "no",
                prop.address_line1 if prop else "", prop.city if prop else "", prop.state if prop else "",
                prop.zip_code if prop else "", lead.origin,
            ]
        )
    csv_body = rows_to_csv(headers, rows)
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{export_filename("leads")}"'},
    )


@router.get("/leads/meta/reference")
def lead_reference_data(db: Session = Depends(get_db)):
    from app.models import Lead as L

    stages = [
        {"key": k, "label": v["label"], "order": v["order"], "color": v["color"]}
        for k, v in sorted(STAGES.items(), key=lambda kv: kv[1]["order"])
    ]
    sources = [r[0] for r in db.query(L.lead_source).filter(L.lead_source.isnot(None)).distinct().order_by(L.lead_source).all()]
    managers = [r[0] for r in db.query(L.assigned_manager).filter(L.assigned_manager.isnot(None)).distinct().order_by(L.assigned_manager).all()]
    return {
        "stages": stages,
        "stage_order": STAGE_ORDER,
        "contact_outcomes": [{"key": k, "label": v["label"]} for k, v in CONTACT_OUTCOMES.items()],
        "completion_outcomes": COMPLETION_OUTCOMES,
        "sources": sources,
        "managers": managers,
    }


@router.get("/leads/{lead_id}")
def lead_detail(lead_id: str, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise ValueError("Lead not found")
    data = serialize_lead(lead, db, detail=True)
    data["resimpli_url"] = _resimpli_url(lead)
    data["timeline"] = _timeline(db, lead)
    return data


@router.get("/leads/{lead_id}/comps")
def lead_comps(lead_id: str, db: Session = Depends(get_db)):
    """Comparable-property brief: subject facts + criteria + portal links.

    Never fabricates comps — see app.services.comps for the honesty rules.
    """
    lead = db.get(Lead, lead_id)
    if not lead:
        raise ValueError("Lead not found")
    return comps_brief(lead)


def _resimpli_url(lead: Lead) -> Optional[str]:
    """Only constructed when a documented pattern is known.

    REsimpli does not publish a stable public lead URL pattern in the Open API
    documentation, so this returns None rather than guessing a link.
    """
    return None


def _timeline(db: Session, lead: Lead) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for a in lead.activities:
        items.append(
            {
                "kind": "activity",
                "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
                "source": a.source,
                "data": serialize_activity(a),
            }
        )
    for f in lead.followups:
        items.append(
            {
                "kind": "followup",
                "occurred_at": f.created_at.isoformat() if f.created_at else None,
                "source": f.creation_source,
                "data": {
                    "id": f.id,
                    "due_at": f.due_at.isoformat() if f.due_at else None,
                    "status": f.status,
                    "priority": f.priority,
                    "reason": f.reason,
                    "action": f.suggested_next_action,
                    "completion_outcome": f.completion_outcome,
                    "completed_at": f.completed_at.isoformat() if f.completed_at else None,
                },
            }
        )
    for ap in lead.appointments:
        items.append(
            {
                "kind": "appointment",
                "occurred_at": ap.scheduled_at.isoformat() if ap.scheduled_at else None,
                "source": ap.source,
                "data": {
                    "id": ap.id,
                    "status": ap.status,
                    "type": ap.appointment_type,
                    "notes": ap.notes,
                },
            }
        )
    items.sort(key=lambda i: i.get("occurred_at") or "", reverse=True)
    return items


@router.patch("/leads/{lead_id}")
def update_lead(lead_id: str, payload: LeadUpdate, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise ValueError("Lead not found")
    changes = {}
    data = payload.model_dump(exclude_unset=True)
    if "pipeline_stage" in data and data["pipeline_stage"] is not None:
        if data["pipeline_stage"] not in STAGES:
            raise ValueError(f"Unknown pipeline stage '{data['pipeline_stage']}'")
        if lead.pipeline_stage != data["pipeline_stage"]:
            changes["pipeline_stage"] = {"from": lead.pipeline_stage, "to": data["pipeline_stage"]}
            db.add(
                Activity(
                    lead_id=lead.id,
                    activity_type="status_change",
                    direction="internal",
                    occurred_at=datetime.utcnow(),
                    summary=f"Stage changed to {STAGES[data['pipeline_stage']]['label']}",
                    source="local",
                )
            )
        lead.pipeline_stage = data["pipeline_stage"]
    for field in ("source_status", "contact_status", "assigned_manager", "lead_source", "notes", "first_name", "last_name"):
        if field in data and data[field] is not None:
            if getattr(lead, field) != data[field]:
                changes[field] = {"from": getattr(lead, field), "to": data[field]}
            setattr(lead, field, data[field])
    if data.get("primary_phone"):
        from app.services.normalization import normalize_phone

        norm, display, _ = normalize_phone(data["primary_phone"])
        lead.primary_phone = display or data["primary_phone"]
        lead.phone_normalized = norm
        changes["primary_phone"] = data["primary_phone"]
    if data.get("email"):
        from app.services.normalization import normalize_email

        lead.email = data["email"]
        lead.email_normalized = normalize_email(data["email"])
        changes["email"] = data["email"]
    if data.get("do_not_contact") is not None and lead.do_not_contact != data["do_not_contact"]:
        lead.do_not_contact = bool(data["do_not_contact"])
        if lead.do_not_contact:
            lead.contact_status = "do_not_contact"
            open_fus = db.query(Followup).filter(Followup.lead_id == lead.id, Followup.status == "open").all()
            for fu in open_fus:
                fu.status = "cancelled"
                fu.completion_notes = "Cancelled automatically: Do Not Contact set"
        changes["do_not_contact"] = lead.do_not_contact
    if data.get("is_hot_lead") is not None:
        lead.is_hot_lead = bool(data["is_hot_lead"])
    if data.get("clear_next_followup"):
        lead.next_followup_at = None
        changes["next_followup_at"] = None
    elif data.get("next_followup_at") is not None:
        lead.next_followup_at = data["next_followup_at"]
        changes["next_followup_at"] = data["next_followup_at"].isoformat()

    refresh_lead_rollups(db, lead)
    db.commit()
    audit(db, "lead.update", "lead", lead.id, changes)
    return serialize_lead(lead, db, detail=True)


@router.post("/leads/{lead_id}/activities")
def add_activity(lead_id: str, payload: ActivityCreate, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise ValueError("Lead not found")
    if payload.outcome and payload.outcome not in COMPLETION_OUTCOMES and payload.outcome not in CONTACT_OUTCOMES:
        raise ValueError(f"Unknown outcome '{payload.outcome}'. Allowed: {COMPLETION_OUTCOMES}")
    activity = Activity(
        lead_id=lead.id,
        activity_type=payload.activity_type,
        direction=payload.direction,
        outcome=payload.outcome,
        summary=payload.summary,
        detail=payload.detail,
        occurred_at=payload.occurred_at or datetime.utcnow(),
        source="local",
    )
    db.add(activity)
    refresh_lead_rollups(db, lead)
    db.commit()
    audit(db, "activity.create", "lead", lead.id, {"summary": payload.summary, "outcome": payload.outcome})
    return serialize_activity(activity)
