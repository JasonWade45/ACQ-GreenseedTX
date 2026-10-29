"""Copy an existing SQLite workspace into PostgreSQL, without touching the source.

The SQLite file is opened read-only, so a failed run cannot damage the workspace the
person is still using. Every row is converted to the type its column declares before
it is written, because SQLite stores booleans as 0/1, timestamps as text and JSON as
text, and PostgreSQL will not accept any of those in a typed column.

Re-running is safe and expected: rows already present are skipped by primary key, and
the report says how many were inserted this time. Sequences are pointed past the
highest copied id, so the next row the application inserts cannot collide with an old
one, and the script verifies its own result with a count per table.

Usage (the target is migrated first, and nothing is written without --confirm):

    DATABASE_URL=postgresql://... python scripts/migrate_sqlite_to_postgres.py --dry-run
    DATABASE_URL=postgresql://... python scripts/migrate_sqlite_to_postgres.py \
        --confirm "MIGRATE TO POSTGRES"
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

CONFIRM = "MIGRATE TO POSTGRES"
# SQLite's own bookkeeping, and the migration table which the target already owns.
IGNORED = {"sqlite_sequence", "sqlite_stat1", "alembic_version"}


def _settings_source():
    from app.config import get_settings

    return Path(get_settings().database_url.removeprefix("sqlite:///"))


def _open_source(path: Path):
    if not path.is_file():
        raise ValueError(f"No SQLite workspace at {path}")
    # mode=ro: this script must be incapable of writing to the original.
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)


def _base_type(kind):
    """The underlying SQLAlchemy type, unwrapped from any decorator."""
    from sqlalchemy.types import TypeDecorator

    seen = 0
    while isinstance(kind, TypeDecorator) and seen < 5:
        kind = kind.impl
        seen += 1
    return kind


def _convert(value, column):
    """Turn a SQLite value into what the PostgreSQL column declares.

    Dispatch is on the underlying type, not ``python_type``: a decorated timestamp and
    a JSON column both report ``object``, which is how a raw string reaches a datetime
    bind parameter and fails at insert time.
    """
    from datetime import date as date_type
    from datetime import datetime as datetime_type
    from datetime import time as time_type
    from datetime import timezone

    from sqlalchemy import Boolean, Date, DateTime, JSON, Numeric, Time
    from sqlalchemy import Float

    if value is None:
        return None
    kind = _base_type(column.type)
    if isinstance(kind, Boolean):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}
    if isinstance(kind, DateTime):
        if not isinstance(value, datetime_type):
            try:
                value = datetime_type.fromisoformat(str(value).strip().replace("Z", "+00:00"))
            except ValueError:
                return None
        # SQLite stores naive UTC. The application's bind layer refuses a naive value
        # (it would be ambiguous), so the UTC offset is restored here, once.
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(kind, Date):
        try:
            return date_type.fromisoformat(str(value).strip()[:10])
        except ValueError:
            return None
    if isinstance(kind, Time):
        try:
            return time_type.fromisoformat(str(value).strip())
        except ValueError:
            return None
    if isinstance(kind, JSON):
        if isinstance(value, (dict, list)):
            return value
        text = str(value).strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError:
            return None
    if isinstance(kind, Float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(kind, Numeric):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    return value


def _target_tables(engine):
    from sqlalchemy import inspect

    from app import models  # noqa: F401 - populates Base.metadata
    from app.db import Base

    existing = set(inspect(engine).get_table_names())
    return [table for table in Base.metadata.sorted_tables if table.name in existing]


def run(source_path: Path, url: str, confirm: str, dry_run: bool, limit: int | None) -> int:
    from sqlalchemy import text
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.db import make_engine

    if not url.startswith("postgresql"):
        raise ValueError("DATABASE_URL must point at the PostgreSQL database you are migrating into")
    if confirm != CONFIRM and not dry_run:
        raise ValueError(f'Nothing was written. Pass --confirm "{CONFIRM}" or --dry-run.')
    engine = make_engine(url, pool_size=1)
    report: list[tuple[str, int, int, int]] = []
    try:
        tables = _target_tables(engine)
        if not tables:
            raise ValueError("The PostgreSQL database has no application tables. Run 'manage.py migrate' first.")
        with engine.connect() as resolved:
            revision = resolved.execute(text("SELECT version_num FROM alembic_version")).scalar()
        print(f"Target revision: {revision}")
        print(f"Source (read-only): {source_path}")
        if dry_run:
            print("Dry run: reading counts only, writing nothing.")
        source = _open_source(source_path)
        source.row_factory = sqlite3.Row
        try:
            present = {
                row[0]
                for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            unknown = sorted(present - {table.name for table in tables} - IGNORED)
            if unknown:
                print("Not in this schema, not copied: " + ", ".join(unknown))
            for table in tables:
                if table.name not in present:
                    report.append((table.name, 0, 0, 0))
                    continue
                columns = [column for column in table.columns]
                names = {column.name for column in columns}
                source_columns = [row[1] for row in source.execute(f'PRAGMA table_info("{table.name}")')]
                missing_in_source = [c for c in names if c not in source_columns]
                if missing_in_source:
                    raise ValueError(
                        f"{table.name}: the SQLite file has no column(s) {', '.join(sorted(missing_in_source))}. "
                        "Migrate the SQLite file to the current version first (manage.py migrate)."
                    )
                rows = source.execute(f'SELECT * FROM "{table.name}"').fetchall()
                payload = [
                    {column.name: _convert(row[column.name], column) for column in columns} for row in rows
                ]
                if limit is not None:
                    payload = payload[:limit]
                if dry_run:
                    report.append((table.name, len(payload), 0, len(payload)))
                    continue
                inserted = 0
                if payload:
                    with engine.begin() as connection:
                        pk = [column.name for column in table.primary_key.columns] or ["id"]
                        for start in range(0, len(payload), 500):
                            batch = payload[start : start + 500]
                            statement = (
                                pg_insert(table)
                                .values(batch)
                                .on_conflict_do_nothing(index_elements=pk)
                                .returning(table.c[pk[0]])
                            )
                            inserted += len(connection.execute(statement).fetchall())
                with engine.connect() as connection:
                    total = connection.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar()
                report.append((table.name, len(payload), inserted, total))
            if not dry_run:
                _reset_sequences(engine, tables)
        finally:
            source.close()
    finally:
        engine.dispose()

    print()
    print(f"{'table':<28}{'read':>8}{'inserted':>10}{'in target':>11}")
    for name, read, inserted, total in report:
        flag = "" if read == total else "  <-- check"
        print(f"{name:<28}{read:>8}{inserted:>10}{total:>11}{flag}")
    read_total = sum(item[1] for item in report)
    inserted_total = sum(item[2] for item in report)
    print(f"\n{read_total} row(s) read, {inserted_total} inserted, {len(report)} table(s) examined.")
    if not dry_run:
        short = [name for name, read, _, total in report if read > total]
        if short:
            raise ValueError(
                "These tables hold fewer rows than the source: " + ", ".join(short) + ". Nothing was deleted; re-run to see what fails."
            )
        print("The SQLite file was not modified. Keep it until the new database has been checked.")
    return 0


def _reset_sequences(engine, tables) -> None:
    """Point every id sequence past the highest copied id."""
    from sqlalchemy import text

    with engine.begin() as connection:
        for table in tables:
            pk = list(table.primary_key.columns)
            if len(pk) != 1:
                continue
            column = pk[0]
            # SQLAlchemy reports the default as "auto", not True.
            if column.autoincrement not in (True, "auto") or column.type.python_type is not int:
                continue
            connection.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence(:table, :column), "
                    "COALESCE((SELECT MAX(" + column.name + ") FROM " + table.name + "), 0) + 1, false)"
                ),
                {"table": table.name, "column": column.name},
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy a SQLite workspace into PostgreSQL")
    parser.add_argument("--source", help="SQLite file (default: the configured workspace)")
    parser.add_argument("--database-url", help="PostgreSQL URL (default: DATABASE_URL)")
    parser.add_argument("--confirm", default="", help=f'Type "{CONFIRM}" to write anything')
    parser.add_argument("--dry-run", action="store_true", help="Print the work, change nothing")
    parser.add_argument("--limit", type=int, default=None, help="Copy at most this many rows per table")
    args = parser.parse_args()
    source = Path(args.source).expanduser().resolve() if args.source else _settings_source()
    url = args.database_url or os.environ.get("DATABASE_URL", "")
    try:
        return run(source, url, args.confirm, args.dry_run, args.limit)
    except (ValueError, OSError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
