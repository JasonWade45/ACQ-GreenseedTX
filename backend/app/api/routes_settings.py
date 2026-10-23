"""Application settings, pipeline mapping and audit endpoints."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import AuditLog
from app.services.audit import audit
from app.services.pipeline import (
    COMPLETION_OUTCOMES,
    CONTACT_OUTCOMES,
    DEFAULT_FOLLOWUP_RULES,
    DEFAULT_STAGE_MAPPING,
    STAGES,
)
from app.services.settings_service import all_settings, followup_rules, set_setting, update_followup_rules

router = APIRouter(tags=["settings"])


class SettingsPayload(BaseModel):
    stage_mapping: Optional[dict[str, str]] = None
    followup_rules: Optional[dict[str, Any]] = None
    ui: Optional[dict[str, Any]] = None
    sync_enabled: Optional[bool] = None
    sync_interval_minutes: Optional[int] = None


@router.get("/settings")
def get_app_settings(db: Session = Depends(get_db)):
    data = all_settings(db)
    return {
        "settings": data,
        "defaults": {
            "stage_mapping": DEFAULT_STAGE_MAPPING,
            "followup_rules": DEFAULT_FOLLOWUP_RULES,
        },
        "runtime": {
            "timezone": settings.timezone,
            "database_url": settings.database_url.split("/")[-1],
            "resimpli_base_url": settings.resimpli_base_url,
            "resimpli_api_key_configured": bool(settings.resimpli_api_key.strip()),
            "resimpli_mock": settings.resimpli_mock,
            "sync_interval_minutes": settings.sync_interval_minutes,
            "ai_enabled": settings.ai_enabled,
            "ollama_base_url": settings.ollama_base_url,
            "ollama_model": settings.ollama_model,
            "upload_dir": settings.upload_dir,
        },
        "pipeline": {
            "stages": [{"key": k, **v} for k, v in sorted(STAGES.items(), key=lambda kv: kv[1]["order"])],
            "contact_outcomes": [{"key": k, **v} for k, v in CONTACT_OUTCOMES.items()],
            "completion_outcomes": COMPLETION_OUTCOMES,
        },
    }


@router.put("/settings")
def put_settings(payload: SettingsPayload, db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    if data.get("followup_rules") is not None:
        update_followup_rules(db, data["followup_rules"])
        data.pop("followup_rules")
    if data.get("sync_enabled") is not None:
        set_setting(db, "sync_enabled", bool(data["sync_enabled"]))
    if data.get("sync_interval_minutes") is not None:
        set_setting(db, "sync_interval_minutes", int(data["sync_interval_minutes"]))
    if data.get("stage_mapping") is not None:
        set_setting(db, "stage_mapping", data["stage_mapping"])
        data.pop("stage_mapping")
    if data.get("ui") is not None:
        set_setting(db, "ui", data["ui"])
        data.pop("ui")
    audit(db, "settings.update", "settings", None, {"keys": sorted(data.keys())})
    return all_settings(db)


@router.get("/settings/followup-rules")
def get_rules(db: Session = Depends(get_db)):
    return {"rules": followup_rules(db), "defaults": DEFAULT_FOLLOWUP_RULES}


@router.put("/settings/followup-rules")
def put_rules(payload: dict[str, Any], db: Session = Depends(get_db)):
    return {"rules": update_followup_rules(db, payload), "defaults": DEFAULT_FOLLOWUP_RULES}


@router.get("/audit")
def audit_log(limit: int = 100, action: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        query = query.filter(AuditLog.action == action)
    items = query.limit(limit).all()
    return {
        "items": [
            {
                "id": a.id,
                "action": a.action,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "detail": a.detail,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in items
        ],
        "total": len(items),
    }
