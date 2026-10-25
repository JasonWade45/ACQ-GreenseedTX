from apscheduler.schedulers.background import BackgroundScheduler
from .config import get_settings
from .db import SessionLocal
from .models import AppSetting
from .services.sync import begin_sync, sync_run

scheduler = BackgroundScheduler(daemon=True, timezone="UTC")


def scheduled_sync():
    try:
        with SessionLocal() as db:
            run = begin_sync(db, get_settings())
            run_id = run.id
        sync_run(run_id)
    except ValueError:
        pass  # Existing run; max_instances/coalescing also prevent overlaps.


def configure_scheduler(db, enabled=None, interval=None):
    settings = get_settings()
    stored = db.get(AppSetting, "scheduler")
    value = (
        dict(stored.value)
        if stored
        else {"enabled": settings.sync_enabled, "interval_minutes": settings.sync_interval_minutes}
    )
    if enabled is not None:
        value["enabled"] = enabled
    if interval is not None:
        value["interval_minutes"] = interval
    if stored:
        stored.value = value
    else:
        db.add(AppSetting(key="scheduler", value=value))
    db.commit()
    if scheduler.get_job("crm_sync"):
        scheduler.remove_job("crm_sync")
    if value["enabled"]:
        scheduler.add_job(
            scheduled_sync,
            "interval",
            minutes=value["interval_minutes"],
            id="crm_sync",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
    return value
