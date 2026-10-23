"""Database-backed dashboard metrics.

Every metric returns its count plus a `filter` payload that the UI uses to open
the corresponding filtered lead list. Nothing here is hardcoded.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Activity, Appointment, Followup, Lead
from app.services.pipeline import CONTACT_OUTCOMES, STAGE_ORDER, STAGES, local_today, today_bounds
from app.services.querying import apply_filters, base_query
from app.services.settings_service import followup_rules
from app.services.sync_service import sync_state


def _count(db: Session, params: dict[str, Any], tz: str) -> int:
    return apply_filters(base_query(db), params, tz).count()


def _metric(db: Session, key: str, label: str, params: dict[str, Any], tz: str, **extra: Any) -> dict[str, Any]:
    data = {"key": key, "label": label, "count": _count(db, params, tz), "filter": params, **extra}
    return data


def dashboard_metrics(db: Session, tz: Optional[str] = None) -> dict[str, Any]:
    from app.config import settings

    tz = tz or settings.timezone
    rules = followup_rules(db)
    day_start, day_end = today_bounds(tz)
    today = local_today(tz)

    stage_metrics = []
    for key in STAGE_ORDER:
        stage_metrics.append(
            _metric(
                db,
                f"stage_{key}",
                STAGES[key]["label"],
                {"stage": key},
                tz,
                color=STAGES[key]["color"],
                stage=key,
            )
        )

    contact_metrics = []
    for key, meta in CONTACT_OUTCOMES.items():
        contact_metrics.append(
            _metric(db, f"contact_{key}", meta["label"], {"contact_status": key}, tz, is_contact=meta["is_contact"])
        )

    lead_total = db.query(Lead).count()
    never_contacted = db.query(Lead).filter(Lead.contact_status == "never_contacted").count()
    contacted = (
        db.query(Lead)
        .filter(Lead.contact_status.in_([k for k, v in CONTACT_OUTCOMES.items() if v["is_contact"]]))
        .count()
    )

    overdue = (
        db.query(Lead)
        .filter(Lead.next_followup_at.isnot(None), Lead.next_followup_at < day_start)
        .count()
    )
    due_today = (
        db.query(Lead)
        .filter(Lead.next_followup_at >= day_start, Lead.next_followup_at < day_end)
        .count()
    )
    upcoming_days = int(rules.get("upcoming_lookahead_days", 14))
    upcoming = (
        db.query(Lead)
        .filter(Lead.next_followup_at >= day_end, Lead.next_followup_at <= day_end + timedelta(days=upcoming_days))
        .count()
    )
    unscheduled_stages = rules.get("unscheduled_stage_keys") or []
    unscheduled = (
        db.query(Lead)
        .filter(Lead.pipeline_stage.in_(unscheduled_stages), Lead.next_followup_at.is_(None))
        .count()
        if unscheduled_stages
        else 0
    )

    open_followups = db.query(Followup).filter(Followup.status == "open").count()
    completed_followups = db.query(Followup).filter(Followup.status == "completed").count()
    cancelled_followups = db.query(Followup).filter(Followup.status == "cancelled").count()
    followup_den = open_followups + completed_followups + cancelled_followups
    followup_completion_rate = round(completed_followups / followup_den, 4) if followup_den else None

    appointments_upcoming = (
        db.query(Appointment)
        .filter(Appointment.scheduled_at >= datetime.utcnow(), Appointment.status.in_(["scheduled", "kept"]))
        .count()
    )
    appointments_today = (
        db.query(Appointment)
        .filter(Appointment.scheduled_at >= day_start, Appointment.scheduled_at < day_end)
        .count()
    )
    appointments_past = db.query(Appointment).filter(Appointment.scheduled_at < datetime.utcnow()).count()
    appointments_kept = db.query(Appointment).filter(Appointment.status == "kept").count()
    appointment_rate = round(appointments_kept / appointments_past, 4) if appointments_past else None

    offers = db.query(Lead).filter(Lead.pipeline_stage == "offer_made").count()
    negotiations = db.query(Lead).filter(Lead.pipeline_stage == "negotiation").count()
    under_contract = db.query(Lead).filter(Lead.pipeline_stage == "under_contract").count()
    closed = db.query(Lead).filter(Lead.pipeline_stage == "closed").count()
    qualified = db.query(Lead).filter(Lead.pipeline_stage == "qualified").count()
    offer_rate_all = round(offers / lead_total, 4) if lead_total else None
    offer_rate_qualified = round(offers / qualified, 4) if qualified else None
    contract_rate_all = round(under_contract / lead_total, 4) if lead_total else None
    closing_rate_contract = round(closed / under_contract, 4) if under_contract else None

    # Aging: active deals with no activity in N days
    aging_threshold = int(rules.get("negotiation_attention_days", 2))
    no_recent_cutoff = datetime.utcnow() - timedelta(days=max(7, aging_threshold * 3))
    leads_without_recent = (
        db.query(Lead)
        .filter(Lead.pipeline_stage.in_(rules.get("aging_stage_keys") or []), Lead.updated_at < no_recent_cutoff)
        .count()
    )

    missing_critical = (
        db.query(Lead)
        .filter((Lead.phone_normalized.is_(None)) | (Lead.primary_phone.is_(None)))
        .count()
    )
    missing_any = (
        db.query(Lead)
        .filter(
            (Lead.phone_normalized.is_(None))
            | (Lead.email_normalized.is_(None))
            | (Lead.lead_source.is_(None))
        )
        .count()
    )

    recent_activities = (
        db.query(Activity)
        .filter(Activity.lead_id.isnot(None))
        .order_by(Activity.occurred_at.desc())
        .limit(12)
        .all()
    )
    recent = []
    for a in recent_activities:
        lead = db.get(Lead, a.lead_id)
        recent.append(
            {
                "id": a.id,
                "lead_id": a.lead_id,
                "lead_name": lead.display_name if lead else None,
                "activity_type": a.activity_type,
                "outcome": a.outcome,
                "summary": a.summary,
                "source": a.source,
                "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
            }
        )

    def breakdown(column, label_key: str) -> list[dict[str, Any]]:
        rows = (
            db.query(column, func.count(Lead.id))
            .filter(column.isnot(None))
            .group_by(column)
            .order_by(func.count(Lead.id).desc())
            .limit(25)
            .all()
        )
        return [{"value": r[0], "count": r[1], "filter": {label_key: r[0]}} for r in rows]

    state_rows = _state_breakdown(db)

    sync = sync_state(db)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "timezone": tz,
        "today": today.isoformat(),
        "total_leads": lead_total,
        "empty": lead_total == 0,
        "tiles": {
            "total_leads": {"label": "Total leads", "count": lead_total, "filter": {}},
            "new_leads": {"label": "New", "count": db.query(Lead).filter(Lead.pipeline_stage == "new").count(), "filter": {"stage": "new"}},
            "not_contacted": {"label": "Not contacted", "count": db.query(Lead).filter(Lead.contact_status == "never_contacted").count(), "filter": {"never_contacted": True}},
            "attempting_contact": {"label": "Attempting contact", "count": db.query(Lead).filter(Lead.pipeline_stage == "attempting_contact").count(), "filter": {"stage": "attempting_contact"}},
            "contacted": {"label": "Contacted", "count": contacted, "filter": {}},
            "qualified": {"label": "Qualified", "count": qualified, "filter": {"stage": "qualified"}},
            "followups_due_today": {"label": "Follow-ups due today", "count": due_today, "filter": {"followup_state": "due_today"}},
            "overdue_followups": {"label": "Overdue follow-ups", "count": overdue, "filter": {"followup_state": "overdue"}},
            "upcoming_followups": {"label": "Upcoming follow-ups", "count": upcoming, "filter": {"followup_state": "upcoming"}},
            "unscheduled": {"label": "Unscheduled follow-ups", "count": unscheduled, "filter": {"followup_state": "unscheduled"}},
            "appointments_scheduled": {"label": "Appointments scheduled", "count": appointments_upcoming, "filter": {}},
            "appointments_today": {"label": "Appointments today", "count": appointments_today, "filter": {}},
            "offers_made": {"label": "Offers made", "count": offers, "filter": {"stage": "offer_made"}},
            "negotiations": {"label": "Negotiations", "count": negotiations, "filter": {"stage": "negotiation"}},
            "under_contract": {"label": "Under contract", "count": under_contract, "filter": {"stage": "under_contract"}},
            "closed": {"label": "Closed", "count": closed, "filter": {"stage": "closed"}},
            "nurture": {"label": "Nurture", "count": db.query(Lead).filter(Lead.pipeline_stage == "nurture").count(), "filter": {"stage": "nurture"}},
            "disqualified": {"label": "Dead / disqualified", "count": db.query(Lead).filter(Lead.pipeline_stage == "dead").count(), "filter": {"stage": "dead"}},
            "missing_critical": {"label": "Missing critical info", "count": missing_critical, "filter": {"missing": "critical"}},
            "missing_any": {"label": "Missing any info", "count": missing_any, "filter": {"missing": "any"}},
            "never_contacted_tile": {"label": "Never contacted", "count": never_contacted, "filter": {"never_contacted": True}},
            "leads_without_recent_activity": {"label": "No recent activity", "count": leads_without_recent, "filter": {}},
        },
        "stages": stage_metrics,
        "contact_statuses": contact_metrics,
        "followups": {
            "open": open_followups,
            "due_today": due_today,
            "overdue": overdue,
            "upcoming": upcoming,
            "unscheduled": unscheduled,
            "completed": completed_followups,
            "cancelled": cancelled_followups,
            "completion_rate": followup_completion_rate,
            "completion_rate_denominator": followup_den,
        },
        "appointments": {
            "upcoming": appointments_upcoming,
            "today": appointments_today,
            "past": appointments_past,
            "kept": appointments_kept,
            "kept_rate": appointment_rate,
            "kept_rate_denominator": appointments_past,
        },
        "pipeline": {
            "offers": offers,
            "negotiations": negotiations,
            "qualified": qualified,
            "under_contract": under_contract,
            "closed": closed,
            "offer_rate_of_all_leads": offer_rate_all,
            "offer_rate_of_qualified": offer_rate_qualified,
            "offer_rate_denominators": {"all_leads": lead_total, "qualified": qualified},
            "contract_rate_of_all_leads": contract_rate_all,
            "closing_rate_of_under_contract": closing_rate_contract,
            "closing_rate_denominator": under_contract,
        },
        "breakdowns": {
            "by_source": breakdown(Lead.lead_source, "source"),
            "by_manager": breakdown(Lead.assigned_manager, "manager"),
            "by_state": state_rows,
        },
        "recent_activity": recent,
        "sync": {
            "health": sync["health"],
            "last_success": sync["last_success"],
            "mock_mode": sync["mock_mode"],
            "data_is_live": sync["data_is_live"],
            "api_key_configured": sync["api_key_configured"],
        },
        "ai": _ai_availability(),
    }


def _state_breakdown(db: Session) -> list[dict[str, Any]]:
    from app.models import LeadProperty, Property

    rows = (
        db.query(Property.state, func.count(func.distinct(Lead.id)))
        .select_from(Lead)
        .join(LeadProperty, LeadProperty.lead_id == Lead.id)
        .join(Property, Property.id == LeadProperty.property_id)
        .filter(Property.state.isnot(None))
        .group_by(Property.state)
        .order_by(func.count(func.distinct(Lead.id)).desc())
        .limit(25)
        .all()
    )
    return [{"value": r[0], "count": r[1], "filter": {"state": r[0]}} for r in rows]


def _ai_availability() -> dict[str, Any]:
    from app.services.ai_service import ai_status

    return ai_status()
