"""Runtime application settings stored in the database (with defaults)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AppSetting
from app.services.pipeline import DEFAULT_SETTINGS, clone_default_settings


def get_setting(db: Session, key: str) -> Any:
    row = db.get(AppSetting, key)
    if row is None:
        return clone_default_settings().get(key)
    return row.value


def set_setting(db: Session, key: str, value: Any) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()


def all_settings(db: Session) -> dict[str, Any]:
    out = clone_default_settings()
    for row in db.query(AppSetting).all():
        out[row.key] = row.value
    return out


def update_settings(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    for key, value in payload.items():
        if key not in DEFAULT_SETTINGS and key not in {"sync_enabled", "sync_interval_minutes"}:
            continue
        set_setting(db, key, value)
    return all_settings(db)


def stage_mapping(db: Session) -> dict[str, str]:
    mapping = get_setting(db, "stage_mapping") or {}
    return {str(k).lower(): str(v) for k, v in mapping.items() if v}


def followup_rules(db: Session) -> dict[str, Any]:
    rules = get_setting(db, "followup_rules") or {}
    merged = dict(DEFAULT_SETTINGS["followup_rules"])
    merged.update(rules or {})
    return merged


def update_followup_rules(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    merged = followup_rules(db)
    merged.update(payload or {})
    set_setting(db, "followup_rules", merged)
    return merged


def resimpli_lead_ids(db: Session) -> dict[str, Any]:
    stored = get_setting(db, "resimpli_lead_ids") or {}
    return dict(stored) if isinstance(stored, dict) else {}


def update_resimpli_lead_ids(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.import_service import EXTERNAL_KEYS

    clean = {
        str(k): str(v).strip()
        for k, v in (payload or {}).items()
        if str(k) in (*EXTERNAL_KEYS, "propertyType") and v and str(v).strip()
    }
    set_setting(db, "resimpli_lead_ids", clean)
    return clean
