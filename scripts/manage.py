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
            if result == "ok" and list(dst.execute("PRAGMA foreign_key_check")):
                result = "foreign key mismatch"
            # The header records the copy's journal mode, so a WAL source yields a WAL copy.
            # Fold the log in and leave one self-contained file behind.
            dst.execute("PRAGMA journal_mode=DELETE")
    if result != "ok":
        destination.unlink(missing_ok=True)
        raise ValueError(f"Backup integrity check failed ({result}); the copy was discarded")
    for suffix in ("-wal", "-shm", "-journal"):
        Path(str(destination) + suffix).unlink(missing_ok=True)
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


def adapter_check(limit):
    """Fetch a few real leads and report which mapped fields actually fill in.

    A wrong JSON path does not raise: it silently yields None, and a mistyped
    adapter then looks like "the source has no phone numbers". This prints how
    many of the sampled records produced a value for each field.
    """
    from itertools import islice

    from app.config import get_settings
    from app.services.resimpli import ResimpliClient

    settings = get_settings()
    client = ResimpliClient(settings)
    try:
        resource = client.adapter.leads
        records = list(islice(client.pages(resource.list_path, resource, limit=min(limit, 100)), limit))
    finally:
        client.close()
    if not records:
        raise ValueError("The source returned no leads to check; nothing was verified")
    print(f"Sampled {len(records)} lead(s). Fill rate only; no seller values are printed.")
    problems = []
    for field in sorted(resource.fields):
        filled = sum(1 for record in records if record.get(field) not in (None, ""))
        rate = round(100 * filled / len(records))
        marker = "ok" if filled else "NEVER FILLED"
        print(f"  leads.{field:<18} {filled}/{len(records)} ({rate}%) {marker}")
        if not filled:
            problems.append(field)
    if problems:
        raise ValueError(
            "These mapped fields never filled: "
            + ", ".join(problems)
            + ". The JSON path is probably wrong (a wrong path returns nothing without an error)."
        )
    print("Every mapped lead field produced a value on at least one record.")


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
    a = sub.add_parser(
        "adapter-check",
        help="Sample live leads and show which mapped fields actually fill (no values printed)",
    )
    a.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    try:
        if args.action == "migrate":
            from app.main import migrate
            from app.db import SessionLocal
            from app.seed import initialize_defaults
            from app.services import templates as template_service

            migrate()
            with SessionLocal() as db:
                initialize_defaults(db)
                # The startup path seeds the reviewed template library too, so a database
                # prepared here is already complete: the first start must not have to
                # write anything, and an update cannot look like it changed seller data.
                template_service.seed_templates(db)
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
        elif args.action == "adapter-check":
            adapter_check(max(1, min(args.limit, 25)))
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
