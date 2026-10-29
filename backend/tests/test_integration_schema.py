"""The REsimpli + Grok tables exist, and the database refuses the states that matter.

These assertions run against a real migrated SQLite file, not against the ORM, so a
migration that drifts from the models shows up here as a failure rather than as a
surprise on a user's machine.
"""

import os
import sqlite3

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from app.config import ROOT, get_settings
from app.db import make_engine
from app.models import Lead
from app.seed import initialize_defaults

NEW_TABLES = {
    "crm_pushes",
    "crm_note_outbox",
    "checklist_templates",
    "checklist_template_items",
    "lead_checklist_items",
    "grok_runs",
    "ai_checklist_suggestions",
}


@pytest.fixture
def migrated(tmp_path):
    """A throwaway database migrated to head; env.py reads the app settings, so set the URL there."""
    database = tmp_path / "migrated.db"
    url = "sqlite:///" + str(database)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "backend/migrations"))
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
    yield database


def _columns(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def _lead(database, name="Sync Test"):
    """Create one real lead through the ORM: the migrated schema, not a hand-written row."""
    engine = make_engine("sqlite:///" + str(database))
    try:
        with sessionmaker(bind=engine)() as session:
            initialize_defaults(session)
            lead = Lead(full_name=name)
            session.add(lead)
            session.commit()
            return lead.id
    finally:
        engine.dispose()


def _insert(db, table, values):
    """Insert one row, filling any other NOT NULL column with a benign default."""
    columns = {row[1]: row for row in db.execute(f"PRAGMA table_info({table})")}
    row = dict(values)
    for name, info in columns.items():
        if name in row or not info[3] or info[4] is not None:
            continue
        row[name] = 0 if any(k in info[2].upper() for k in ("INT", "BOOL", "FLOAT")) else ""
    db.execute(
        f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
        tuple(row.values()),
    )


def test_every_integration_table_is_created_by_the_migration(migrated):
    with sqlite3.connect(migrated) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert NEW_TABLES <= tables
        assert {"state", "resimpli_lead_id", "payload_hash", "last_error"} <= _columns(db, "crm_pushes")
        assert {"note_hash", "body", "state", "blocked_reason"} <= _columns(db, "crm_note_outbox")
        assert {"input_hash", "model_id", "purpose", "output"} <= _columns(db, "grok_runs")
        assert {"template_key", "title", "done", "source"} <= _columns(db, "lead_checklist_items")


def test_a_push_row_cannot_record_a_state_outside_the_known_set(migrated):
    lead_id = _lead(migrated)
    with sqlite3.connect(migrated) as db:
        _insert(db, "crm_pushes", {"lead_id": lead_id, "state": "pushed"})
        with pytest.raises(sqlite3.IntegrityError):
            _insert(db, "crm_pushes", {"lead_id": lead_id + 1, "state": "sent"})


def test_one_lead_has_at_most_one_push_mapping(migrated):
    lead_id = _lead(migrated)
    with sqlite3.connect(migrated) as db:
        _insert(db, "crm_pushes", {"lead_id": lead_id, "state": "pending"})
        with pytest.raises(sqlite3.IntegrityError):
            _insert(db, "crm_pushes", {"lead_id": lead_id, "state": "pushed"})


def test_the_same_note_hash_is_stored_once_per_lead(migrated):
    lead_id = _lead(migrated, "Note Test")
    with sqlite3.connect(migrated) as db:
        note = {"lead_id": lead_id, "note_hash": "a" * 64, "body": "[GreenSeed] one", "state": "blocked"}
        _insert(db, "crm_note_outbox", note)
        with pytest.raises(sqlite3.IntegrityError):
            _insert(db, "crm_note_outbox", note)


def test_a_grok_run_only_records_the_three_supported_purposes(migrated):
    with sqlite3.connect(migrated) as db:
        run = {"id": "r1", "purpose": "advisor", "model_id": "grok-4.3", "input_hash": "b" * 64}
        _insert(db, "grok_runs", run)
        with pytest.raises(sqlite3.IntegrityError):
            _insert(db, "grok_runs", {**run, "id": "r2", "purpose": "outreach"})


def test_a_checklist_item_cannot_claim_to_come_from_an_unknown_source(migrated):
    lead_id = _lead(migrated, "Checklist Test")
    with sqlite3.connect(migrated) as db:
        item = {"lead_id": lead_id, "template_key": "lead_manager", "title": "Confirm ownership", "source": "template"}
        _insert(db, "lead_checklist_items", item)
        with pytest.raises(sqlite3.IntegrityError):
            _insert(db, "lead_checklist_items", {**item, "source": "imported"})
