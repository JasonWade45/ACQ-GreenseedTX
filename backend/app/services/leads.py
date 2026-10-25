from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo
from sqlalchemy import select, or_, and_, exists, func
from ..models import Lead, Property, LeadProperty, Followup, Activity, Appointment, AuditLog, StageHistory
from ..db import utcnow

CONTACTED = {
    "Connected",
    "Callback Requested",
    "Appointment Scheduled",
    "Seller Not Interested",
    "Offer Accepted",
    "Offer Rejected",
}
ATTEMPTED = {"No Answer", "Left Voicemail", "Wrong Number"}
NON_CONTACT_ACTIVITY_TYPES = {"note", "source_note_snapshot", "appointment_result", "offer_result", "stage_change"}


def source_date_is_connection(outcome):
    # Explicit failed/unknown outcomes take precedence over an ambiguously named source date.
    return not outcome or outcome in CONTACTED


def contact_attempt_exists():
    return or_(
        Lead.last_contact_at.is_not(None),
        exists(
            select(Activity.id).where(
                Activity.lead_id == Lead.id,
                Activity.activity_type.notin_(NON_CONTACT_ACTIVITY_TYPES),
                Activity.outcome.in_(CONTACTED | ATTEMPTED),
            )
        ),
    )


def is_contact_attempt(activity):
    return activity.activity_type not in NON_CONTACT_ACTIVITY_TYPES and activity.outcome in CONTACTED | ATTEMPTED


def day_bounds(zone, now=None):
    local = (now or utcnow()).astimezone(ZoneInfo(zone))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    # Compute next midnight locally so DST days can be 23 or 25 hours.
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def outreach_allowed_clause():
    return and_(
        Lead.local_do_not_contact.is_(False),
        or_(Lead.source_do_not_contact.is_(None), Lead.source_do_not_contact.is_(False)),
    )


def followup_exists(*conditions):
    return exists(select(Followup.id).where(Followup.lead_id == Lead.id, Followup.status == "pending", *conditions))


def missing_clause():
    return or_(
        Lead.full_name == "",
        Lead.full_name.is_(None),
        Lead.primary_phone.is_(None),
        ~exists(select(LeadProperty.lead_id).where(LeadProperty.lead_id == Lead.id)),
        exists(select(Property.id).join(LeadProperty).where(LeadProperty.lead_id == Lead.id, Property.state.is_(None))),
        Lead.original_created_at.is_(None),
        Lead.assigned_manager.is_(None),
        and_(
            Lead.source_do_not_contact.is_(None),
            Lead.restriction_reviewed.is_(False),
            Lead.local_do_not_contact.is_(False),
        ),
    )


def metric_clause(metric, zone):
    start, end = day_bounds(zone)
    if metric == "total":
        return True
    if metric.startswith("stage:"):
        return Lead.stage_code == metric.split(":", 1)[1]
    if metric == "never_contacted":
        return Lead.contact_status != "contacted"
    if metric == "missing_contact":
        return and_(Lead.primary_phone.is_(None), Lead.email.is_(None))
    if metric == "not_contacted":
        return Lead.contact_status.in_(["unknown", "not_contacted"])
    if metric == "attempting_contact":
        return Lead.contact_status == "attempted"
    if metric == "contacted":
        return Lead.contact_status == "contacted"
    if metric == "overdue":
        return and_(outreach_allowed_clause(), followup_exists(Followup.due_at < start))
    if metric == "today":
        return and_(outreach_allowed_clause(), followup_exists(Followup.due_at >= start, Followup.due_at < end))
    if metric == "upcoming":
        return and_(outreach_allowed_clause(), followup_exists(Followup.due_at >= end))
    if metric == "unscheduled":
        return and_(outreach_allowed_clause(), followup_exists(Followup.due_at.is_(None)))
    if metric == "appointments":
        return exists(
            select(Appointment.id).where(
                Appointment.lead_id == Lead.id,
                Appointment.starts_at >= start,
                Appointment.status == "scheduled",
                Appointment.local_result.is_(None),
            )
        )
    if metric == "missing":
        return missing_clause()
    if metric == "dnc":
        return or_(Lead.local_do_not_contact.is_(True), Lead.source_do_not_contact.is_(True))
    if metric in {"stale", "stale_activity_leads", "unknown_activity_recency"}:
        cutoff = utcnow() - timedelta(days=30)
        last_activity = select(func.max(Activity.occurred_at)).where(Activity.lead_id == Lead.id).scalar_subquery()
        unknown_recency = and_(Lead.last_contact_at.is_(None), last_activity.is_(None))
        if metric == "unknown_activity_recency":
            return unknown_recency
        no_recent = and_(
            or_(Lead.last_contact_at.is_(None), Lead.last_contact_at < cutoff),
            or_(last_activity.is_(None), last_activity < cutoff),
        )
        return and_(~unknown_recency, no_recent) if metric == "stale_activity_leads" else no_recent
    if metric == "contact_attempts":
        return contact_attempt_exists()
    if metric == "no_recorded_attempt":
        return ~contact_attempt_exists()
    raise ValueError("Unknown metric filter")


def lead_query(params, zone):
    query = select(Lead)
    search = params.get("search")
    if search:
        # Treat SQL wildcard characters as literal user input.
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        needle = f"%{escaped}%"
        address = exists(
            select(Property.id)
            .join(LeadProperty, LeadProperty.property_id == Property.id)
            .where(
                LeadProperty.lead_id == Lead.id,
                or_(
                    *(
                        getattr(Property, k).ilike(needle, escape="\\")
                        for k in ["street_address", "city", "state", "zip_code"]
                    )
                ),
            )
        )
        phone_digits = re.sub(r"\D", "", search)
        phone_match = (
            Lead.primary_phone.contains(phone_digits)
            if len(phone_digits) >= 7 and re.fullmatch(r"[\d\s()+.\-]+", search)
            else False
        )
        query = query.where(
            or_(
                address,
                phone_match,
                *(
                    getattr(Lead, k).ilike(needle, escape="\\")
                    for k in ["full_name", "primary_phone", "email", "external_id"]
                ),
            )
        )
    for key, field in [
        ("stage", "stage_code"),
        ("source", "lead_source"),
        ("manager", "assigned_manager"),
        ("contact_status", "contact_status"),
    ]:
        if params.get(key):
            value = params[key]
            query = query.where(
                getattr(Lead, field).is_(None) if value == "__unknown__" else getattr(Lead, field) == value
            )
    if params.get("state"):
        query = query.where(
            ~exists(
                select(Property.id)
                .join(LeadProperty)
                .where(LeadProperty.lead_id == Lead.id, Property.state.is_not(None))
            )
            if params["state"] == "__unknown__"
            else exists(
                select(Property.id)
                .join(LeadProperty)
                .where(LeadProperty.lead_id == Lead.id, Property.state == params["state"])
            )
        )
    for key, operator in [("from_date", "__ge__"), ("to_date", "__lt__")]:
        if params.get(key):
            day = datetime.fromisoformat(params[key]).replace(tzinfo=ZoneInfo(zone))
            if key == "to_date":
                day += timedelta(days=1)
            query = query.where(getattr(Lead.original_created_at, operator)(day.astimezone(timezone.utc)))
    if params.get("metric"):
        query = query.where(metric_clause(params["metric"], zone))
    if params.get("followup"):
        query = query.where(metric_clause(params["followup"], zone))
    return query


def missing_information(lead):
    result = []
    if not lead.full_name:
        result.append("Seller identity")
    if not lead.primary_phone:
        result.append("Phone number")
    if not lead.email:
        result.append("Email address (optional)")
    if not lead.properties or not any(p.street_address for p in lead.properties):
        result.append("Property address")
    if lead.properties and any(not p.state for p in lead.properties):
        result.append("Property state")
    if not lead.original_created_at:
        result.append("Original creation date")
    if not lead.assigned_manager:
        result.append("Assigned manager")
    if lead.restriction_status == "unknown":
        result.append("Contact restriction review")
    if lead.contact_status == "unknown":
        result.append("Verified contact history")
    return result


def property_dict(prop):
    return {
        k: getattr(prop, k)
        for k in [
            "id",
            "external_id",
            "street_address",
            "city",
            "state",
            "zip_code",
            "property_type",
            "bedrooms",
            "bathrooms",
            "square_feet",
            "year_built",
            "asking_price",
            "estimated_value",
            "repair_estimate",
            "property_metadata",
        ]
    }


def lead_dict(lead):
    keys = [
        "id",
        "external_id",
        "first_name",
        "last_name",
        "full_name",
        "primary_phone",
        "email",
        "lead_source",
        "original_created_at",
        "stage_code",
        "source_status",
        "contact_status",
        "contact_outcome",
        "assigned_manager",
        "last_contact_at",
        "next_followup_at",
        "source_kind",
        "created_at",
        "updated_at",
        "synced_at",
        "source_do_not_contact",
        "local_do_not_contact",
        "local_stage_override",
        "restriction_evidence",
    ]
    return {
        **{k: getattr(lead, k) for k in keys},
        "do_not_contact": lead.do_not_contact,
        "restriction_status": lead.restriction_status,
        "properties": [property_dict(p) for p in lead.properties],
        "missing_information": missing_information(lead),
    }


def activity_dict(a):
    return {
        k: getattr(a, k)
        for k in [
            "id",
            "external_id",
            "lead_id",
            "activity_type",
            "direction",
            "outcome",
            "occurred_at",
            "recorded_at",
            "source",
            "summary",
            "source_metadata",
        ]
    }


def followup_dict(f):
    return {
        k: getattr(f, k)
        for k in [
            "id",
            "lead_id",
            "property_id",
            "due_at",
            "priority",
            "reason",
            "suggested_action",
            "status",
            "completed_at",
            "completion_outcome",
            "creation_source",
            "ai_suggested",
            "created_at",
        ]
    }


def appointment_dict(a):
    return {
        k: getattr(a, k)
        for k in [
            "id",
            "external_id",
            "lead_id",
            "starts_at",
            "status",
            "source_status",
            "local_result",
            "notes",
            "source",
        ]
    }


def update_next_followup(db, lead):
    db.flush()
    lead.next_followup_at = db.scalar(
        select(func.min(Followup.due_at)).where(Followup.lead_id == lead.id, Followup.status == "pending")
    )


def apply_contact_outcome(lead, outcome, occurred_at):
    if not outcome or outcome == "Administrative / No Contact":
        return
    lead.contact_outcome = outcome
    if outcome == "Do Not Contact":
        lead.local_do_not_contact = True
    elif outcome in CONTACTED:
        lead.contact_status = "contacted"
        if occurred_at and (not lead.last_contact_at or occurred_at > lead.last_contact_at):
            lead.last_contact_at = occurred_at
    elif outcome in ATTEMPTED and lead.contact_status != "contacted":
        lead.contact_status = "attempted"


def set_stage(db, lead, stage, source="local"):
    if lead.stage_code != stage:
        db.add(StageHistory(lead_id=lead.id, from_stage=lead.stage_code, to_stage=stage, source=source))
        db.add(
            AuditLog(
                lead_id=lead.id,
                action="stage_changed",
                details={"from": lead.stage_code, "to": stage, "source": source},
            )
        )
        lead.stage_code = stage
    if source == "local":
        lead.local_stage_override = True
