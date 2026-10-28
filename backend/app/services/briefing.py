"""Daily briefing aggregation (Phase 7)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from ..models import Lead, Message, SyncConflict, AuditLog


def briefing(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=14)
    # replies needing action
    inbound = db.query(Message).filter(Message.direction == "inbound", Message.classification.in_(["INTERESTED", "WANTS_PRICE"])).order_by(Message.created_at.desc()).limit(20).all()
    replies = []
    for m in inbound:
        lead = db.get(Lead, m.lead_id)
        if lead:
            replies.append({"lead_id": lead.id, "name": lead.full_name, "classification": m.classification, "confidence": m.confidence, "received_at": m.created_at.isoformat() if m.created_at else None})
    # follow-ups due
    due = db.query(Lead).filter(Lead.next_followup_at.isnot(None), Lead.next_followup_at <= now).order_by(Lead.next_followup_at).limit(20).all()
    followups = [{"lead_id": x.id, "name": x.full_name, "due_at": x.next_followup_at.isoformat() if x.next_followup_at else None} for x in due]
    # drafts awaiting approval
    drafts = db.query(Message).filter(Message.status == "DRAFT", Message.direction == "outbound").count()
    # skip trace needed
    skip_trace = db.query(Lead).filter(Lead.needs_skip_trace.is_(True)).count()
    # stalled leads
    stalled = db.query(Lead).filter(Lead.updated_at < cutoff, Lead.contact_status == "unknown").count()
    # sync conflicts
    conflicts = db.query(SyncConflict).filter(SyncConflict.resolved.is_(False)).count()
    # backup status
    last_backup = db.query(AuditLog).filter(AuditLog.action == "backup_created").order_by(AuditLog.created_at.desc()).first()
    return {
        "generated_at": now.isoformat(),
        "replies_needing_action": replies,
        "followups_due": followups,
        "drafts_awaiting_approval": drafts,
        "leads_needing_skip_trace": skip_trace,
        "stalled_leads": stalled,
        "sync_conflicts": conflicts,
        "last_backup": (last_backup.created_at.isoformat() if last_backup and last_backup.created_at else None),
    }
