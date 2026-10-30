"""Local features carried over from the Acquisition CRM Hub.

Calls, tags, desk assignment and the automation rules live here. Every route is local
bookkeeping: none of them sends a message, dials a number or writes to the CRM. The only
outbound routes in the application remain the ones declared in ``route_allowlist.py``.
"""

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import (
    AssignmentRule,
    AuditLog,
    AutomationLog,
    AutomationRule,
    CallLog,
    Lead,
    LeadTag,
)
from .schemas import StrictModel
from .services import assignment, automation, calls

router = APIRouter(prefix="/api")


class CallIn(StrictModel):
    outcome: Literal[
        "connected",
        "interested",
        "wants_offer",
        "no_answer",
        "voicemail",
        "callback",
        "not_interested",
        "dnc",
        "wrong_number",
    ]
    direction: Literal["outbound", "inbound"] = "outbound"
    duration_seconds: Optional[int] = Field(default=None, ge=0, le=86400)
    notes: Optional[str] = Field(default=None, max_length=20000)
    next_step: Optional[str] = Field(default=None, max_length=2000)
    occurred_at: Optional[datetime] = None


class TagIn(StrictModel):
    tag: str = Field(min_length=1, max_length=60)


class AssignmentRuleIn(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    priority: int = Field(default=100, ge=0, le=1000)
    enabled: bool = True
    is_fallback: bool = False
    state: Optional[str] = Field(default=None, min_length=2, max_length=2)
    city: Optional[str] = Field(default=None, max_length=120)
    target_assignee: str = Field(min_length=1, max_length=120)
    notes: Optional[str] = Field(default=None, max_length=2000)


class AssignmentRulePatch(StrictModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    priority: Optional[int] = Field(default=None, ge=0, le=1000)
    enabled: Optional[bool] = None
    is_fallback: Optional[bool] = None
    state: Optional[str] = Field(default=None, min_length=2, max_length=2)
    city: Optional[str] = Field(default=None, max_length=120)
    target_assignee: Optional[str] = Field(default=None, min_length=1, max_length=120)
    notes: Optional[str] = Field(default=None, max_length=2000)


class AssignmentApplyIn(StrictModel):
    only_unassigned: bool = False
    lead_ids: Optional[list[int]] = Field(default=None, max_length=500)


class ManualAssignmentIn(StrictModel):
    assigned_manager: str = Field(min_length=1, max_length=120)


class AutomationRuleIn(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    rule_type: Literal["stale_lead", "hot_lead", "dead_lead"]
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class AutomationRulePatch(StrictModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    config: Optional[dict] = None
    enabled: Optional[bool] = None


def _lead(db: Session, lead_id: int) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "Seller lead not found")
    return lead


@router.get("/leads/{lead_id}/conversations")
def list_calls(lead_id: int, db: Session = Depends(get_db)):
    lead = _lead(db, lead_id)
    rows = db.scalars(
        select(CallLog)
        .where(CallLog.lead_id == lead.id)
        .order_by(CallLog.occurred_at.desc(), CallLog.id.desc())
    ).all()
    last = rows[0] if rows else None
    return {
        "items": [calls.call_dict(row) for row in rows],
        "outcomes": [
            {"code": code, "label": data["label"]} for code, data in calls.OUTCOMES.items()
        ],
        "last_outcome": last.outcome if last else None,
        "suggestion": calls.suggest_followup(last.outcome) if last else None,
    }


@router.post("/leads/{lead_id}/conversations", status_code=201)
def record_call(lead_id: int, body: CallIn, db: Session = Depends(get_db)):
    lead = _lead(db, lead_id)
    try:
        return calls.record_call(
            db,
            lead,
            outcome=body.outcome,
            direction=body.direction,
            duration_seconds=body.duration_seconds,
            notes=body.notes,
            next_step=body.next_step,
            occurred_at=body.occurred_at,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from None


@router.get("/leads/{lead_id}/conversations/script")
def live_script(lead_id: int, db: Session = Depends(get_db)):
    return {"script": calls.build_live_script(_lead(db, lead_id))}


@router.get("/leads/{lead_id}/tags")
def list_tags(lead_id: int, db: Session = Depends(get_db)):
    lead = _lead(db, lead_id)
    rows = db.scalars(select(LeadTag).where(LeadTag.lead_id == lead.id).order_by(LeadTag.tag)).all()
    return [{"id": row.id, "tag": row.tag} for row in rows]


@router.post("/leads/{lead_id}/tags", status_code=201)
def add_tag(lead_id: int, body: TagIn, db: Session = Depends(get_db)):
    lead = _lead(db, lead_id)
    tag = body.tag.strip()
    existing = db.scalar(select(LeadTag).where(LeadTag.lead_id == lead.id, LeadTag.tag == tag))
    if existing:
        return {"id": existing.id, "tag": existing.tag}
    row = LeadTag(lead_id=lead.id, tag=tag)
    db.add(row)
    db.add(AuditLog(lead_id=lead.id, action="tag_added", details={"tag": tag}))
    db.commit()
    db.refresh(row)
    return {"id": row.id, "tag": row.tag}


@router.delete("/leads/{lead_id}/tags/{tag_id}", status_code=204)
def delete_tag(lead_id: int, tag_id: int, db: Session = Depends(get_db)):
    lead = _lead(db, lead_id)
    row = db.get(LeadTag, tag_id)
    if row is None or row.lead_id != lead.id:
        raise HTTPException(404, "Tag not found")
    db.delete(row)
    db.add(AuditLog(lead_id=lead.id, action="tag_removed", details={"tag": row.tag}))
    db.commit()
    return None


@router.get("/assignment/rules")
def list_assignment_rules(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(AssignmentRule).order_by(AssignmentRule.priority.asc(), AssignmentRule.id.asc())
    ).all()
    return [assignment.rule_dict(row) for row in rows]


@router.post("/assignment/rules", status_code=201)
def create_assignment_rule(body: AssignmentRuleIn, db: Session = Depends(get_db)):
    if body.is_fallback and (body.state or body.city):
        raise HTTPException(400, "A fallback rule cannot also filter by state or city")
    if not body.is_fallback and not (body.state or body.city):
        raise HTTPException(400, "A rule needs a state or a city, or must be the fallback")
    if db.scalar(select(AssignmentRule).where(AssignmentRule.name == body.name)):
        raise HTTPException(409, "An assignment rule with that name already exists")
    row = AssignmentRule(**body.model_dump())
    if row.state:
        row.state = row.state.upper()
    db.add(row)
    db.add(AuditLog(action="assignment_rule_created", details={"name": row.name}))
    db.commit()
    db.refresh(row)
    return assignment.rule_dict(row)


@router.patch("/assignment/rules/{rule_id}")
def update_assignment_rule(rule_id: int, body: AssignmentRulePatch, db: Session = Depends(get_db)):
    row = db.get(AssignmentRule, rule_id)
    if row is None:
        raise HTTPException(404, "Assignment rule not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value.upper() if key == "state" and value else value)
    db.add(AuditLog(action="assignment_rule_updated", details={"name": row.name}))
    db.commit()
    db.refresh(row)
    return assignment.rule_dict(row)


@router.delete("/assignment/rules/{rule_id}", status_code=204)
def delete_assignment_rule(rule_id: int, db: Session = Depends(get_db)):
    row = db.get(AssignmentRule, rule_id)
    if row is None:
        raise HTTPException(404, "Assignment rule not found")
    db.delete(row)
    db.add(AuditLog(action="assignment_rule_deleted", details={"name": row.name}))
    db.commit()
    return None


@router.post("/assignment/apply")
def apply_assignment(body: AssignmentApplyIn, db: Session = Depends(get_db)):
    return assignment.apply_rules(
        db, only_unassigned=body.only_unassigned, lead_ids=body.lead_ids
    )


@router.patch("/leads/{lead_id}/assignment")
def assign_lead(lead_id: int, body: ManualAssignmentIn, db: Session = Depends(get_db)):
    lead = _lead(db, lead_id)
    assignment.set_assigned(db, lead, body.assigned_manager)
    db.commit()
    return {"lead_id": lead.id, "assigned_manager": lead.assigned_manager}


@router.get("/automation/rules")
def list_automation_rules(db: Session = Depends(get_db)):
    rows = db.scalars(select(AutomationRule).order_by(AutomationRule.id)).all()
    return [automation.rule_dict(row) for row in rows]


@router.post("/automation/rules", status_code=201)
def create_automation_rule(body: AutomationRuleIn, db: Session = Depends(get_db)):
    if db.scalar(select(AutomationRule).where(AutomationRule.name == body.name)):
        raise HTTPException(409, "An automation rule with that name already exists")
    row = AutomationRule(**body.model_dump())
    db.add(row)
    db.add(AuditLog(action="automation_rule_created", details={"name": row.name}))
    db.commit()
    db.refresh(row)
    return automation.rule_dict(row)


@router.patch("/automation/rules/{rule_id}")
def update_automation_rule(rule_id: int, body: AutomationRulePatch, db: Session = Depends(get_db)):
    row = db.get(AutomationRule, rule_id)
    if row is None:
        raise HTTPException(404, "Automation rule not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.add(AuditLog(action="automation_rule_updated", details={"name": row.name}))
    db.commit()
    db.refresh(row)
    return automation.rule_dict(row)


@router.delete("/automation/rules/{rule_id}", status_code=204)
def delete_automation_rule(rule_id: int, db: Session = Depends(get_db)):
    row = db.get(AutomationRule, rule_id)
    if row is None:
        raise HTTPException(404, "Automation rule not found")
    db.delete(row)
    db.add(AuditLog(action="automation_rule_deleted", details={"name": row.name}))
    db.commit()
    return None


@router.post("/automation/seed-defaults")
def seed_automation(db: Session = Depends(get_db)):
    return {"created": automation.seed_defaults(db)}


@router.post("/automation/run")
def run_automation(db: Session = Depends(get_db)):
    return {"results": automation.run_all(db, trigger="manual")}


@router.get("/automation/logs")
def automation_logs(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(AutomationLog).order_by(AutomationLog.id.desc()).limit(limit)
    ).all()
    return [
        {
            "id": row.id,
            "rule_id": row.rule_id,
            "rule_name": row.rule_name,
            "records_affected": row.records_affected,
            "result": row.result,
            "error_message": row.error_message,
            "details": row.details,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
        }
        for row in rows
    ]


@router.get("/automation/stale-leads")
def stale_leads(days: int = Query(default=14, ge=1, le=365), db: Session = Depends(get_db)):
    return automation.stale_leads(db, days)
