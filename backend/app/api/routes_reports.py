"""Reports: conversion funnel, aging, volume and exportable series."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Activity, Appointment, Followup, Lead
from app.services.export import export_filename, rows_to_csv
from app.services.pipeline import CONTACT_OUTCOMES, STAGES
from app.services.workqueue import completion_denominator

router = APIRouter(tags=["reports"])


@router.get("/reports/summary")
def summary(db: Session = Depends(get_db)):
    total = db.query(Lead).count()
    stage_counts = dict(db.query(Lead.pipeline_stage, func.count(Lead.id)).group_by(Lead.pipeline_stage).all())

    def rate(numerator: int, denominator: int) -> Optional[float]:
        return round(numerator / denominator, 4) if denominator else None

    qualified = stage_counts.get("qualified", 0)
    appointment_set = stage_counts.get("appointment_set", 0)
    offers = stage_counts.get("offer_made", 0) + stage_counts.get("negotiation", 0)
    under_contract = stage_counts.get("under_contract", 0) + stage_counts.get("contract_sent", 0)
    closed = stage_counts.get("closed", 0)

    never_contacted = db.query(Lead).filter(Lead.contact_status == "never_contacted").count()
    # "Contacted" must match the stated definition below (connected-type
    # statuses). `total - never_contacted` would count DNC and no-answer-only
    # leads as contacted, which inflates the funnel.
    contacted = (
        db.query(Lead)
        .filter(Lead.contact_status.in_([k for k, v in CONTACT_OUTCOMES.items() if v["is_contact"]]))
        .count()
    )
    contact_attempt_leads = (
        db.query(Lead.id)
        .join(Activity, Activity.lead_id == Lead.id)
        .filter(Activity.activity_type.in_(["call", "text", "email"]))
        .distinct()
        .count()
    )

    followup = completion_denominator(db)

    appointments_total = db.query(Appointment).count()
    appointments_kept = db.query(Appointment).filter(Appointment.status == "kept").count()

    aging_rules = ["new", "not_contacted", "attempting_contact", "contacted", "qualified", "follow_up", "appointment_set", "offer_made", "negotiation", "contract_sent", "under_contract"]
    aging_rows: list[dict[str, Any]] = []
    for stage in aging_rules:
        leads = db.query(Lead).filter(Lead.pipeline_stage == stage).all()
        if not leads:
            aging_rows.append({"stage": stage, "label": STAGES[stage]["label"], "count": 0, "avg_age_days": None, "median_age_days": None})
            continue
        ages = sorted((datetime.utcnow() - (lead.created_at or datetime.utcnow())).days for lead in leads)
        aging_rows.append(
            {
                "stage": stage,
                "label": STAGES[stage]["label"],
                "count": len(ages),
                "avg_age_days": round(sum(ages) / len(ages), 1),
                "median_age_days": ages[len(ages) // 2],
                "max_age_days": ages[-1],
            }
        )

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "totals": {
            "leads": total,
            "never_contacted": never_contacted,
            "contacted": contacted,
            "contact_attempt_leads": contact_attempt_leads,
            "stages": {k: {"label": STAGES[k]["label"], "count": v} for k, v in stage_counts.items()},
        },
        "conversion": {
            "contact_rate": rate(contacted, total),
            "contact_rate_definition": "leads with a connected-type contact status / all leads",
            "contact_attempt_rate": rate(contact_attempt_leads, total),
            "contact_attempt_rate_definition": "leads with at least one call/text/email activity / all leads",
            "qualification_rate": rate(qualified, contacted if contacted else 0),
            "qualification_rate_definition": "qualified leads / contacted leads",
            "appointment_rate": rate(appointment_set, qualified if qualified else 0),
            "appointment_rate_definition": "appointment-set leads / qualified leads",
            "offer_rate_of_qualified": rate(offers, qualified if qualified else 0),
            "offer_rate_of_all": rate(offers, total),
            "offer_rate_definition": "offer_made + negotiation leads, shown against both denominators",
            "contract_rate_of_offers": rate(under_contract, offers if offers else 0),
            "contract_rate_of_all": rate(under_contract, total),
            "closing_rate_of_contract": rate(closed, under_contract if under_contract else 0),
            "closing_rate_of_all": rate(closed, total),
            "denominators": {
                "all_leads": total,
                "contacted": contacted,
                "qualified": qualified,
                "offers": offers,
                "under_contract": under_contract,
            },
        },
        "followups": followup,
        "appointments": {
            "total": appointments_total,
            "kept": appointments_kept,
            "kept_rate": rate(appointments_kept, appointments_total),
            "kept_rate_denominator": appointments_total,
        },
        "aging": aging_rows,
        "unavailable_metrics": [
            "Revenue / assignment fee per contract — no offer or contract value fields are available from the REsimpli Open API at launch.",
            "Source-level ROI — cost per lead is not available.",
        ],
    }


@router.get("/reports/lead-volume")
def lead_volume(days: int = 90, db: Session = Depends(get_db)):
    start = (datetime.utcnow() - timedelta(days=days)).date()
    rows = (
        db.query(Lead.original_creation_date, func.count(Lead.id))
        .filter(Lead.original_creation_date.isnot(None), Lead.original_creation_date >= start)
        .group_by(Lead.original_creation_date)
        .order_by(Lead.original_creation_date)
        .all()
    )
    by_date = {r[0].isoformat(): r[1] for r in rows}
    local_rows = (
        db.query(func.date(Lead.created_at), func.count(Lead.id))
        .filter(Lead.created_at >= datetime(start.year, start.month, start.day))
        .group_by(func.date(Lead.created_at))
        .order_by(func.date(Lead.created_at))
        .all()
    )
    return {
        "days": days,
        "by_original_creation_date": [{"date": k, "count": v} for k, v in by_date.items()],
        "by_local_created_at": [{"date": str(k), "count": v} for k, v in local_rows],
        "note": "original_creation_date comes from REsimpli/import; local_created_at is when the row first entered this app.",
    }


@router.get("/reports/export/csv")
def export_report(kind: str = "leads", db: Session = Depends(get_db)):
    if kind == "aging":
        leads = db.query(Lead).all()
        headers = ["lead_id", "name", "stage", "created_at", "age_days", "last_contact_at", "next_followup_at", "source"]
        rows = []
        for lead in leads:
            age = (datetime.utcnow() - (lead.created_at or datetime.utcnow())).days
            rows.append([
                lead.id, lead.display_name, lead.pipeline_stage, lead.created_at.isoformat() if lead.created_at else "",
                age, lead.last_contact_at.isoformat() if lead.last_contact_at else "",
                lead.next_followup_at.isoformat() if lead.next_followup_at else "", lead.lead_source,
            ])
    elif kind == "followups":
        rows_f = db.query(Followup).order_by(Followup.due_at.desc()).limit(5000).all()
        headers = ["followup_id", "lead_id", "due_at", "priority", "status", "reason", "outcome", "completed_at", "source"]
        rows = [
            [
                f.id, f.lead_id, f.due_at.isoformat() if f.due_at else "", f.priority, f.status,
                f.reason, f.completion_outcome, f.completed_at.isoformat() if f.completed_at else "", f.creation_source,
            ]
            for f in rows_f
        ]
    elif kind == "activities":
        acts = db.query(Activity).order_by(Activity.occurred_at.desc()).limit(5000).all()
        headers = ["activity_id", "lead_id", "type", "direction", "outcome", "occurred_at", "source", "summary"]
        rows = [
            [a.id, a.lead_id, a.activity_type, a.direction, a.outcome,
             a.occurred_at.isoformat() if a.occurred_at else "", a.source, a.summary]
            for a in acts
        ]
    else:
        leads = db.query(Lead).limit(5000).all()
        headers = ["lead_id", "resimpli_id", "name", "phone", "email", "stage", "contact_status", "source", "manager", "created", "next_followup", "do_not_contact"]
        rows = [
            [lead.id, lead.external_id, lead.display_name, lead.primary_phone, lead.email, lead.pipeline_stage,
             lead.contact_status, lead.lead_source, lead.assigned_manager,
             lead.created_at.isoformat() if lead.created_at else "",
             lead.next_followup_at.isoformat() if lead.next_followup_at else "",
             "yes" if lead.do_not_contact else "no"]
            for lead in leads
        ]
    body = rows_to_csv(headers, rows)
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{export_filename("report_" + kind)}"'},
    )


@router.get("/reports/by-source")
def by_source(db: Session = Depends(get_db)):
    rows = (
        db.query(Lead.lead_source, func.count(Lead.id))
        .filter(Lead.lead_source.isnot(None))
        .group_by(Lead.lead_source)
        .all()
    )
    total = sum(r[1] for r in rows)
    out = []
    for source, count in sorted(rows, key=lambda r: -r[1]):
        stage_split = dict(
            db.query(Lead.pipeline_stage, func.count(Lead.id))
            .filter(Lead.lead_source == source)
            .group_by(Lead.pipeline_stage)
            .all()
        )
        out.append(
            {
                "source": source,
                "count": count,
                "share": round(count / total, 4) if total else None,
                "share_denominator": total,
                "stages": {k: v for k, v in stage_split.items()},
                "closed": stage_split.get("closed", 0),
                "closed_rate": round(stage_split.get("closed", 0) / count, 4) if count else None,
            }
        )
    return {"items": out, "total": total}
