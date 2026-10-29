"""Portable, verifiable backups for PostgreSQL.

``pg_dump`` is not available on every host and cannot be installed from inside a
running application, so the backup this app always produces is a logical one: one
gzipped NDJSON file holding every row of every table, preceded by a manifest that
records the row count per table. Writing, verifying and restoring use only the
database connection the app already has.

The manifest is the point. "The file exists" is not a backup; a file that has been
re-read, parsed, and whose row counts match the counts taken at write time is.

Nothing here is imported by the request path except through ``backups``, and the
restore path is deliberately only reachable from the command line.
"""

from __future__ import annotations

import base64
import gzip
import json
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
import uuid

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine

FORMAT = "acq-ndjson-v1"
MANIFEST_KEY = "__manifest__"
CHUNK = 500


def _encode(value):
    """JSON-safe stand-in that keeps the original type recoverable."""
    if isinstance(value, datetime):
        return {"$t": value.isoformat()}
    if isinstance(value, date):
        return {"$d": value.isoformat()}
    if isinstance(value, time):
        return {"$c": value.isoformat()}
    if isinstance(value, Decimal):
        return {"$n": str(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"$b": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, uuid.UUID):
        return {"$u": str(value)}
    raise TypeError(f"Cannot serialise {type(value).__name__} in a backup")


def _decode(value):
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if isinstance(value, dict):
        if len(value) == 1:
            (key, inner), = value.items()
            if key == "$t":
                return datetime.fromisoformat(inner)
            if key == "$d":
                return date.fromisoformat(inner)
            if key == "$c":
                return time.fromisoformat(inner)
            if key == "$n":
                return Decimal(inner)
            if key == "$b":
                return base64.b64decode(inner)
            if key == "$u":
                return uuid.UUID(inner)
        return {key: _decode(inner) for key, inner in value.items()}
    return value


def tables_for(engine: Engine) -> list:
    """Every mapped table that actually exists, in dependency order.

    The models are imported here on purpose: a script that imports this module without
    the application would otherwise see an empty metadata object and write a backup
    containing no tables at all, which verifies perfectly and restores nothing.
    """
    from ..db import Base
    from .. import models  # noqa: F401 - populates Base.metadata

    existing = set(inspect(engine).get_table_names())
    return [table for table in Base.metadata.sorted_tables if table.name in existing]


def _revision(connection) -> str | None:
    try:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # noqa: BLE001 - a pre-migration database simply has no row
        return None


def create(engine: Engine, folder: Path, reason: str, stamp: str) -> Path:
    """Write ``<folder>/acquisitions-<stamp>-<reason>.ndjson.gz`` and verify it."""
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = folder / f"acquisitions-{stamp}-{reason}.ndjson.gz"
    temporary = destination.with_suffix(".gz.partial")
    counts: dict[str, int] = {}
    tables = tables_for(engine)
    try:
        with engine.connect() as connection:
            manifest = {
                "format": FORMAT,
                "database": "postgresql",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "alembic_revision": _revision(connection),
                "server_version": connection.execute(text("SHOW server_version")).scalar(),
                "tables": counts,
            }
            with gzip.open(temporary, "wt", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({MANIFEST_KEY: manifest}, default=_encode) + "\n")
                for table in tables:
                    written = 0
                    result = connection.execution_options(stream_results=True).execute(select(table))
                    for row in result.mappings().yield_per(CHUNK):
                        handle.write(json.dumps({"t": table.name, "r": dict(row)}, default=_encode) + "\n")
                        written += 1
                    counts[table.name] = written
            # The manifest is written first and its counts mutate as rows are copied,
            # so rewrite the first line with the final counts before the file is named.
        _rewrite_manifest(temporary, manifest)
        verify(temporary, expected=counts)
        temporary.chmod(0o600)
        temporary.replace(destination)
        return destination
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _rewrite_manifest(path: Path, manifest: dict) -> None:
    """Replace the manifest line with the completed one, streaming the rest through."""
    replacement = path.with_suffix(".manifest.partial")
    with gzip.open(path, "rt", encoding="utf-8") as source, gzip.open(
        replacement, "wt", encoding="utf-8", newline="\n"
    ) as target:
        source.readline()
        target.write(json.dumps({MANIFEST_KEY: manifest}, default=_encode) + "\n")
        for line in source:
            target.write(line)
    replacement.replace(path)


def read_manifest(path: Path) -> dict:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            first = handle.readline()
    except OSError as error:
        raise ValueError(f"Backup is not a readable gzip file: {error}") from None
    try:
        document = json.loads(first)
        manifest = document[MANIFEST_KEY]
    except (ValueError, KeyError, TypeError):
        raise ValueError("Not an Acquisitions logical backup: the first line is not a manifest") from None
    if manifest.get("format") != FORMAT:
        raise ValueError(f"Unsupported backup format: {manifest.get('format')!r}")
    return manifest


def verify(path: Path, expected: dict | None = None) -> dict:
    """Re-read the whole file. Returns the manifest; raises ValueError if anything is off.

    Every line must parse, each row must name a table the manifest knows, and the
    counts must match -- both what the manifest claims and, when given, what the
    writer counted. A truncated gzip fails to decompress and is caught here.
    """
    manifest = read_manifest(path)
    # Start from the declared tables so a table with no rows still counts as zero
    # rather than disappearing from the comparison.
    counted: dict[str, int] = {name: 0 for name in manifest.get("tables", {})}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            handle.readline()
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                counted[row["t"]] = counted.get(row["t"], 0) + 1
    except (OSError, EOFError, ValueError, KeyError) as error:
        raise ValueError(f"Backup is damaged: {error}") from None
    declared = manifest.get("tables", {})
    if counted != declared:
        raise ValueError("Backup row counts do not match its manifest")
    if expected is not None and counted != expected:
        raise ValueError("Backup row counts do not match what was written")
    return manifest


def _sequence_reset(connection, table) -> None:
    """Point the sequence at the highest id, so the next insert does not collide."""
    pk = [column.name for column in table.primary_key.columns]
    if len(pk) != 1 or not table.name:
        return
    column = table.primary_key.columns[pk[0]]
    # SQLAlchemy reports the default as "auto", not True: comparing to True skips
    # every ordinary integer primary key and leaves the sequence at its old value.
    if column.autoincrement not in (True, "auto") or column.type.python_type is not int:
        return
    connection.execute(
        text(
            "SELECT setval("
            "  pg_get_serial_sequence(:table, :column),"
            "  COALESCE((SELECT MAX(" + connection.dialect.identifier_preparer.quote(column.name) + ")"
            "            FROM " + connection.dialect.identifier_preparer.quote(table.name) + "), 0) + 1,"
            "  false)"
        ),
        {"table": table.name, "column": column.name},
    )


def restore(engine: Engine, path: Path) -> dict:
    """Replace this database's rows with the backup's. Destructive; caller confirms.

    Rows are deleted in reverse dependency order and inserted in dependency order, so
    foreign keys hold at every step without needing a superuser to disable them.
    """
    manifest = verify(path)
    tables = {table.name: table for table in tables_for(engine)}
    unknown = set(manifest["tables"]) - set(tables)
    if unknown:
        raise ValueError(
            "This backup contains tables this version does not have ("
            + ", ".join(sorted(unknown))
            + "); upgrade the application before restoring it"
        )
    payload: dict[str, list] = {name: [] for name in tables}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        handle.readline()
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            payload[row["t"]].append(_decode(row["r"]))
    with engine.begin() as connection:
        for name in reversed([table.name for table in tables.values()]):
            connection.execute(tables[name].delete())
        for name in [table.name for table in tables.values()]:
            rows = payload[name]
            for start in range(0, len(rows), CHUNK):
                connection.execute(tables[name].insert(), rows[start : start + CHUNK])
        for table in tables.values():
            _sequence_reset(connection, table)
    return {"restored_from": path.name, "tables": manifest["tables"]}
