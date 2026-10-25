"""Fail closed on the incompatible GitHub schema; backup before our additive upgrade."""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

HEAD = "0a6d91cf17b2"


def protect_before_upgrade(url):
    if not url.startswith("sqlite:///") or ":memory:" in url:
        return None
    path = Path(url.removeprefix("sqlite:///")).resolve()
    if not path.exists():
        return None
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source:
        source.execute("PRAGMA trusted_schema=OFF")
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "leads" in tables:
            fields = {row[1] for row in source.execute("PRAGMA table_info(leads)")}
            if not {"stage_code", "source_data", "full_name"}.issubset(fields):
                raise ValueError(
                    "Incompatible GitHub/Next UUID database. Nothing migrated. Keep DATABASE_URL pointing to the unified data/acquisitions.db; use MERGE-WORKSPACES.cmd for a reviewed, backup-first transfer instead."
                )
        elif tables:
            raise ValueError("Unknown non-empty database schema; no migrations were run")
        version = (
            source.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            if "alembic_version" in tables
            else None
        )
        if version == HEAD or not tables:
            return None
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError(
                "Database integrity failed before upgrade. Keep the original and restore a trusted backup."
            )
        folder = path.parent / "backups"
        folder.mkdir(exist_ok=True, mode=0o700)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = folder / (path.stem + "-before-v1.2-" + stamp + ".db")
        with sqlite3.connect(backup) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Pre-upgrade backup failed integrity check; no migration ran")
        backup.chmod(0o600)
        return backup
