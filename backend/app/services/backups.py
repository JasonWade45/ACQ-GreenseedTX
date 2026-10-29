"""Scheduled, rotating SQLite backups that never touch a live connection unsafely.

The database is copied with SQLite's own online-backup API against a read-only
connection, then verified with ``PRAGMA integrity_check``. A file only appears
under its final name after the copy passed verification, so a half-written
backup can never be mistaken for a good one.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# The prefix comes from the database filename, not a constant: a database called
# acq.db produced backups that were created, then invisible to listing, download and
# rotation because this pattern only accepted "acquisitions-...".
NAME = re.compile(r"^acquisitions-\d{8}T\d{6}Z-(scheduled|manual)\.db$")


def _name_pattern(database: Path) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(database.stem)}-\d{{8}}T\d{{6}}Z-(scheduled|manual)\.db$")


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
    src = None
    dst = None
    try:
        src = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        dst = sqlite3.connect(temporary)
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup integrity check failed; the copy was discarded.")
        if list(dst.execute("PRAGMA foreign_key_check")):
            raise ValueError("Backup foreign-key check failed; the copy was discarded.")
        dst.execute("PRAGMA journal_mode=DELETE")
        dst.commit()
        _remove_sidecars(temporary)
        os.chmod(temporary, 0o600)
        # Close before rename: Windows locks open file handles.
        dst.close()
        dst = None
        src.close()
        src = None
        temporary.replace(destination)
        return destination
    except Exception:
        if dst is not None:
            try:
                dst.close()
            except Exception:
                pass
        if src is not None:
            try:
                src.close()
            except Exception:
                pass
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
    pattern = _name_pattern(source)
    items = []
    for path in folder.iterdir():
        if not path.is_file() or not pattern.match(path.name):
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
    # Only files this module created are candidates. A user file that merely ends in
    # "-scheduled.db" must never be deleted by rotation.
    pattern = _name_pattern(source)
    scheduled = [
        p for p in sorted(folder.iterdir()) if p.is_file() and pattern.match(p.name) and p.name.endswith("-scheduled.db")
    ]
    removed = []
    for path in scheduled[:-keep] if len(scheduled) > keep else []:
        path.unlink(missing_ok=True)
        removed.append(path.name)
    return removed


def prune_policy(url: str, daily_keep: int = 14, weekly_keep: int = 8) -> list[str]:
    """Rotate scheduled backups: keep ``daily_keep`` newest daily plus one per
    week for the last ``weekly_keep`` weeks. Manual backups are never touched."""
    source = database_path(url)
    folder = backup_directory(source)
    if not folder.is_dir():
        return []
    pattern = _name_pattern(source)
    scheduled = [
        p
        for p in folder.iterdir()
        if p.is_file() and pattern.match(p.name) and p.name.endswith("-scheduled.db")
    ]
    if not scheduled:
        return []
    # Group by ISO week; keep the newest of each week.
    by_week: dict[tuple[int, int], list[Path]] = {}
    for p in scheduled:
        st = p.stat()
        dt = datetime.fromtimestamp(st.st_mtime, timezone.utc)
        by_week.setdefault((dt.isocalendar().year, dt.isocalendar().week), []).append(p)
    weekly_keep_set: set[Path] = set()
    for week in sorted(by_week)[-weekly_keep:]:
        weekly_keep_set.add(max(by_week[week], key=lambda p: p.stat().st_mtime))
    # Daily: newest daily_keep overall.
    daily_keep_set = set(sorted(scheduled, key=lambda p: p.stat().st_mtime, reverse=True)[:daily_keep])
    keep = daily_keep_set | weekly_keep_set
    removed = []
    for p in scheduled:
        if p not in keep:
            p.unlink(missing_ok=True)
            removed.append(p.name)
    return removed


def resolve_backup(url: str, name: str) -> Path:
    """Map a requested filename to a path inside the backup folder, or refuse."""
    source = database_path(url)
    if not _name_pattern(source).match(name or ""):
        raise ValueError("Unknown backup name")
    path = (backup_directory(source) / name).resolve()
    if path.parent != backup_directory(source):
        raise ValueError("Unknown backup name")
    if not path.is_file():
        raise ValueError("Backup not found")
    return path

def validate_second_folder(path: str) -> str:
    """Validate an optional second backup folder (e.g. a synced Google Drive folder).

    The folder must already exist and be writable; the app never creates it, so a
    typo cannot silently scatter backups somewhere unexpected. Nothing outside the
    files this app writes is ever read or deleted there.
    """
    target = Path(str(path)).expanduser()
    if not target.is_absolute():
        raise ValueError("Use an absolute path for the second backup folder")
    if not target.exists() or not target.is_dir():
        raise ValueError("The second backup folder does not exist")
    probe = target / ".acq-write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        raise ValueError(f"The second backup folder is not writable: {error}") from None
    return str(target.resolve())


def copy_to_second_folder(url: str, created: Path, second: str | None) -> dict:
    """Copy one completed backup into the second folder and report the outcome.

    Copy failures never delete or damage the primary backup; they are reported so the
    Backups panel and the briefing can show them instead of swallowing them.
    """
    if not second:
        return {"configured": False, "ok": True, "detail": "No second folder configured"}
    try:
        folder = Path(second).expanduser()
        if not folder.is_dir():
            raise ValueError("The second backup folder is not available")
        destination = folder / created.name
        shutil.copy2(created, destination)
        with sqlite3.connect(destination) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("The copy failed its integrity check and was removed")
        return {
            "configured": True,
            "ok": True,
            "folder": str(folder),
            "name": destination.name,
            "copied_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as error:  # reported, never fatal
        return {
            "configured": True,
            "ok": False,
            "folder": str(second),
            "detail": str(error),
            "copied_at": datetime.now(timezone.utc).isoformat(),
        }
