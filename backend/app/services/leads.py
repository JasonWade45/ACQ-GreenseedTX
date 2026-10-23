"""Lead read/write helpers: serialization, missing-data checks, rollups."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import Activity, Appointment, Followup, Lead, LeadProperty, Property
from app.services.normalization import address_key

CRITICAL_FIELDS = [
    {"field": "primary_phone", "label": "Phone number", "severity": "critical"},
    {"field": "email", "label": "Email address", "severity": "warning"},
    {"field": "property", "label": "Property address", "severity": "critical"},
    {"field": "lead_source", "label": "Lead source", "severity": "warning"},
    {"field": "first_name", "label": "First name", "severity": "warning"},
]


def primary_property(lead: Lead) -> Optional[Property]:
    if not lead.properties:
        return None
    for link in lead.properties:
        if link.is_primary and link.property:
            return link.property
    return lead.properties[0].property if lead.properties else None


def missing_fields(lead: Lead) -> list[dict[str, Any]]:
    prop = primary_property(lead)
    values = {
        "primary_phone": lead.primary_phone,
        "email": lead.email,
        "property": prop.formatted_address if prop and prop.address_line1 else None,
        "lead_source": lead.lead_source,
        "first_name": lead.first_name,
    }
    out = []
    for spec in CRITICAL_FIELDS:
        if not values.get(spec["field"]):
            out.append(dict(spec))
    return out


def has_critical_missing(lead: Lead) -> bool:
    return any(m["severity"] == "critical" for m in missing_fields(lead))


def next_open_followup(db: Session, lead_id: str) -> Optional[Followup]:
    return (
        db.query(Followup)
        .filter(Followup.lead_id == lead_id, Followup.status == "open")
        .order_by(Followup.due_at.asc())
        .first()
    )


def refresh_lead_rollups(db: Session, lead: Lead) -> None:
    """Recompute next_followup_at / contact_status / last_contact_at."""
    # autoflush is disabled on this session: flush first so follow-ups or
    # activities added in the current transaction are visible to the queries.
    db.flush()
    fu = next_open_followup(db, lead.id)
    lead.next_followup_at = fu.due_at if fu else None

    contact_activities = [
        a
        for a in lead.activities
        if a.outcome in {"connected", "callback_requested", "seller_not_interested", "appointment_scheduled"}
        or (a.outcome is None and a.direction == "inbound" and a.activity_type in {"call", "text", "email"})
    ]
    if contact_activities:
        lead.last_contact_at = max(a.occurred_at for a in contact_activities)
        latest = contact_activities[0]  # activities ordered desc
        if latest.outcome:
            lead.contact_status = latest.outcome
        elif lead.contact_status == "never_contacted":
            lead.contact_status = "connected"
    elif lead.do_not_contact:
        lead.contact_status = "do_not_contact"
    else:
        attempted = [a for a in lead.activities if a.activity_type in {"call", "text", "email"}]
        if attempted:
            latest = attempted[0]
            if latest.outcome and latest.outcome in {"no_answer", "left_voicemail", "wrong_number"}:
                lead.contact_status = latest.outcome
            elif lead.contact_status == "never_contacted":
                lead.contact_status = "no_answer"
            lead.last_contact_at = None
        else:
            lead.contact_status = "do_not_contact" if lead.do_not_contact else "never_contacted"


def link_property(
    db: Session,
    lead: Lead,
    *,
    external_id: Optional[str] = None,
    address_line1: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
    property_type: Optional[str] = None,
    replace: bool = False,
) -> Property:
    existing: Optional[Property] = None
    if external_id:
        existing = db.query(Property).filter(Property.external_id == external_id).first()
    akey = address_key(address_line1, city, state, zip_code) if address_line1 else None
    if existing is None and akey:
        existing = db.query(Property).filter(Property.address_normalized == akey).first()
    if existing is None:
        existing = Property(
            external_id=external_id,
            address_line1=address_line1,
            city=city,
            state=state,
            zip_code=zip_code,
            address_normalized=akey,
            property_type=property_type,
        )
        db.add(existing)
        db.flush()
    else:
        if external_id and not existing.external_id:
            existing.external_id = external_id
        existing.address_line1 = address_line1 or existing.address_line1
        existing.city = city or existing.city
        existing.state = state or existing.state
        existing.zip_code = zip_code or existing.zip_code
        existing.property_type = property_type or existing.property_type
        existing.address_normalized = akey or existing.address_normalized

    already_linked = (
        db.query(LeadProperty)
        .filter(LeadProperty.lead_id == lead.id, LeadProperty.property_id == existing.id)
        .first()
    )
    if not already_linked:
        if replace:
            for link in list(lead.properties):
                link.is_primary = False
        db.add(LeadProperty(lead_id=lead.id, property_id=existing.id, is_primary=True))
    return existing


def serialize_property(prop: Optional[Property]) -> Optional[dict[str, Any]]:
    if not prop:
        return None
    return {
        "id": prop.id,
        "external_id": prop.external_id,
        "address_line1": prop.address_line1,
        "address_line2": prop.address_line2,
        "city": prop.city,
        "state": prop.state,
        "zip_code": prop.zip_code,
        "formatted_address": prop.formatted_address,
        "property_type": prop.property_type,
        "bedrooms": prop.bedrooms,
        "bathrooms": prop.bathrooms,
        "square_footage": prop.square_footage,
        "year_built": prop.year_built,
        "county": prop.county,
        "latitude": prop.latitude,
        "longitude": prop.longitude,
        "lot_acres": prop.lot_acres,
        "asking_price": prop.asking_price,
        "estimated_value": prop.estimated_value,
        "repair_estimate": prop.repair_estimate,
        "extra": prop.extra,
    }


def serialize_lead(lead: Lead, db: Optional[Session] = None, *, detail: bool = False) -> dict[str, Any]:
    from app.services.pipeline import STAGES

    prop = primary_property(lead)
    data: dict[str, Any] = {
        "id": lead.id,
        "external_id": lead.external_id,
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "full_name": lead.display_name,
        "primary_phone": lead.primary_phone,
        "phone_normalized": lead.phone_normalized,
        "email": lead.email,
        "lead_source": lead.lead_source,
        "original_creation_date": lead.original_creation_date.isoformat() if lead.original_creation_date else None,
        "pipeline_stage": lead.pipeline_stage,
        "pipeline_stage_label": STAGES.get(lead.pipeline_stage, {}).get("label", lead.pipeline_stage),
        "source_status": lead.source_status,
        "contact_status": lead.contact_status,
        "assigned_manager": lead.assigned_manager,
        "last_contact_at": lead.last_contact_at.isoformat() if lead.last_contact_at else None,
        "next_followup_at": lead.next_followup_at.isoformat() if lead.next_followup_at else None,
        "do_not_contact": lead.do_not_contact,
        "is_hot_lead": lead.is_hot_lead,
        "tags": lead.tags or [],
        "notes": lead.notes,
        "origin": lead.origin,
        "import_batch_id": lead.import_batch_id,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        "last_synced_at": lead.last_synced_at.isoformat() if lead.last_synced_at else None,
        "property": serialize_property(prop),
        "missing_fields": missing_fields(lead),
        "has_critical_missing": has_critical_missing(lead),
        "activity_count": len(lead.activities) if lead.activities is not None else 0,
        "open_followup_count": (
            sum(1 for f in lead.followups if f.status == "open") if lead.followups is not None else 0
        ),
    }
    if detail:
        data["properties"] = [serialize_property(lp.property) for lp in lead.properties]
        data["activities"] = [serialize_activity(a) for a in lead.activities]
        data["appointments"] = [serialize_appointment(a) for a in lead.appointments]
        data["followups"] = [serialize_followup(f) for f in lead.followups]
        data["insights"] = [serialize_insight(i) for i in lead.insights[:5]]
        data["drafts"] = [serialize_draft(d) for d in lead.drafts[:10]]
        data["call_plan"] = serialize_call_plan(lead.call_plans[0]) if lead.call_plans else None
    return data


def serialize_activity(a: Activity) -> dict[str, Any]:
    return {
        "id": a.id,
        "external_id": a.external_id,
        "lead_id": a.lead_id,
        "activity_type": a.activity_type,
        "direction": a.direction,
        "outcome": a.outcome,
        "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
        "recorded_at": a.recorded_at.isoformat() if a.recorded_at else None,
        "source": a.source,
        "summary": a.summary,
        "detail": a.detail,
    }


def serialize_appointment(a: Appointment) -> dict[str, Any]:
    return {
        "id": a.id,
        "external_id": a.external_id,
        "lead_id": a.lead_id,
        "scheduled_at": a.scheduled_at.isoformat() if a.scheduled_at else None,
        "end_at": a.end_at.isoformat() if a.end_at else None,
        "status": a.status,
        "appointment_type": a.appointment_type,
        "appointment_subtype": a.appointment_subtype,
        "notes": a.notes,
        "source": a.source,
    }


def serialize_followup(f: Followup) -> dict[str, Any]:
    return {
        "id": f.id,
        "lead_id": f.lead_id,
        "due_at": f.due_at.isoformat() if f.due_at else None,
        "priority": f.priority,
        "reason": f.reason,
        "suggested_next_action": f.suggested_next_action,
        "status": f.status,
        "completed_at": f.completed_at.isoformat() if f.completed_at else None,
        "completion_outcome": f.completion_outcome,
        "completion_notes": f.completion_notes,
        "creation_source": f.creation_source,
        "ai_suggested": f.ai_suggested,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


def serialize_insight(i) -> dict[str, Any]:
    return {
        "id": i.id,
        "lead_id": i.lead_id,
        "summary": i.summary,
        "seller_motivation": i.seller_motivation,
        "urgency_indicators": i.urgency_indicators or [],
        "price_information": i.price_information or {},
        "objections": i.objections or [],
        "missing_information": i.missing_information or [],
        "recommended_next_action": i.recommended_next_action,
        "suggested_followup_at": i.suggested_followup_at.isoformat() if i.suggested_followup_at else None,
        "evidence": i.evidence or [],
        "confidence": i.confidence,
        "engine": i.engine,
        "model": i.model,
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }


def serialize_draft(d) -> dict[str, Any]:
    return {
        "id": d.id,
        "lead_id": d.lead_id,
        "channel_hint": d.channel_hint,
        "body": d.body,
        "edited_body": d.edited_body,
        "context_used": d.context_used or [],
        "refusal_reason": d.refusal_reason,
        "engine": d.engine,
        "model": d.model,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


def serialize_call_plan(plan) -> Optional[dict[str, Any]]:
    if not plan:
        return None
    return {
        "id": plan.id,
        "lead_id": plan.lead_id,
        "opener": plan.opener,
        "talking_points": plan.talking_points or [],
        "questions": plan.questions or [],
        "do_not_say": plan.do_not_say or [],
        "context_used": plan.context_used or [],
        "refusal_reason": plan.refusal_reason,
        "engine": plan.engine,
        "model": plan.model,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
    }


def upsert_followup(
    db: Session,
    lead: Lead,
    due_at: datetime,
    reason: str,
    action: str,
    priority: int = 3,
    source: str = "manual",
    ai_suggested: bool = False,
    replace_open: bool = True,
) -> Followup:
    if replace_open:
        existing = next_open_followup(db, lead.id)
        if existing and existing.due_at == due_at and existing.reason == reason:
            return existing
        if existing and source == "rule":
            # Keep a user-created follow-up; only add rule-driven ones when none exist
            return existing
    prop = primary_property(lead)
    fu = Followup(
        lead_id=lead.id,
        property_id=prop.id if prop else None,
        due_at=due_at,
        priority=priority,
        reason=reason,
        suggested_next_action=action,
        creation_source=source,
        ai_suggested=ai_suggested,
        status="open",
    )
    db.add(fu)
    lead.next_followup_at = due_at
    db.flush()
    return fu
