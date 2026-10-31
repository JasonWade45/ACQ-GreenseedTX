from datetime import timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, func
from ..models import Lead, Activity, Followup, Appointment, AppSetting, AuditLog
from ..db import utcnow
from . import followup_strategy
from .leads import (
    lead_dict,
    activity_dict,
    followup_dict,
    day_bounds,
    outreach_allowed_clause,
    update_next_followup,
    apply_contact_outcome,
)

SECTIONS = [
    "needs_skip_trace",
    "overdue",
    "today",
    "new",
    "callbacks",
    "appointments",
    "offers",
    "negotiations",
    "upcoming",
    "unscheduled",
    "missing",
]
SECTION_LABELS = {
    "needs_skip_trace": "Needs skip trace",
    "overdue": "Overdue",
    "today": "Due Today",
    "new": "New Leads Not Contacted",
    "callbacks": "Callbacks Requested",
    "appointments": "Appointments Today",
    "offers": "Offers Awaiting Response",
    "negotiations": "Negotiations Requiring Attention",
    "upcoming": "Upcoming",
    "unscheduled": "Unscheduled Follow-ups",
    "missing": "Missing Critical Information",
}


def contextual_bonus(lead, rules):
    """Heat, sale likelihood and equity additions, each reported separately.

    These only ever *add* to the existing deterministic score; the same 0-100 cap and
    the DNC exclusion still apply. Nothing here guesses a value: a missing score or
    equity simply contributes nothing.
    """
    total, reasons = 0, []
    heat = (getattr(lead, "heat", None) or "").upper()
    if heat == "VERY_HOT":
        bonus = int(rules.get("heat_very_hot_bonus", 0))
        total += bonus
        reasons.append(f"Very hot lead (+{bonus})")
    elif heat == "HOT":
        bonus = int(rules.get("heat_hot_bonus", 0))
        total += bonus
        reasons.append(f"Hot lead (+{bonus})")
    score = getattr(lead, "score", None)
    weight = int(rules.get("ds_score_weight", 0))
    if score is not None and score >= 50 and weight:
        bonus = round((float(score) - 50) * weight / 50)
        if bonus:
            total += bonus
            reasons.append(f"Sale likelihood {score:g} (+{bonus})")
    equity = getattr(lead, "equity_pct", None)
    if equity is not None:
        if equity >= 40:
            bonus = int(rules.get("equity_bonus", 0))
            if bonus:
                total += bonus
                reasons.append(f"Equity {equity:g}% (+{bonus})")
        elif equity < 20:
            penalty = int(rules.get("negative_equity_penalty", 0))
            if penalty:
                total += penalty
                reasons.append(f"Equity {equity:g}% ({penalty:+d})")
    return total, reasons


def priority_for(lead, followup, rules, start, zone="America/New_York"):
    score = followup.priority if followup else rules["new_lead_priority"]
    reasons = []
    if followup and followup.due_at and followup.due_at < start:
        days = max(
            1, (start.astimezone(ZoneInfo(zone)).date() - followup.due_at.astimezone(ZoneInfo(zone)).date()).days
        )
        bonus = min(40, days * rules["overdue_per_day"])
        score += bonus
        reasons.append(f"{days} calendar day(s) overdue (+{bonus})")
    if lead.contact_outcome == "Callback Requested":
        score += rules["callback_bonus"]
        reasons.append(f"Explicit callback requested (+{rules['callback_bonus']})")
    if lead.stage_code == "negotiation":
        score += rules["negotiation_bonus"]
        reasons.append(f"Active negotiation (+{rules['negotiation_bonus']})")
    if lead.stage_code == "appointment_set":
        score += rules["appointment_bonus"]
        reasons.append(f"Appointment-stage priority (+{rules['appointment_bonus']})")
    contextual, contextual_reasons = contextual_bonus(lead, rules)
    score += contextual
    reasons.extend(contextual_reasons)
    return max(0, min(100, score)), reasons


def daily_queue(db, zone, section=None, page=1, page_size=30):
    start, end = day_bounds(zone)
    rules = db.get(AppSetting, "priority_rules").value
    leads = db.scalars(
        select(Lead).where(
            outreach_allowed_clause(),
            Lead.stage_code.notin_({"dead", "closed", "under_contract"}),
        )
    ).all()
    activities = db.scalars(
        select(Activity).order_by(Activity.occurred_at.desc().nullslast(), Activity.id.desc())
    ).all()
    latest, latest_offer = {}, {}
    for a in activities:
        latest.setdefault(a.lead_id, a)
        if a.activity_type == "offer":
            latest_offer.setdefault(a.lead_id, a.outcome)
    follows = db.scalars(select(Followup).where(Followup.status == "pending")).all()
    completed_counts = dict(
        db.execute(
            select(Followup.lead_id, func.count())
            .where(Followup.status == "completed")
            .group_by(Followup.lead_id)
        ).all()
    )
    message_counts = dict(
        db.execute(
            select(Activity.lead_id, func.count())
            .where(Activity.activity_type == "message")
            .group_by(Activity.lead_id)
        ).all()
    )
    by_lead = {}
    for f in follows:
        by_lead.setdefault(f.lead_id, []).append(f)
    appts = set(
        db.scalars(
            select(Appointment.lead_id).where(
                Appointment.starts_at >= start,
                Appointment.starts_at < end,
                Appointment.status == "scheduled",
                Appointment.local_result.is_(None),
            )
        )
    )
    result = {key: [] for key in SECTIONS}
    for lead in leads:
        payload = lead_dict(lead)
        last = latest.get(lead.id)
        fs = by_lead.get(lead.id, [])

        def item(f=None, reason="", action="Review the lead and confirm the appropriate next step."):
            score, factors = priority_for(lead, f, rules, start, zone)
            if lead.restriction_status == "unknown":
                action = "Review contact permissions before any outreach. " + action
            first = not completed_counts.get(lead.id) and not message_counts.get(lead.id)
            message = followup_strategy.build_message(lead, last, first=first)
            return {
                "lead": payload,
                "followup": followup_dict(f) if f else None,
                "last_activity": activity_dict(last) if last else None,
                "reason": reason,
                "suggested_action": (f.suggested_action if f and f.suggested_action else action),
                "suggested_message": message["text"],
                "message_basis": message["basis"],
                "message_first": message["first_message"],
                "message_channel": message["channel"],
                "conversation": message["conversation"],
                "priority": score,
                "priority_factors": factors,
                "evidence_quality": "Source/user data; deterministic rule",
                "draft_available": lead.restriction_status == "reviewed_clear"
                and bool(last or lead.source_data.get("normalized", {}).get("seller_motivation")),
            }

        # A lead with no verified owner name or phone can be worked on, but only in
        # its own section: it must never appear as a "call this seller" task.
        if lead.needs_skip_trace:
            score, factors = priority_for(lead, None, rules, start, zone)
            result["needs_skip_trace"].append(
                {
                    "lead": payload,
                    "followup": None,
                    "last_activity": activity_dict(last) if last else None,
                    "reason": "No verified owner name or phone yet; export and run a skip trace first.",
                    "suggested_action": "Export the skip-trace file, then import the results.",
                    "priority": score,
                    "priority_factors": factors,
                    "evidence_quality": "Vendor record; owner identity not verified",
                    "draft_available": False,
                }
            )
            continue

        for f in fs:
            if not f.due_at:
                group = "unscheduled"
            elif f.due_at < start:
                group = "overdue"
            elif f.due_at < end:
                group = "today"
            else:
                group = "upcoming"
            result[group].append(item(f, f.reason))
        if lead.contact_status in {"unknown", "not_contacted"} and lead.stage_code in {
            "new",
            "not_contacted",
            "unmapped",
        }:
            result["new"].append(
                item(
                    reason="No verified contact or contact attempt is recorded.",
                    action="Review the source lead and verify contact eligibility.",
                )
            )
        if lead.contact_outcome == "Callback Requested":
            result["callbacks"].append(
                item(
                    fs[0] if fs else None,
                    "An explicit callback outcome is recorded. No date is inferred if one is missing.",
                    "Review the callback request and confirm a date.",
                )
            )
        if lead.id in appts:
            result["appointments"].append(
                item(
                    reason="A scheduled appointment falls on today’s business calendar.",
                    action="Review the appointment details and preparation notes.",
                )
            )
        if lead.stage_code == "offer_made" and latest_offer.get(lead.id) not in {"Offer Accepted", "Offer Rejected"}:
            result["offers"].append(
                item(
                    reason="Lead is in Offer Made. Awaiting-response inference needs human review.",
                    action="Review the actual offer and response history; confirm whether a response is outstanding.",
                )
            )
        if lead.stage_code == "negotiation":
            result["negotiations"].append(
                item(
                    reason="Lead is in Negotiation; no overdue date is inferred.",
                    action="Review recorded terms and determine the next negotiation step.",
                )
            )
        critical = [
            x
            for x in payload["missing_information"]
            if x not in {"Email address (optional)", "Verified contact history"}
        ]
        if critical:
            result["missing"].append(
                item(
                    reason="Missing: " + ", ".join(critical),
                    action="Verify missing fields against source records; do not invent values.",
                )
            )
    for key, items in result.items():
        if key == "needs_skip_trace":
            items.sort(
                key=lambda x: (
                    -(x["priority"]),
                    -(x["lead"].get("score") or 0),
                    x["lead"]["id"],
                )
            )
            continue
        items.sort(
            key=lambda x: (
                -(x["priority"]),
                (x["followup"] or {}).get("due_at") or end + timedelta(days=36500),
                x["lead"]["id"],
            )
        )
    counts = {key: len(items) for key, items in result.items()}
    if section:
        if section not in result:
            raise ValueError("Unknown queue section")
        result = {section: result[section][(page - 1) * page_size : page * page_size]}
    else:
        result = {key: items[:page_size] for key, items in result.items()}
    return {
        "sections": result,
        "counts": counts,
        "labels": SECTION_LABELS,
        "rules": rules,
        "timezone": zone,
        "excluded_dnc": db.scalar(select(func.count()).select_from(Lead).where(~outreach_allowed_clause())),
        "strategy": followup_strategy.STRATEGY,
        "definition": "Overdue means a pending explicit due date before today’s local midnight. Today includes the entire local day. Unscheduled is never overdue. Leads with no verified owner name or phone appear only under Needs skip trace.",
    }


def complete_followup(db, f, request):
    if not request.confirm:
        raise ValueError("Explicit confirmation is required")
    if f.status != "pending":
        raise ValueError("This follow-up is no longer pending")
    lead = db.get(Lead, f.lead_id)
    if request.action == "complete":
        if not request.outcome:
            raise ValueError("Choose the actual outcome; completion alone never implies contact")
        if request.outcome == "Other" and not request.note.strip():
            raise ValueError("Describe the actual outcome when choosing Other")
        f.status, f.completion_outcome, f.completed_at = "completed", request.outcome, utcnow()
        db.add(
            Activity(
                lead_id=lead.id,
                activity_type="followup_completion",
                outcome=request.outcome,
                occurred_at=utcnow(),
                summary=request.note or f"Follow-up completed: {request.outcome}.",
                source="local",
                source_metadata={"followup_id": f.id, "communication_automated": False},
            )
        )
        apply_contact_outcome(lead, request.outcome, f.completed_at)
    elif request.action == "reschedule":
        if not request.due_at or not request.due_at.tzinfo:
            raise ValueError("A timezone-aware reschedule date is required")
        f.due_at = request.due_at
    else:
        f.status = "cancelled"
    db.add(
        AuditLog(
            lead_id=lead.id,
            action="followup_" + request.action,
            details={
                "followup_id": f.id,
                "outcome": request.outcome,
                "note": request.note,
                "due_at": request.due_at.isoformat() if request.due_at else None,
            },
        )
    )
    update_next_followup(db, lead)
    db.commit()
    return f
