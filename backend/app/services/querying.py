"""Shared lead query builder used by the list view, dashboard counts and reports."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import and_, func, not_, or_
from sqlalchemy.orm import Query, Session, joinedload

from app.models import Lead, LeadProperty, Property
from app.services.pipeline import today_bounds


def _lead_properties_join(query: Query) -> Query:
    return query.join(LeadProperty, LeadProperty.lead_id == Lead.id, isouter=True).join(
        Property, Property.id == LeadProperty.property_id, isouter=True
    )


def base_query(db: Session) -> Query:
    return db.query(Lead).options(joinedload(Lead.properties).joinedload(LeadProperty.property))


def apply_filters(query: Query, params: dict[str, Any], tz: str = "UTC") -> Query:
    stage = params.get("stage")
    if stage:
        stages = [stage] if isinstance(stage, str) else list(stage)
        stages = [s for s in stages if s]
        if stages:
            query = query.filter(Lead.pipeline_stage.in_(stages))

    contact_status = params.get("contact_status")
    if contact_status:
        values = [contact_status] if isinstance(contact_status, str) else list(contact_status)
        query = query.filter(Lead.contact_status.in_(values))

    source = params.get("source")
    if source:
        values = [source] if isinstance(source, str) else list(source)
        query = query.filter(Lead.lead_source.in_(values))

    manager = params.get("manager")
    if manager:
        values = [manager] if isinstance(manager, str) else list(manager)
        query = query.filter(Lead.assigned_manager.in_(values))

    state = params.get("state")
    if state:
        values = [state] if isinstance(state, str) else list(state)
        query = _lead_properties_join(query).filter(Property.state.in_(values))

    dnc = params.get("do_not_contact")
    if dnc is True or dnc == "true":
        query = query.filter(Lead.do_not_contact.is_(True))
    elif dnc is False or dnc == "false":
        query = query.filter(Lead.do_not_contact.is_(False))

    never = params.get("never_contacted")
    if never is True or never == "true":
        query = query.filter(Lead.contact_status == "never_contacted")

    date_from = params.get("date_from")
    date_to = params.get("date_to")
    if date_from:
        try:
            start = datetime.fromisoformat(str(date_from))
            query = query.filter(Lead.original_creation_date >= start.date())
        except ValueError:
            pass
    if date_to:
        try:
            end = datetime.fromisoformat(str(date_to))
            query = query.filter(Lead.original_creation_date <= end.date())
        except ValueError:
            pass

    missing = params.get("missing")
    if missing in {"critical", "any", "true"}:
        query = query.filter(
            or_(
                Lead.phone_normalized.is_(None),
                Lead.primary_phone.is_(None),
                not_(exists_property()),
            )
        )
    elif missing == "none":
        query = query.filter(
            and_(Lead.phone_normalized.isnot(None), exists_property())
        )

    followup_state = params.get("followup_state")
    if followup_state and followup_state != "any":
        day_start, day_end = today_bounds(tz)
        if followup_state == "overdue":
            query = query.filter(
                and_(Lead.next_followup_at.isnot(None), Lead.next_followup_at < day_start)
            )
        elif followup_state == "due_today":
            query = query.filter(
                and_(Lead.next_followup_at >= day_start, Lead.next_followup_at < day_end)
            )
        elif followup_state == "upcoming":
            lookahead = int(params.get("upcoming_lookahead_days") or 14)
            query = query.filter(
                and_(Lead.next_followup_at >= day_end, Lead.next_followup_at <= day_end + timedelta(days=lookahead))
            )
        elif followup_state == "open":
            query = query.filter(Lead.next_followup_at.isnot(None))
        elif followup_state == "unscheduled":
            unscheduled_stages = params.get("unscheduled_stage_keys") or []
            if unscheduled_stages:
                query = query.filter(
                    and_(Lead.pipeline_stage.in_(unscheduled_stages), Lead.next_followup_at.is_(None))
                )
            else:
                query = query.filter(Lead.next_followup_at.is_(None))

    origin = params.get("origin")
    if origin:
        values = [origin] if isinstance(origin, str) else list(origin)
        query = query.filter(Lead.origin.in_(values))

    q = (params.get("q") or "").strip()
    if q:
        like = f"%{q.lower()}%"
        query = query.outerjoin(LeadProperty, LeadProperty.lead_id == Lead.id).outerjoin(
            Property, Property.id == LeadProperty.property_id
        ).filter(
            or_(
                func.lower(Lead.full_name).like(like),
                func.lower(Lead.first_name).like(like),
                func.lower(Lead.last_name).like(like),
                func.lower(func.coalesce(Lead.primary_phone, "")).like(like),
                func.lower(func.coalesce(Lead.phone_normalized, "")).like(like.replace("%", "")),
                func.lower(func.coalesce(Lead.email, "")).like(like),
                func.lower(func.coalesce(Lead.external_id, "")).like(like),
                func.lower(func.coalesce(Property.address_line1, "")).like(like),
                func.lower(func.coalesce(Property.city, "")).like(like),
                func.lower(func.coalesce(Property.zip_code, "")).like(like),
            )
        )

    return query.distinct()


def exists_property() -> Any:
    from sqlalchemy import exists

    return exists().where(LeadProperty.lead_id == Lead.id)


def apply_sort(query: Query, sort: Optional[str], direction: str = "desc") -> Query:
    order = "desc" if str(direction).lower() == "desc" else "asc"
    col = {
        "name": Lead.full_name,
        "created": Lead.created_at,
        "updated": Lead.updated_at,
        "stage": Lead.pipeline_stage,
        "followup": Lead.next_followup_at,
        "last_contact": Lead.last_contact_at,
        "source": Lead.lead_source,
    }.get((sort or "updated").lower(), Lead.updated_at)
    return query.order_by(col.desc() if order == "desc" else col.asc())
