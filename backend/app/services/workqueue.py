"""Daily follow-up work queue.

Rules are configurable via the `followup_rules` setting. Nothing in here
contacts a seller — it only tells the user what to do next.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Appointment, Followup, Lead
from app.services.leads import missing_fields, primary_property
from app.services.pipeline import local_today, today_bounds
from app.services.settings_service import followup_rules


def _base_task(lead: Lead, *, reason: str, action: str, priority: int, confidence: str, evidence: list[str]) -> dict[str, Any]:
    prop = primary_property(lead)
    last_activity = lead.activities[0] if lead.activities else None
    return {
        "lead_id": lead.id,
        "external_id": lead.external_id,
        "seller_name": lead.display_name,
        "phone": lead.primary_phone,
        "email": lead.email,
        "property_address": prop.formatted_address if prop else None,
        "stage": lead.pipeline_stage,
        "source_status": lead.source_status,
        "contact_status": lead.contact_status,
        "last_contact_at": lead.last_contact_at.isoformat() if lead.last_contact_at else None,
        "last_activity_summary": last_activity.summary if last_activity else None,
        "last_activity_at": last_activity.occurred_at.isoformat() if last_activity else None,
        "next_followup_at": lead.next_followup_at.isoformat() if lead.next_followup_at else None,
        "do_not_contact": lead.do_not_contact,
        "reason": reason,
        "suggested_next_action": action,
        "priority": priority,
        "confidence": confidence,
        "evidence": evidence,
        "missing_fields": [m["label"] for m in missing_fields(lead)],
    }


def build_work_queue(db: Session, tz: Optional[str] = None) -> dict[str, Any]:
    tz = tz or settings.timezone
    rules = followup_rules(db)
    day_start, day_end = today_bounds(tz)
    now = datetime.utcnow()
    today = local_today(tz)

    sections: dict[str, list[dict[str, Any]]] = {
        "overdue": [],
        "due_today": [],
        "new_not_contacted": [],
        "callbacks_requested": [],
        "appointments_today": [],
        "offers_awaiting_response": [],
        "negotiations_requiring_attention": [],
        "upcoming": [],
        "unscheduled": [],
        "missing_critical": [],
    }

    open_followups = (
        db.query(Followup)
        .join(Lead, Lead.id == Followup.lead_id)
        .filter(Followup.status == "open")
        .all()
    )
    lead_ids = {f.lead_id for f in open_followups}
    leads_by_id: dict[str, Lead] = {}
    for lead_id in lead_ids:
        lead = db.get(Lead, lead_id)
        if lead:
            leads_by_id[lead_id] = lead

    # --- Overdue / due today / upcoming ----------------------------------- #
    for fu in open_followups:
        lead = leads_by_id.get(fu.lead_id)
        if not lead or lead.do_not_contact:
            continue
        if fu.due_at < day_start:
            lateness = (day_start.date() - fu.due_at.date()).days
            priority = min(5, max(int(rules.get("overdue_priority", 4)), 3 + lateness))
            sections["overdue"].append(
                _base_task(
                    lead,
                    reason=f"Follow-up overdue by {lateness} day(s) — {fu.reason or 'scheduled follow-up'}",
                    action=fu.suggested_next_action or "Call the seller and record the outcome",
                    priority=priority,
                    confidence="high",
                    evidence=[f"Open follow-up {fu.id} due {fu.due_at.isoformat()}"],
                )
            )
        elif day_start <= fu.due_at < day_end:
            sections["due_today"].append(
                _base_task(
                    lead,
                    reason=f"Follow-up due today — {fu.reason or 'scheduled follow-up'}",
                    action=fu.suggested_next_action or "Call or text the seller per company workflow",
                    priority=int(rules.get("default_priority", 3)),
                    confidence="high",
                    evidence=[f"Open follow-up {fu.id} due today"],
                )
            )
        elif day_end <= fu.due_at <= day_end + timedelta(days=int(rules.get("upcoming_lookahead_days", 14))):
            sections["upcoming"].append(
                _base_task(
                    lead,
                    reason=f"Follow-up scheduled — {fu.reason or 'follow-up'}",
                    action=fu.suggested_next_action or "Prepare before the due time",
                    priority=max(1, int(rules.get("default_priority", 3)) - 1),
                    confidence="high",
                    evidence=[f"Open follow-up {fu.id} due {fu.due_at.date().isoformat()}"],
                )
            )

    # --- Callbacks requested ---------------------------------------------- #
    callback_leads = (
        db.query(Lead)
        .filter(Lead.contact_status == "callback_requested", Lead.do_not_contact.is_(False))
        .order_by(Lead.last_contact_at.desc().nullslast())
        .limit(100)
        .all()
    )
    for lead in callback_leads:
        sections["callbacks_requested"].append(
            _base_task(
                lead,
                reason="Seller requested a callback",
                action="Call back at the time they asked for",
                priority=int(rules.get("callback_priority", 5)),
                confidence="high",
                evidence=[f"Contact status = callback_requested (last contact {lead.last_contact_at})"],
            )
        )

    # --- New leads never contacted ---------------------------------------- #
    grace = timedelta(hours=int(rules.get("new_lead_grace_hours", 4)))
    cutoff = now - grace
    new_leads = (
        db.query(Lead)
        .filter(
            Lead.contact_status == "never_contacted",
            Lead.do_not_contact.is_(False),
            Lead.pipeline_stage.in_(["new", "not_contacted"]),
        )
        .order_by(Lead.created_at.asc())
        .limit(200)
        .all()
    )
    for lead in new_leads:
        attempted = any(a.activity_type in {"call", "text", "email"} for a in lead.activities)
        if attempted:
            continue
        evidence = ["No call/text/email activity recorded on this lead"]
        if lead.created_at and lead.created_at < cutoff:
            sections["new_not_contacted"].append(
                _base_task(
                    lead,
                    reason="New lead with no contact attempt yet",
                    action="Make the first outreach attempt",
                    priority=int(rules.get("new_lead_priority", 3)),
                    confidence="high",
                    evidence=evidence,
                )
            )

    # --- Appointments today ------------------------------------------------ #
    appts_today = (
        db.query(Appointment)
        .join(Lead, Lead.id == Appointment.lead_id)
        .filter(Appointment.scheduled_at >= day_start, Appointment.scheduled_at < day_end)
        .all()
    )
    for appt in appts_today:
        lead = db.get(Lead, appt.lead_id) if appt.lead_id else None
        if not lead:
            continue
        sections["appointments_today"].append(
            _base_task(
                lead,
                reason=f"Appointment today ({appt.appointment_type or 'seller appointment'}) — {appt.status}",
                action="Prepare notes and confirm attendance",
                priority=int(rules.get("appointment_priority", 5)),
                confidence="high",
                evidence=[f"Appointment {appt.external_id or appt.id} at {appt.scheduled_at.isoformat()}"],
            )
        )

    # --- Offers awaiting response ------------------------------------------ #
    offer_days = int(rules.get("offer_response_attention_days", 3))
    offer_leads = db.query(Lead).filter(Lead.pipeline_stage == "offer_made").all()
    for lead in offer_leads:
        stale_since = lead.updated_at or lead.created_at
        age = (now - stale_since).days if stale_since else 0
        if age >= offer_days or lead.next_followup_at and lead.next_followup_at < now:
            sections["offers_awaiting_response"].append(
                _base_task(
                    lead,
                    reason=f"Offer outstanding — {age} day(s) without movement",
                    action="Follow up on the offer and record the seller's response",
                    priority=int(rules.get("offer_priority", 4)),
                    confidence="medium" if age >= offer_days else "high",
                    evidence=[f"Stage = offer_made; last local update {stale_since.isoformat() if stale_since else 'unknown'}"],
                )
            )

    # --- Negotiations requiring attention ---------------------------------- #
    neg_days = int(rules.get("negotiation_attention_days", 2))
    neg_leads = db.query(Lead).filter(Lead.pipeline_stage == "negotiation").all()
    for lead in neg_leads:
        stale_since = lead.updated_at or lead.created_at
        age = (now - stale_since).days if stale_since else 0
        overdue_flag = bool(lead.next_followup_at and lead.next_followup_at < now)
        if age >= neg_days or overdue_flag:
            sections["negotiations_requiring_attention"].append(
                _base_task(
                    lead,
                    reason=f"Active negotiation without movement for {age} day(s)",
                    action="Re-engage the seller and move toward contract",
                    priority=int(rules.get("negotiation_priority", 4)),
                    confidence="medium",
                    evidence=[f"Stage = negotiation; last local update {stale_since.isoformat() if stale_since else 'unknown'}"],
                )
            )

    # --- Unscheduled follow-ups -------------------------------------------- #
    unscheduled_stages = rules.get("unscheduled_stage_keys") or []
    if unscheduled_stages:
        unsched = (
            db.query(Lead)
            .filter(
                Lead.pipeline_stage.in_(unscheduled_stages),
                Lead.next_followup_at.is_(None),
                Lead.do_not_contact.is_(False),
            )
            .limit(200)
            .all()
        )
        for lead in unsched:
            sections["unscheduled"].append(
                _base_task(
                    lead,
                    reason=f"Active stage '{lead.pipeline_stage}' with no scheduled follow-up",
                    action="Schedule the next follow-up so the lead is not forgotten",
                    priority=2,
                    confidence="medium",
                    evidence=[f"Stage = {lead.pipeline_stage}; no open follow-up"],
                )
            )

    # --- Missing critical information --------------------------------------- #
    missing = (
        db.query(Lead)
        .filter(Lead.do_not_contact.is_(False))
        .limit(1000)
        .all()
    )
    for lead in missing:
        crit = [m for m in missing_fields(lead) if m["severity"] == "critical"]
        if crit:
            sections["missing_critical"].append(
                _base_task(
                    lead,
                    reason="Missing critical information: " + ", ".join(m["label"] for m in crit),
                    action="Fill in the missing fields before the next outreach",
                    priority=2,
                    confidence="high",
                    evidence=[f"Missing {m['field']}" for m in crit],
                )
            )

    def sort_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(tasks, key=lambda t: (-t["priority"], t.get("next_followup_at") or "9999"))[:200]

    for key in sections:
        sections[key] = sort_tasks(sections[key])

    total = sum(len(v) for v in sections.values())
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "timezone": tz,
        "today": today.isoformat(),
        "total_tasks": total,
        "sections": [
            {"key": "overdue", "label": "Overdue", "tasks": sections["overdue"]},
            {"key": "due_today", "label": "Due today", "tasks": sections["due_today"]},
            {"key": "new_not_contacted", "label": "New leads not contacted", "tasks": sections["new_not_contacted"]},
            {"key": "callbacks_requested", "label": "Callbacks requested", "tasks": sections["callbacks_requested"]},
            {"key": "appointments_today", "label": "Appointments today", "tasks": sections["appointments_today"]},
            {"key": "offers_awaiting_response", "label": "Offers awaiting response", "tasks": sections["offers_awaiting_response"]},
            {"key": "negotiations_requiring_attention", "label": "Negotiations requiring attention", "tasks": sections["negotiations_requiring_attention"]},
            {"key": "upcoming", "label": "Upcoming", "tasks": sections["upcoming"]},
            {"key": "unscheduled", "label": "Unscheduled follow-ups", "tasks": sections["unscheduled"]},
            {"key": "missing_critical", "label": "Leads missing critical information", "tasks": sections["missing_critical"]},
        ],
        "rules": rules,
    }


def completion_denominator(db: Session) -> dict[str, Any]:
    """Documented denominators for follow-up completion reporting."""
    total = db.query(Followup).count()
    completed = db.query(Followup).filter(Followup.status == "completed").count()
    return {
        "completed": completed,
        "total": total,
        "rate": round(completed / total, 4) if total else None,
        "definition": "completed follow-ups / all follow-ups ever created",
    }
