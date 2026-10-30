"""State/city desk assignment, with a visible reason for every decision.

Assignment only fills ``leads.assigned_manager``. It never changes a stage, a
restriction or contact permission, and it never contacts anyone.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import AssignmentRule, AuditLog, Lead


def _matches(rule: AssignmentRule, lead: Lead) -> bool:
    if rule.is_fallback:
        return True
    if not lead.properties:
        return False
    prop = lead.properties[0]
    if rule.state and (prop.state or "").strip().upper() != rule.state.strip().upper():
        return False
    if rule.city and (prop.city or "").strip().lower() != rule.city.strip().lower():
        return False
    return bool(rule.state or rule.city)


def match_rule(db: Session, lead: Lead) -> Optional[AssignmentRule]:
    """First enabled rule by priority wins; a fallback rule is only the last resort."""
    rules = db.scalars(
        select(AssignmentRule)
        .where(AssignmentRule.enabled.is_(True))
        .order_by(AssignmentRule.priority.asc(), AssignmentRule.id.asc())
    ).all()
    fallback = None
    for rule in rules:
        if rule.is_fallback:
            fallback = fallback or rule
            continue
        if _matches(rule, lead):
            return rule
    return fallback


def apply_to_lead(db: Session, lead: Lead, *, only_unassigned: bool = False) -> Optional[AssignmentRule]:
    if only_unassigned and (lead.assigned_manager or "").strip():
        return None
    rule = match_rule(db, lead)
    if rule is None:
        return None
    previous = lead.assigned_manager
    if previous == rule.target_assignee:
        return rule
    lead.assigned_manager = rule.target_assignee
    db.add(
        AuditLog(
            lead_id=lead.id,
            action="lead_assigned",
            details={
                "from": previous,
                "to": rule.target_assignee,
                "rule": rule.name,
                "match": "fallback" if rule.is_fallback else {"state": rule.state, "city": rule.city},
            },
        )
    )
    return rule


def apply_rules(db: Session, *, only_unassigned: bool = False, lead_ids: Optional[list[int]] = None) -> dict:
    statement = select(Lead)
    if lead_ids:
        statement = statement.where(Lead.id.in_(lead_ids))
    if only_unassigned:
        statement = statement.where(
            (Lead.assigned_manager.is_(None)) | (Lead.assigned_manager == "")
        )
    leads = db.scalars(statement).all()
    assigned = 0
    unmatched = 0
    for lead in leads:
        rule = apply_to_lead(db, lead, only_unassigned=only_unassigned)
        if rule is None:
            unmatched += 1
        else:
            assigned += 1
    db.commit()
    return {"ok": True, "considered": len(leads), "assigned": assigned, "unmatched": unmatched}


def rule_dict(rule: AssignmentRule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "priority": rule.priority,
        "enabled": rule.enabled,
        "is_fallback": rule.is_fallback,
        "state": rule.state,
        "city": rule.city,
        "target_assignee": rule.target_assignee,
        "notes": rule.notes,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


def set_assigned(db: Session, lead: Lead, assignee: str) -> None:
    previous = lead.assigned_manager
    lead.assigned_manager = assignee.strip() or None
    db.add(
        AuditLog(
            lead_id=lead.id,
            action="lead_assigned_manual",
            details={"from": previous, "to": lead.assigned_manager, "at": utcnow().isoformat()},
        )
    )
