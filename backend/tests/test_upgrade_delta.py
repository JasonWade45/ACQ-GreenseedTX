"""Upgrade safety: a database from the previous release keeps every record."""

import os
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import ROOT, get_settings
from app.version import APP_VERSION


def _alembic(url: str, revision: str) -> None:
    """Migrate a throwaway database. migrations/env.py reads the app settings, so the
    URL has to be set there too (never migrate the developer's real data folder)."""
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "backend/migrations"))
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        command.upgrade(config, revision)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def test_upgrade_from_previous_database_preserves_every_record(tmp_path):
    database = tmp_path / "previous.db"
    url = "sqlite:///" + str(database)
    _alembic(url, "g7h8i9j0k1l2")  # the release before this delta

    with sqlite3.connect(database) as db:
        db.execute("PRAGMA foreign_keys=OFF")

        def insert(table, values):
            """Insert one row, filling any other NOT NULL column with a benign default.

            The previous schema has many NOT NULL columns; the point of this test is that
            existing data survives an upgrade, not that the fixture matches every column.
            """
            columns = {row[1]: row for row in db.execute(f"PRAGMA table_info({table})")}
            row = dict(values)
            for name, info in columns.items():
                if name in row:
                    continue
                if info[3] and info[4] is None:  # notnull, no default
                    row[name] = 0 if any(k in info[2].upper() for k in ("INT", "BOOL", "FLOAT")) else ""
            keys = ",".join(row)
            placeholders = ",".join("?" for _ in row)
            db.execute(f"INSERT INTO {table} ({keys}) VALUES ({placeholders})", tuple(row.values()))

        insert("pipeline_stages", {"code": "new", "label": "New", "position": 0, "active": 1})
        insert(
            "leads",
            {
                "id": 1,
                "full_name": "Existing Seller",
                "stage_code": "new",
                "contact_status": "contacted",
                "local_do_not_contact": 0,
                "in_license": 1,
                "source_kind": "resimpli",
                "source_data": "{}",
                "user_edited_fields": "[]",
                "created_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-01 00:00:00",
            },
        )
        insert(
            "activities",
            {
                "id": 1,
                "lead_id": 1,
                "activity_type": "call",
                "source": "resimpli",
                "summary": "Existing activity",
                "source_metadata": "{}",
                "recorded_at": "2026-01-01 00:00:00",
            },
        )
        insert(
            "drafts",
            {
                "id": 1,
                "lead_id": 1,
                "body": "Existing draft body",
                "context": "ctx",
                "model_id": "model",
                "created_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-01 00:00:00",
            },
        )
        insert(
            "app_settings",
            {
                "key": "priority_rules",
                "value": '{"callback_bonus": 30, "negotiation_bonus": 20, "appointment_bonus": 25, '
                '"overdue_per_day": 2, "new_lead_priority": 40, "stale_after_days": 30}',
            },
        )
        db.commit()

    _alembic(url, "head")

    with sqlite3.connect(database) as db:
        assert db.execute("SELECT full_name FROM leads WHERE id=1").fetchone()[0] == "Existing Seller"
        assert db.execute("SELECT summary FROM activities WHERE id=1").fetchone()[0] == "Existing activity"
        assert db.execute("SELECT body FROM drafts WHERE id=1").fetchone()[0] == "Existing draft body"
        columns = {row[1] for row in db.execute("PRAGMA table_info(leads)")}
        assert {"ds_flags", "ds_flags_raw", "ds_extra_flags", "ds_compatible_offers", "outreach_mode"} <= columns
        assert db.execute("SELECT outreach_mode FROM leads WHERE id=1").fetchone()[0] == "relationship"
        assert "reason_tags" in {row[1] for row in db.execute("PRAGMA table_info(messages)")}
        assert {"id", "lead_id", "kind", "status"} <= {
            row[1] for row in db.execute("PRAGMA table_info(suggested_actions)")
        }
        assert db.execute("SELECT value FROM app_settings WHERE key='priority_rules'").fetchone()[0]


def test_startup_backfills_new_priority_rules_without_losing_values():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db import Base
    from app.models import AppSetting
    from app.seed import initialize_defaults

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as db:
        db.add(
            AppSetting(
                key="priority_rules",
                value={
                    "callback_bonus": 44,
                    "negotiation_bonus": 20,
                    "appointment_bonus": 25,
                    "overdue_per_day": 2,
                    "new_lead_priority": 40,
                    "stale_after_days": 30,
                },
            )
        )
        db.commit()
        initialize_defaults(db)
        rules = db.get(AppSetting, "priority_rules").value
        assert rules["callback_bonus"] == 44  # an explicit choice is kept
        assert rules["heat_very_hot_bonus"] == 30  # the new default is added
        assert rules["negative_equity_penalty"] == -15


def test_version_matches_the_frontend_package():
    import json

    package = json.loads((Path(ROOT) / "frontend" / "package.json").read_text())
    assert package["version"] == APP_VERSION
