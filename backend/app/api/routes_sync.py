"""Sync status, manual trigger, scheduler control and reference lookups."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import SyncRun
from app.scheduler import configure_scheduler, scheduler_state
from app.services.audit import audit
from app.services.resimpli_client import ResimpliAuthError, ResimpliError
from app.services.sync_service import get_client, is_mock, run_sync, serialize_sync_run, sync_state

router = APIRouter(tags=["sync"])


class SchedulerPayload(BaseModel):
    enabled: bool
    interval_minutes: Optional[int] = None


@router.get("/sync/status")
def status(db: Session = Depends(get_db)):
    return sync_state(db)


@router.get("/sync/runs")
def runs(limit: int = 25, db: Session = Depends(get_db)):
    rows = db.query(SyncRun).order_by(SyncRun.started_at.desc()).limit(limit).all()
    return {"items": [serialize_sync_run(r) for r in rows]}


@router.post("/sync/run")
def trigger(db: Session = Depends(get_db), full: bool = Query(default=True)):
    run = run_sync(db, trigger="manual")
    audit(db, "sync.run", "sync_run", run.id, {"result": run.result, "full": full})
    return serialize_sync_run(run)


@router.post("/sync/scheduler")
def scheduler(payload: SchedulerPayload, db: Session = Depends(get_db)):
    from app.services.settings_service import set_setting

    minutes = payload.interval_minutes or settings.sync_interval_minutes
    state = configure_scheduler(payload.enabled, minutes)
    set_setting(db, "sync_enabled", payload.enabled)
    set_setting(db, "sync_interval_minutes", int(minutes))
    audit(db, "sync.scheduler", "settings", None, {"enabled": payload.enabled, "interval_minutes": minutes})
    return state


@router.post("/sync/test-connection")
def test_connection():
    client = get_client()
    try:
        info = client.get_user_info()
        return {"ok": True, "mock": is_mock(), "info": info}
    except ResimpliAuthError as exc:
        return {"ok": False, "mock": is_mock(), "error": str(exc), "kind": "auth"}
    except ResimpliError as exc:
        return {"ok": False, "mock": is_mock(), "error": str(exc), "kind": "api"}
    finally:
        client.close()


@router.get("/sync/reference/reference-data")
def reference_data(db: Session = Depends(get_db)):
    """Account reference data used when creating leads in REsimpli."""
    if is_mock():
        return {
            "mock": True,
            "message": "Configure RESIMPLI_API_KEY to load your account pipelines, markets and campaigns.",
            "pipelines": [],
            "markets": [],
            "campaigns": [],
            "users": [],
            "tags": [],
        }
    client = get_client()
    try:
        pipelines = client.get_pipelines(module_type=1)
        return {
            "mock": False,
            "pipelines": pipelines,
            "markets": client.markets(),
            "campaigns": client.marketing_campaigns(),
            "users": client.users(),
            "tags": client.tags(),
        }
    except ResimpliAuthError as exc:
        raise ValueError(str(exc)) from exc
    except ResimpliError as exc:
        raise ValueError(f"Could not load reference data: {exc}") from exc
    finally:
        client.close()


@router.get("/sync/state")
def state():
    return scheduler_state()
