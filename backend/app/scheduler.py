"""Background scheduler for periodic REsimpli synchronisation.

Runs inside the FastAPI process using APScheduler, which works fine for a
single-user local deployment on Windows. The manual "Sync now" button always
remains available, and the scheduler can be enabled/disabled at runtime.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.db import SessionLocal

logger = logging.getLogger("acquisitions.scheduler")

_lock = threading.Lock()
_scheduler: Optional[BackgroundScheduler] = None
_state: dict[str, Any] = {
    "enabled": False,
    "interval_minutes": settings.sync_interval_minutes,
    "last_started": None,
    "last_job_at": None,
    "last_job_result": None,
    "last_error": None,
}


def _job() -> None:  # pragma: no cover - exercised indirectly in tests
    from app.services.sync_service import run_sync

    db = SessionLocal()
    try:
        _state["last_job_at"] = datetime.utcnow().isoformat()
        run = run_sync(db, trigger="scheduled")
        _state["last_job_result"] = run.result
        _state["last_error"] = run.error
    except Exception as exc:  # noqa: BLE001
        logger.exception("Scheduled sync failed")
        _state["last_error"] = str(exc)
        _state["last_job_result"] = "failed"
    finally:
        db.close()


def start_scheduler(interval_minutes: Optional[int] = None) -> dict[str, Any]:
    global _scheduler
    with _lock:
        minutes = int(interval_minutes or settings.sync_interval_minutes or 30)
        minutes = max(5, minutes)
        if _scheduler is None:
            _scheduler = BackgroundScheduler(timezone="UTC")
        if _scheduler.running:
            _scheduler.remove_job("resimpli_sync") if _scheduler.get_job("resimpli_sync") else None
        _scheduler.add_job(
            _job,
            trigger=IntervalTrigger(minutes=minutes),
            id="resimpli_sync",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        if not _scheduler.running:
            _scheduler.start()
        _state.update(
            {
                "enabled": True,
                "interval_minutes": minutes,
                "last_started": datetime.utcnow().isoformat(),
                "last_error": None,
            }
        )
    return scheduler_state()


def stop_scheduler() -> dict[str, Any]:
    global _scheduler
    with _lock:
        if _scheduler and _scheduler.running:
            _scheduler.shutdown(wait=False)
        _scheduler = None
        _state["enabled"] = False
    return scheduler_state()

def scheduler_state() -> dict[str, Any]:
    return dict(_state)


def configure_scheduler(enabled: bool, interval_minutes: int) -> dict[str, Any]:
    minutes = max(5, int(interval_minutes or settings.sync_interval_minutes or 30))
    if enabled:
        return start_scheduler(minutes)
    stop_scheduler()
    # Keep the requested cadence visible even while the scheduler is off.
    _state["interval_minutes"] = minutes
    return scheduler_state()
