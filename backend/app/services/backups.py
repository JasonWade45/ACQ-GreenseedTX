"""Scheduled, rotating SQLite backups that never touch a live connection unsafely.

The database is copied with SQLite's own online-backup API against a read-only
connection, then verified with ``PRAGMA integrity_check``. A file only appears
under its final name after the copy passed verification, so a half-written
backup can never be mistaken for a good one.
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

NAME = re.compile(r"^acquisitions-\d{8}T\d{6}Z-(scheduled|manual)\.db$")


def database_path(url: str) -> Path:
    """Resolve a file-backed SQLite URL, refusing anything we cannot copy safely."""
    if not url.startswith("sqlite:///") or ":memory:" in url:
        raise ValueError("Automatic backups support a file-backed SQLite database only")
    return Path(url.removeprefix("sqlite:///")).resolve()


def backup_directory(database: Path) -> Path:
    return database.parent / "backups"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def create_backup(url: str, reason: str = "scheduled") -> Path:
    """Write a verified copy and return its path. Raises instead of leaving junk."""
    if reason not in {"scheduled", "manual"}:
        reason = "manual"
    source = database_path(url)
    if not source.is_file():
        raise ValueError("Database is not initialized; nothing to back up.")
    folder = backup_directory(source)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = folder / f"{source.stem}-{_stamp()}-{reason}.db"
    temporary = destination.with_suffix(".db.partial")
    try:
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
            with sqlite3.connect(temporary) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup integrity check failed; the copy was discarded.")
                if list(dst.execute("PRAGMA foreign_key_check")):
                    raise ValueError("Backup foreign-key check failed; the copy was discarded.")
                # The live database runs in WAL mode, so the copy may too. Fold the log into
                # the main file and leave no -wal/-shm sidecars, otherwise renaming would
                # split the backup and silently drop the newest writes.
                dst.execute("PRAGMA journal_mode=DELETE")
        _remove_sidecars(temporary)
        os.chmod(temporary, 0o600)
        temporary.replace(destination)
        return destination
    except Exception:
        _remove_sidecars(temporary)
        temporary.unlink(missing_ok=True)
        raise


def _remove_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def list_backups(url: str) -> list[dict]:
    """Newest first. Ignores partial files and anything not created by this app."""
    source = database_path(url)
    folder = backup_directory(source)
    if not folder.is_dir():
        return []
    items = []
    for path in folder.iterdir():
        if not path.is_file() or not NAME.match(path.name):
            continue
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                "reason": "scheduled" if path.name.endswith("-scheduled.db") else "manual",
            }
        )
    return sorted(items, key=lambda item: item["name"], reverse=True)


def prune(url: str, keep: int) -> list[str]:
    """Delete the oldest scheduled backups beyond ``keep``. Manual copies are never pruned."""
    if keep < 1:
        raise ValueError("Keep at least one backup")
    source = database_path(url)
    folder = backup_directory(source)
    if not folder.is_dir():
        return []
    scheduled = [p for p in sorted(folder.iterdir()) if p.is_file() and p.name.endswith("-scheduled.db")]
    removed = []
    for path in scheduled[:-keep] if len(scheduled) > keep else []:
        path.unlink(missing_ok=True)
        removed.append(path.name)
    return removed


def resolve_backup(url: str, name: str) -> Path:
    """Map a requested filename to a path inside the backup folder, or refuse."""
    if not NAME.match(name or ""):
        raise ValueError("Unknown backup name")
    source = database_path(url)
    path = (backup_directory(source) / name).resolve()
    if path.parent != backup_directory(source):
        raise ValueError("Unknown backup name")
    if not path.is_file():
        raise ValueError("Backup not found")
    return path
