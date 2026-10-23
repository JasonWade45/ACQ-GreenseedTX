"""Audit trail helpers for important local actions."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(
    db: Session,
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
    commit: bool = True,
) -> AuditLog:
    entry = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail or {},
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    return entry
