from apscheduler.schedulers.background import BackgroundScheduler
from .config import get_settings
from .db import SessionLocal
from .models import AppSetting
from .services.backups import copy_to_second_folder, create_backup, prune
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


def scheduled_backup():
    """Nightly verified copy. SQLite handles its own locking, so no session is needed."""
    settings = get_settings()
    try:
        created = create_backup(settings.database_url, reason="scheduled")
        prune(settings.database_url, settings.backup_keep)
        with SessionLocal() as db:
            from .models import AuditLog

            row = db.get(AppSetting, "backup_second_folder")
            second = (row.value or {}).get("path") if row and isinstance(row.value, dict) else None
            mirror = copy_to_second_folder(settings.database_url, created, second)
            if row is not None and mirror.get("configured"):
                row.value = {"path": second, "status": mirror}
            db.add(
                AuditLog(
                    action="backup_created",
                    details={
                        "file": created.name,
                        "reason": "scheduled",
                        "bytes": created.stat().st_size,
                        "second_folder": mirror,
                    },
                )
            )
            db.commit()
    except Exception:
        # A failing backup must never take the scheduler down; the log keeps the evidence.
        import logging

        logging.getLogger("uvicorn.error").exception("Scheduled backup failed")


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
    if scheduler.get_job("nightly_backup"):
        scheduler.remove_job("nightly_backup")
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
    if settings.backup_enabled:
        scheduler.add_job(
            scheduled_backup,
            "cron",
            hour=settings.backup_hour_utc,
            minute=0,
            id="nightly_backup",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
    return value
