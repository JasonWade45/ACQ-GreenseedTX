"""Analytics aggregates (Phase 7)."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Lead, Message, Template


def analytics(db: Session) -> dict:
    total_leads = db.query(Lead).count()
    by_tier = {r[0]: r[1] for r in db.query(Lead.priority_tier, func.count(Lead.id)).group_by(Lead.priority_tier).all()}
    by_lead_type = {r[0]: r[1] for r in db.query(Lead.lead_type, func.count(Lead.id)).group_by(Lead.lead_type).all()}
    by_county = {r[0]: r[1] for r in db.query(Lead.county, func.count(Lead.id)).group_by(Lead.county).all()}
    sent = db.query(Message).filter(Message.direction == "outbound", Message.status.in_(["SENT", "DELIVERED"])).count()
    drafts = db.query(Message).filter(Message.status == "DRAFT").count()
    approved = db.query(Message).filter(Message.status == "APPROVED").count()
    inbound = db.query(Message).filter(Message.direction == "inbound").count()
    opt_outs = db.query(Message).filter(Message.classification == "STOP").count()
    templates = []
    for t in db.query(Template).all():
        templates.append({"id": t.id, "category": t.category, "variant": t.variant, "stats": t.stats or {}})
    return {
        "total_leads": total_leads,
        "by_tier": by_tier,
        "by_lead_type": by_lead_type,
        "by_county": by_county,
        "messages": {"sent": sent, "drafts": drafts, "approved": approved, "inbound": inbound, "opt_outs": opt_outs},
        "templates": templates,
    }
