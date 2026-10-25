from collections import Counter
from datetime import timedelta
from sqlalchemy import select, func
from ..models import Lead, Activity, Followup, StageHistory, PipelineStage, Appointment
from ..db import utcnow
from .leads import lead_query, metric_clause, is_contact_attempt

METRICS = [
    ("total", "Total seller leads"),
    ("stage:new", "New leads"),
    ("not_contacted", "No verified contact / attempt"),
    ("attempting_contact", "Attempted, not connected"),
    ("contacted", "Contacted leads"),
    ("stage:qualified", "Qualified leads"),
    ("today", "Follow-ups due today"),
    ("overdue", "Overdue follow-ups"),
    ("upcoming", "Upcoming follow-ups"),
    ("appointments", "Appointments scheduled"),
    ("stage:offer_made", "Offers made"),
    ("stage:negotiation", "Negotiations"),
    ("stage:contract_sent", "Contract sent"),
    ("stage:under_contract", "Under contract"),
    ("stage:closed", "Closed"),
    ("stage:nurture", "Nurture"),
    ("stage:dead", "Dead / Disqualified"),
    ("missing", "Missing important information"),
    ("stage:not_contacted", "Not Contacted stage"),
    ("stage:attempting_contact", "Attempting Contact stage"),
    ("stage:contacted", "Contacted stage"),
    ("stage:follow_up", "Follow-up stage"),
    ("stage:appointment_set", "Appointment Set stage"),
    ("stage:unmapped", "Unmapped source status"),
    ("dnc", "Do Not Contact"),
]


def count_query(db, query):
    return db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0


def dashboard(db, params, zone):
    query = lead_query(params, zone)
    metrics = [
        {"key": key, "label": label, "value": count_query(db, query.where(metric_clause(key, zone)))}
        for key, label in METRICS
    ]
    existing_metric_keys = {key for key, _ in METRICS}
    for stage in db.scalars(select(PipelineStage)):
        if "stage:" + stage.code not in existing_metric_keys:
            metrics.append(
                {
                    "key": "stage:" + stage.code,
                    "label": stage.label,
                    "value": count_query(db, query.where(Lead.stage_code == stage.code)),
                }
            )
    leads = db.scalars(query).all()
    ids = [lead.id for lead in leads]
    recent = (
        db.scalars(
            select(Activity).where(Activity.lead_id.in_(ids)).order_by(Activity.recorded_at.desc()).limit(8)
        ).all()
        if ids
        else []
    )
    stage_labels = {s.code: s.label for s in db.scalars(select(PipelineStage))}

    def breakdown(values):
        return [{"label": k or "Unknown", "value": v} for k, v in Counter(values).most_common()]

    return {
        "metrics": metrics,
        "breakdowns": {
            "source": breakdown(lead_record.lead_source for lead_record in leads),
            "manager": breakdown(lead_record.assigned_manager for lead_record in leads),
            "state": breakdown(
                state
                for lead_record in leads
                for state in ({p.state for p in lead_record.properties if p.state} or {None})
            ),
            "stage": [
                {"label": stage_labels.get(k, k), "code": k, "value": v}
                for k, v in Counter(lead_record.stage_code for lead_record in leads).most_common()
            ],
        },
        "recent_activity": [
            {
                "id": a.id,
                "lead_id": a.lead_id,
                "seller": db.get(Lead, a.lead_id).full_name,
                "summary": a.summary,
                "outcome": a.outcome,
                "source": a.source,
                "recorded_at": a.recorded_at,
                "occurred_at": a.occurred_at,
            }
            for a in recent
        ],
        "timezone": zone,
        "filters": params,
        "definitions": {
            "population": "Lead totals count workspace records, including unknown-owner property-only prospects; they are not a distinct verified-person count.",
            "dates": "Date filters use the original source creation date. Unknown dates are excluded only when a date range is applied.",
            "contact": "Contacted requires explicit connection evidence or a verified historical last-contact date. Unanswered calls are attempts only.",
            "followups": "Follow-up tiles count distinct seller leads, not tasks; verified DNC leads are excluded. Overdue means due before today’s local midnight.",
        },
    }


def rate(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "percent": round(100 * numerator / denominator, 1) if denominator else None,
    }


def reports(db, params, zone):
    leads = db.scalars(lead_query(params, zone)).all()
    ids = [lead_record.id for lead_record in leads]
    n = len(leads)
    activities = db.scalars(select(Activity).where(Activity.lead_id.in_(ids))).all() if ids else []
    follows = db.scalars(select(Followup).where(Followup.lead_id.in_(ids))).all() if ids else []
    histories = (
        db.scalars(select(StageHistory).where(StageHistory.lead_id.in_(ids)).order_by(StageHistory.changed_at)).all()
        if ids
        else []
    )
    appointments = set(db.scalars(select(Appointment.lead_id).where(Appointment.lead_id.in_(ids)))) if ids else set()
    stages = Counter(lead_record.stage_code for lead_record in leads)
    ever = {}
    for h in histories:
        ever.setdefault(h.lead_id, set()).add(h.to_stage)
    for lead in leads:
        ever.setdefault(lead.id, set()).add(lead.stage_code)

    def reached(stage):
        return sum(stage in values for values in ever.values())

    attempts = {a.lead_id for a in activities if is_contact_attempt(a)} | {
        lead.id for lead in leads if lead.last_contact_at is not None
    }
    qualified = reached("qualified")
    offers = reached("offer_made")
    completed = sum(f.status == "completed" for f in follows)
    eligible = sum(f.status != "cancelled" for f in follows)
    metrics = [
        {
            "label": "Recorded contact attempt rate",
            **rate(len(attempts), n),
            "definition": "Distinct leads with a canonical recorded contact outcome or verified historical last-contact date ÷ all filtered leads; internal notes are excluded.",
        },
        {
            "label": "Verified contact rate",
            **rate(sum(lead_record.contact_status == "contacted" for lead_record in leads), n),
            "definition": "Leads with explicit connection evidence ÷ all filtered leads.",
        },
        {
            "label": "Follow-up completion rate",
            **rate(completed, eligible),
            "definition": "Completed tasks ÷ all non-cancelled tasks attached to filtered leads (all task dates).",
        },
        {
            "label": "Recorded appointment rate",
            **rate(len(appointments), n),
            "definition": "Distinct leads with a recorded appointment ÷ all filtered leads.",
        },
        {
            "label": "Recorded offer rate — all leads",
            **rate(offers, n),
            "definition": "Leads observed in Offer Made ÷ all filtered leads; prior unobserved stages are not inferred.",
        },
        {
            "label": "Recorded offer rate — qualified cohort",
            **rate(sum("qualified" in v and "offer_made" in v for v in ever.values()), qualified),
            "definition": "Leads observed in both Qualified and Offer Made ÷ leads observed in Qualified.",
        },
        {
            "label": "Recorded contract rate",
            **rate(reached("under_contract"), n),
            "definition": "Leads observed in Under Contract ÷ all filtered leads.",
        },
        {
            "label": "Recorded closing rate",
            **rate(reached("closed"), n),
            "definition": "Leads observed in Closed ÷ all filtered leads.",
        },
    ]
    now = utcnow()
    aging = Counter()
    unknown_dates = 0
    for lead in leads:
        if not lead.original_created_at:
            unknown_dates += 1
            continue
        days = (now - lead.original_created_at).days
        aging[
            "Future date — review"
            if days < 0
            else "0–7 days"
            if days <= 7
            else "8–30 days"
            if days <= 30
            else "31–90 days"
            if days <= 90
            else "90+ days"
        ] += 1
    volume = Counter(
        lead_record.original_created_at.strftime("%Y-%m") for lead_record in leads if lead_record.original_created_at
    )
    durations, previous = {}, {}
    for history in histories:
        if history.lead_id in previous:
            old = previous[history.lead_id]
            durations.setdefault(old.to_stage, []).append((history.changed_at - old.changed_at).total_seconds() / 86400)
        previous[history.lead_id] = history
    latest_activity = {}
    for activity in activities:
        if activity.occurred_at and (
            activity.lead_id not in latest_activity or activity.occurred_at > latest_activity[activity.lead_id]
        ):
            latest_activity[activity.lead_id] = activity.occurred_at
    stale_known, unknown_recency = [], []
    for lead in leads:
        known = [value for value in (lead.last_contact_at, latest_activity.get(lead.id)) if value is not None]
        if not known:
            unknown_recency.append(lead.id)
        elif max(known) < now - timedelta(days=30):
            stale_known.append(lead.id)
    stale = stale_known + unknown_recency
    return {
        "total": n,
        "rates": metrics,
        "stages": dict(stages),
        "volume": dict(sorted(volume.items())),
        "aging": dict(aging),
        "unknown_creation_dates": unknown_dates,
        "stage_duration": [
            {
                "stage": stage,
                "average_days": round(sum(values) / len(values), 2),
                "observed_completed_intervals": len(values),
            }
            for stage, values in durations.items()
        ],
        "counts": {
            "never_verified_contact": sum(lead_record.contact_status != "contacted" for lead_record in leads),
            "contact_attempts": len(attempts),
            "no_recorded_attempt": n - len(attempts),
            "no_recent_dated_activity_30_days": len(stale),
            "stale_activity_leads": len(stale_known),
            "unknown_activity_recency": len(unknown_recency),
            "missing_contact_information": sum(
                not lead_record.primary_phone and not lead_record.email for lead_record in leads
            ),
            "overdue_leads": count_query(db, lead_query(params, zone).where(metric_clause("overdue", zone))),
        },
        "limitations": [
            "Metrics reflect recorded/observed data, not proof of unrecorded business events.",
            "Time in stage uses completed locally observed intervals only. Historical stage entry dates are unavailable unless provided by the source.",
            "Lead volume excludes unknown source creation dates; local import timestamps are never substituted.",
            "No recent activity includes unknown dated history; this is not proof a seller was never contacted.",
            "Stale activity requires a known latest activity/contact timestamp older than 30 elapsed days; unknown recency is counted separately.",
        ],
    }
