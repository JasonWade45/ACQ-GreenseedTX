"""Reviewed local automation: stale leads, warm leads and dead-lead cleanup.

Rules create *local* follow-ups, tags or a stage change. They never send a message,
dial a number, write to the CRM or change contact permission. Every run is logged with
its counts so the screen can explain what happened.
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import (
    AuditLog,
    AutomationLog,
    AutomationRule,
    Followup,
    Lead,
    LeadTag,
    PipelineStage,
    StageHistory,
)

DEFAULT_RULES = [
    {
        "name": "Stale lead check-in",
        "description": "Create a follow-up when an active lead has not been contacted for 14 days.",
        "rule_type": "stale_lead",
        "config": {
            "days_since_contact": 14,
            "action": "create_followup",
            "followup_delay_days": 1,
            "followup_type": "Call",
        },
        "enabled": True,
    },
    {
        "name": "Warm lead follow-up",
        "description": "Create a same-day follow-up for a lead whose last call was interested or asked for an offer.",
        "rule_type": "hot_lead",
        "config": {"action": "create_followup", "followup_delay_days": 0},
        "enabled": True,
    },
    {
        "name": "Dead lead archive",
        "description": "Move leads with no contact for 90 days to the Dead stage after review.",
        "rule_type": "dead_lead",
        "config": {"days_since_contact": 90, "action": "mark_dead"},
        "enabled": False,
    },
]

CLOSED_STAGES = {"closed", "dead", "under_contract"}
WARM_OUTCOMES = {"Interested", "Wants an Offer"}


def seed_defaults(db: Session) -> int:
    created = 0
    for data in DEFAULT_RULES:
        if db.scalar(select(AutomationRule).where(AutomationRule.name == data["name"])):
            continue
        db.add(
            AutomationRule(
                name=data["name"],
                description=data["description"],
                rule_type=data["rule_type"],
                config=dict(data["config"]),
                enabled=data["enabled"],
            )
        )
        created += 1
    if created:
        db.commit()
    return created


def _cutoff(days: int) -> datetime:
    return utcnow() - timedelta(days=max(1, days))


def _last_touch(lead: Lead) -> Optional[datetime]:
    return lead.last_contact_at or lead.updated_at or lead.created_at


def _pending_followup(db: Session, lead_id: int) -> bool:
    return (
        db.scalar(
            select(Followup).where(
                Followup.lead_id == lead_id,
                Followup.status == "pending",
            )
        )
        is not None
    )


def _create_followup(db: Session, lead: Lead, *, days: int, kind: str, reason: str) -> Followup:
    due_at = utcnow() + timedelta(days=max(0, days))
    followup = Followup(
        lead_id=lead.id,
        due_at=due_at,
        priority=50,
        reason=reason,
        suggested_action=kind,
        status="pending",
        creation_source="automation",
        ai_suggested=False,
    )
    db.add(followup)
    lead.next_followup_at = due_at
    db.flush()
    return followup


def _add_tag(db: Session, lead: Lead, tag: str) -> bool:
    tag = tag.strip()[:60]
    if not tag:
        return False
    if db.scalar(select(LeadTag).where(LeadTag.lead_id == lead.id, LeadTag.tag == tag)):
        return False
    db.add(LeadTag(lead_id=lead.id, tag=tag))
    return True


def _mark_dead(db: Session, lead: Lead, source: str) -> bool:
    if lead.stage_code in CLOSED_STAGES or db.get(PipelineStage, "dead") is None:
        return False
    db.add(
        StageHistory(
            lead_id=lead.id,
            from_stage=lead.stage_code,
            to_stage="dead",
            changed_at=utcnow(),
            source=source,
        )
    )
    lead.stage_code = "dead"
    lead.local_stage_override = True
    return True


def _active(lead: Lead) -> bool:
    return lead.stage_code not in CLOSED_STAGES


def _run_stale(db: Session, rule: AutomationRule) -> dict:
    config = rule.config or {}
    days = int(config.get("days_since_contact", 14))
    action = config.get("action", "create_followup")
    cutoff = _cutoff(days)
    affected, details = 0, []
    for lead in db.scalars(select(Lead).where(Lead.stage_code.notin_(CLOSED_STAGES))).all():
        touched = _last_touch(lead)
        if touched is None or touched >= cutoff:
            continue
        if action == "create_followup":
            if _pending_followup(db, lead.id):
                continue
            _create_followup(
                db,
                lead,
                days=int(config.get("followup_delay_days", 1)),
                kind=str(config.get("followup_type", "Call")),
                reason=f"No contact for {days}+ days — re-engage",
            )
        elif action == "add_tag":
            if not _add_tag(db, lead, str(config.get("tag", "stale"))):
                continue
        else:
            continue
        affected += 1
        details.append({"lead_id": lead.id, "action": action})
    return {"affected": affected, "details": details[:50]}


def _run_hot(db: Session, rule: AutomationRule) -> dict:
    config = rule.config or {}
    affected, details = 0, []
    for lead in db.scalars(
        select(Lead).where(Lead.contact_outcome.in_(WARM_OUTCOMES))
    ).all():
        if not _active(lead) or _pending_followup(db, lead.id):
            continue
        _create_followup(
            db,
            lead,
            days=int(config.get("followup_delay_days", 0)),
            kind=str(config.get("followup_type", "Call")),
            reason="Last call was warm — keep the next step today",
        )
        affected += 1
        details.append({"lead_id": lead.id, "action": "create_followup"})
    return {"affected": affected, "details": details[:50]}


def _run_dead(db: Session, rule: AutomationRule) -> dict:
    config = rule.config or {}
    days = int(config.get("days_since_contact", 90))
    cutoff = _cutoff(days)
    affected, details = 0, []
    for lead in db.scalars(select(Lead).where(Lead.stage_code.notin_(CLOSED_STAGES))).all():
        touched = _last_touch(lead)
        if touched is None or touched >= cutoff:
            continue
        if config.get("action", "mark_dead") == "mark_dead":
            if not _mark_dead(db, lead, "automation"):
                continue
        elif not _add_tag(db, lead, str(config.get("tag", "archive"))):
            continue
        affected += 1
        details.append({"lead_id": lead.id, "action": config.get("action", "mark_dead")})
    return {"affected": affected, "details": details[:50]}


def run_rule(db: Session, rule: AutomationRule) -> dict:
    if rule.rule_type == "stale_lead":
        result = _run_stale(db, rule)
    elif rule.rule_type == "hot_lead":
        result = _run_hot(db, rule)
    elif rule.rule_type == "dead_lead":
        result = _run_dead(db, rule)
    else:
        return {"success": False, "affected": 0, "error": f"Unknown rule type: {rule.rule_type}"}
    return {"success": True, **result}


def run_all(db: Session, *, trigger: str = "manual") -> list[dict]:
    rules = db.scalars(
        select(AutomationRule).where(AutomationRule.enabled.is_(True)).order_by(AutomationRule.id)
    ).all()
    results = []
    for rule in rules:
        started = utcnow()
        try:
            outcome = run_rule(db, rule)
            db.commit()
            state = "success" if outcome.get("success") else "failed"
            error = outcome.get("error")
        except Exception as exc:  # one broken rule must not stop the rest
            db.rollback()
            outcome = {"affected": 0, "details": []}
            state, error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        log = AutomationLog(
            rule_id=rule.id,
            rule_name=rule.name,
            records_affected=outcome.get("affected", 0),
            result=state,
            error_message=error,
            details=outcome.get("details", []),
            started_at=started,
            finished_at=utcnow(),
        )
        db.add(log)
        rule.last_run_at = utcnow()
        rule.last_run_result = (
            f"Success: {outcome.get('affected', 0)} affected"
            if state == "success"
            else f"Failed: {error}"
        )
        db.add(
            AuditLog(
                action="automation_run",
                details={
                    "rule": rule.name,
                    "trigger": trigger,
                    "affected": outcome.get("affected", 0),
                    "state": state,
                },
            )
        )
        db.commit()
        results.append(
            {
                "rule_id": rule.id,
                "rule_name": rule.name,
                "affected": outcome.get("affected", 0),
                "state": state,
                "error": error,
            }
        )
    return results


def stale_leads(db: Session, days: int = 14) -> list[dict]:
    cutoff = _cutoff(days)
    rows = []
    for lead in db.scalars(select(Lead).where(Lead.stage_code.notin_(CLOSED_STAGES))).all():
        touched = _last_touch(lead)
        if touched is None or touched >= cutoff:
            continue
        rows.append(
            {
                "lead_id": lead.id,
                "full_name": lead.full_name,
                "stage_code": lead.stage_code,
                "contact_status": lead.contact_status,
                "assigned_manager": lead.assigned_manager,
                "last_contact_at": lead.last_contact_at,
                "days_since_contact": (utcnow() - touched).days,
                "has_pending_followup": _pending_followup(db, lead.id),
            }
        )
    rows.sort(key=lambda row: row["days_since_contact"], reverse=True)
    return rows


def rule_dict(rule: AutomationRule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "description": rule.description,
        "rule_type": rule.rule_type,
        "config": rule.config or {},
        "enabled": rule.enabled,
        "last_run_at": rule.last_run_at,
        "last_run_result": rule.last_run_result,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }
