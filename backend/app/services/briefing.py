"""Daily briefing (Phase 7).

Everything here is read-only. Each block answers "what is waiting for a human?" and
carries the evidence behind it; nothing is summarised away and nothing is invented.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import AppSetting, AuditLog, Lead, Message, SuggestedAction, SyncConflict

STALLED_DAYS = 14
CLASSIFICATION_WEIGHT = {
    "STOP": 0,
    "WRONG_NUMBER": 1,
    "INTERESTED": 2,
    "WANTS_PRICE": 3,
    "QUESTION": 4,
    "NOT_NOW": 5,
    "NOT_INTERESTED": 6,
    "OTHER": 7,
}


def _backup_block(db: Session) -> dict:
    last = (
        db.query(AuditLog)
        .filter(AuditLog.action == "backup_created")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    row = db.get(AppSetting, "backup_second_folder")
    value = row.value if row and isinstance(row.value, dict) else {}
    status = value.get("status") or {}
    return {
        "last_backup_at": last.created_at.isoformat() if last and last.created_at else None,
        "last_backup_file": (last.details or {}).get("file") if last else None,
        "last_backup_reason": (last.details or {}).get("reason") if last else None,
        "second_folder": value.get("path"),
        "second_folder_ok": status.get("ok") if status else None,
        "second_folder_detail": status.get("detail") if status else None,
        "second_folder_checked_at": status.get("copied_at") if status else None,
    }


def _suggestions(db: Session) -> list[dict]:
    rows = (
        db.query(SuggestedAction)
        .filter(SuggestedAction.status == "pending")
        .order_by(SuggestedAction.id.desc())
        .limit(50)
        .all()
    )
    items = []
    for row in rows:
        lead = db.get(Lead, row.lead_id)
        items.append(
            {
                "id": row.id,
                "lead_id": row.lead_id,
                "lead_name": lead.full_name if lead else None,
                "kind": row.kind,
                "classification": row.classification,
                "confidence": row.confidence,
                "evidence": row.evidence,
                "needs_review": bool((row.payload or {}).get("needs_review")),
                "label": (
                    "Add to suppression"
                    if row.kind == "suppress"
                    else "Review suggested reply"
                    if row.kind == "price_question"
                    else "Confirm suggested action"
                ),
                "heat": getattr(lead, "heat", None),
                "score": getattr(lead, "score", None),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    # A literal opt-out always surfaces first; then the hottest reply.
    items.sort(
        key=lambda item: (
            CLASSIFICATION_WEIGHT.get(item["classification"] or "OTHER", 9),
            -(item["score"] or 0),
            -(item["heat"] == "VERY_HOT"),
        )
    )
    return items


def briefing(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=STALLED_DAYS)

    suggestions = _suggestions(db)
    replies = [
        {
            "lead_id": item["lead_id"],
            "name": item["lead_name"],
            "classification": item["classification"],
            "confidence": item["confidence"],
            "evidence": item["evidence"],
            "suggestion_id": item["id"],
            "kind": item["kind"],
            "needs_review": item["needs_review"],
            "received_at": item["created_at"],
        }
        for item in suggestions
    ]

    due = (
        db.query(Lead)
        .filter(Lead.next_followup_at.isnot(None), Lead.next_followup_at <= now)
        .order_by(Lead.next_followup_at)
        .limit(20)
        .all()
    )
    followups = [
        {"lead_id": x.id, "name": x.full_name, "due_at": x.next_followup_at.isoformat() if x.next_followup_at else None}
        for x in due
    ]

    drafts = (
        db.query(Message)
        .filter(Message.status == "DRAFT", Message.direction == "outbound")
        .count()
    )
    invalid_drafts = (
        db.query(Message)
        .filter(Message.status == "DRAFT", Message.direction == "outbound")
        .all()
    )
    invalid_drafts = [
        {"id": m.id, "lead_id": m.lead_id, "reasons": (m.validator_result or {}).get("reasons", [])}
        for m in invalid_drafts
        if not (m.validator_result or {}).get("ok", True)
    ]

    skip_trace = db.query(Lead).filter(Lead.needs_skip_trace.is_(True)).count()
    skip_trace_rows = (
        db.query(Lead)
        .filter(Lead.needs_skip_trace.is_(True))
        .order_by(Lead.priority_rank.desc().nullslast(), Lead.id)
        .limit(10)
        .all()
    )

    stalled = db.query(Lead).filter(Lead.updated_at < cutoff, Lead.contact_status == "unknown").count()
    conflicts = db.query(SyncConflict).filter(SyncConflict.resolved.is_(False)).count()

    return {
        "generated_at": now.isoformat(),
        # A literal STOP is a compliance item, so it is listed first and separately.
        "compliance_first": [item for item in suggestions if item["classification"] == "STOP"],
        "replies_needing_action": replies,
        "followups_due": followups,
        "drafts_awaiting_approval": drafts,
        "drafts_failing_validation": invalid_drafts,
        "leads_needing_skip_trace": skip_trace,
        "skip_trace_leads": [
            {
                "lead_id": lead.id,
                "address": lead.properties[0].street_address if lead.properties else None,
                "heat": lead.heat,
                "score": lead.score,
                "priority_tier": lead.priority_tier,
            }
            for lead in skip_trace_rows
        ],
        "stalled_leads": stalled,
        "stalled_window_days": STALLED_DAYS,
        "sync_conflicts": conflicts,
        "backups": _backup_block(db),
        "last_backup": _backup_block(db)["last_backup_at"],
        "never_sent": True,
    }
