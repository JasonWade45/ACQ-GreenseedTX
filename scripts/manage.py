"""Maintenance tools. Does not print configuration secrets or seller payloads."""

import argparse
from datetime import datetime, timezone
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)


def database_path():
    from app.config import get_settings

    url = get_settings().database_url
    if not url.startswith("sqlite:///") or ":memory:" in url:
        raise ValueError("This maintenance command supports a file-backed SQLite database only")
    return Path(url.removeprefix("sqlite:///")).resolve()


def private_permissions(path):
    try:
        path.chmod(0o600)
    except OSError:
        pass


def backup(output):
    source = database_path()
    destination = Path(output).expanduser().resolve()
    if not source.exists():
        raise ValueError("Database is not initialized. Start the application or run migrate first.")
    if source == destination:
        raise ValueError("Backup destination must differ from the live database")
    if destination.exists():
        raise ValueError("Backup destination already exists; choose a new filename to avoid overwriting")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)
            result = dst.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise ValueError("Backup integrity check failed")
    private_permissions(destination)
    print(f"Consistent SQLite backup created: {destination}")


def restore(input_path, confirm):
    if confirm != "RESTORE LOCAL DATABASE":
        raise ValueError("Stop the app first. Restore requires --confirm 'RESTORE LOCAL DATABASE'.")
    source = Path(input_path).expanduser().resolve()
    destination = database_path()
    if source == destination or not source.is_file():
        raise ValueError("Choose a different, existing trusted SQLite backup file.")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
        tables = {row[0] for row in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"leads", "pipeline_stages", "alembic_version"}.issubset(tables):
            raise ValueError("This does not look like an Acquisitions Assistant backup.")
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or list(src.execute("PRAGMA foreign_key_check")):
            raise ValueError("Backup integrity/foreign-key check failed; nothing restored.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            recovery = destination.with_name(destination.name + ".pre-restore-" + stamp + ".bak")
            with sqlite3.connect(destination) as previous, sqlite3.connect(recovery) as previous_copy:
                previous.backup(previous_copy)
            private_permissions(recovery)
            print(f"Pre-restore recovery backup: {recovery}")
        with sqlite3.connect(destination) as dst:
            src.backup(dst)
    private_permissions(destination)
    print(f"Restored trusted backup into {destination}. Run migrate and check before starting the app.")


def main():
    parser = argparse.ArgumentParser(description="Acquisitions Assistant maintenance")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("migrate")
    b = sub.add_parser("backup")
    b.add_argument("--output", required=True)
    r = sub.add_parser("restore", help="Stop the app before restoring a trusted SQLite backup")
    r.add_argument("--input", required=True)
    r.add_argument("--confirm", required=True)
    sub.add_parser("check")
    f = sub.add_parser(
        "fixture-sync", help="Explicitly load fictional integration records into the configured database"
    )
    f.add_argument("--confirm", required=True, choices=["LOAD SYNTHETIC"])
    args = parser.parse_args()
    try:
        if args.action == "migrate":
            from app.main import migrate
            from app.db import SessionLocal
            from app.seed import initialize_defaults

            migrate()
            with SessionLocal() as db:
                initialize_defaults(db)
            print("Schema migrated and default pipeline initialized (no seller data seeded).")
        elif args.action == "backup":
            backup(args.output)
        elif args.action == "restore":
            restore(args.input, args.confirm)
        elif args.action == "check":
            with sqlite3.connect(database_path().as_uri() + "?mode=ro", uri=True) as db:
                integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
                violations = len(db.execute("PRAGMA foreign_key_check").fetchall())
                print("Integrity:", integrity)
                print("Foreign-key violations:", violations)
                if integrity != "ok" or violations:
                    raise ValueError("Database validation failed")
        elif args.action == "fixture-sync":
            from app.config import get_settings
            from app.db import SessionLocal
            from app.services.sync import begin_sync, sync_run
            from app.models import SyncRun

            settings = get_settings().model_copy(update={"resimpli_mode": "fixture"})
            with SessionLocal() as db:
                run = begin_sync(db, settings)
            sync_run(run.id, settings=settings)
            with SessionLocal() as db:
                r = db.get(SyncRun, run.id)
                print(
                    f"Synthetic sync #{r.id}: {r.result}; fetched={r.fetched}, created={r.created}, updated={r.updated}, failed={r.failed}"
                )
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
