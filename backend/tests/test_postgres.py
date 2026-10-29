"""PostgreSQL tests. They run only when TEST_POSTGRES_URL points at a throwaway database.

The suite drops and recreates the ``public`` schema, because the point is to prove the
migrations work on an empty PostgreSQL database and the backups round-trip through real
types. Never point this at a database you care about:

    TEST_POSTGRES_URL=postgresql+psycopg://postgres@localhost:5432/acq_test pytest -k postgres
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

URL = os.environ.get("TEST_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(
    not URL, reason="Set TEST_POSTGRES_URL to a throwaway PostgreSQL database to run these"
)

ROOT = Path(__file__).resolve().parents[2]


def reset_schema():
    engine = create_engine(URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()


@pytest.fixture(scope="module")
def client(migrated):
    """The real application, wired to the PostgreSQL database under test."""
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app
    from app.seed import initialize_defaults

    with sessions()() as db:
        initialize_defaults(db)

    def override():
        with sessions()() as db:
            yield db

    app.dependency_overrides[get_db] = override
    instance = TestClient(app, base_url="http://localhost:8010", client=("127.0.0.1", 50400))
    yield instance
    instance.close()
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(scope="module")
def migrated():
    """An empty PostgreSQL database migrated to head by the application's own entry point."""
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    os.environ["DATABASE_URL"] = URL
    from app.config import get_settings

    get_settings.cache_clear()
    reset_schema()
    from app.main import migrate
    from app.seed import initialize_defaults

    migrate()
    # The default pipeline and template library, created the way a real first start does.
    with sessions()() as db:
        initialize_defaults(db)
    yield URL
    get_settings.cache_clear()


def _engine():
    from app.db import make_engine

    return make_engine(URL, pool_size=1)


def sessions():
    """A session factory for the PostgreSQL database under test.

    It deliberately does not use app.db.SessionLocal: that engine is bound when the
    module is first imported, and this suite sets DATABASE_URL later.
    """
    from app.db import make_engine

    return sessionmaker(bind=make_engine(URL, pool_size=1), expire_on_commit=False)


def _expected_head():
    """The head alembic itself points at, so a new migration cannot silently skip this check."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1, f"the migration graph has more than one head: {heads}"
    return heads[0]


def test_migrations_reach_head_on_an_empty_database(migrated):
    engine = _engine()
    try:
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            tables = {
                row[0]
                for row in connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
            }
    finally:
        engine.dispose()
    assert revision == _expected_head()
    assert {"leads", "properties", "messages", "suppression", "templates"} <= tables
    # The REsimpli and Grok tables arrive with the last migration and must exist on
    # PostgreSQL exactly as they do on SQLite: same names, same parity.
    assert {"crm_pushes", "crm_note_outbox", "grok_runs", "checklist_templates", "lead_checklist_items"} <= tables
    # The dropped column must stay dropped, and no boolean may carry an integer default.
    engine = _engine()
    try:
        with engine.connect() as connection:
            defaults = dict(
                connection.execute(
                    text(
                        "SELECT column_name, column_default FROM information_schema.columns "
                        "WHERE table_name='messages'"
                    )
                ).fetchall()
            )
            booleans = connection.execute(
                text(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_schema='public' AND data_type='boolean' AND column_default IS NOT NULL"
                )
            ).scalars().all()
    finally:
        engine.dispose()
    assert "sent_at" not in defaults
    assert booleans and set(booleans) <= {"true", "false"}


def test_a_migrated_database_accepts_the_default_pipeline(migrated):
    from app.models import PipelineStage
    from app.seed import initialize_defaults

    with sessions()() as db:
        initialize_defaults(db)
        stages = db.query(PipelineStage).count()
    assert stages > 0


def test_the_same_flag_filter_means_the_same_thing_on_postgres(migrated):
    from app.models import Lead
    from app.services.leads import lead_query

    with sessions()() as db:
        db.query(Lead).filter(Lead.external_id.like("pg-%")).delete()
        db.add(
            Lead(
                full_name="Flag Test",
                external_id="pg-flags",
                ds_flags={"high_equity": True, "senior_owner_occupied": False},
                ds_compatible_offers=["Cash", "Subject-To"],
                contact_status="unknown",
                source_kind="import",
                stage_code="new",
                outreach_mode="cold",
            )
        )
        db.commit()
        found = db.execute(lead_query({"flags": "high_equity"}, "America/New_York")).scalars().all()
        prefixed = db.execute(lead_query({"flags": "owner_occupied"}, "America/New_York")).scalars().all()
        offers = db.execute(lead_query({"offer": "cash"}, "America/New_York")).scalars().all()
        wildcard = db.execute(lead_query({"offer": "%"}, "America/New_York")).scalars().all()
        db.query(Lead).filter(Lead.external_id.like("pg-%")).delete()
        db.commit()
    assert "pg-flags" in [lead.external_id for lead in found]
    assert "pg-flags" not in [lead.external_id for lead in prefixed]
    assert "pg-flags" in [lead.external_id for lead in offers]
    assert wildcard == []


def test_logical_backup_verifies_restores_and_resets_sequences(migrated, tmp_path):
    from app.models import Lead
    from app.services import backups, logical_backup

    engine = _engine()
    try:
        with sessions()() as db:
            db.add(
                Lead(
                    full_name="Ünïcode Seller",
                    external_id="pg-backup",
                    contact_status="unknown",
                    source_kind="import",
                    stage_code="new",
                    score=4.5,
                )
            )
            db.commit()
        path = backups.create_backup(URL, reason="manual")
        assert path.name.endswith(".ndjson.gz")
        manifest = logical_backup.verify(path)
        assert manifest["database"] == "postgresql"
        assert manifest["tables"]["leads"] >= 1

        # A truncated file must be refused, not listed as a usable backup.
        broken = tmp_path / "acquisitions-20260101T000000Z-manual.ndjson.gz"
        broken.write_bytes(path.read_bytes()[:400])
        with pytest.raises(ValueError):
            backups.verify_backup(broken)

        with sessions()() as db:
            db.query(Lead).filter(Lead.external_id == "pg-backup").delete()
            db.commit()
        # Copying the backup into a second folder re-verifies it there.
        second = tmp_path / "mirror"
        second.mkdir()
        copied = backups.copy_to_second_folder(URL, path, str(second))
        assert copied["ok"] is True

        logical_backup.restore(engine, path)
        with sessions()() as db:
            restored = db.query(Lead).filter(Lead.external_id == "pg-backup").one()
            assert restored.full_name == "Ünïcode Seller"
            # The sequence must be past the restored ids, or the next insert collides.
            db.add(
                Lead(
                    full_name="After Restore",
                    external_id="pg-after",
                    contact_status="unknown",
                    source_kind="import",
                    stage_code="new",
                )
            )
            db.commit()
            assert db.query(Lead).filter(Lead.external_id == "pg-after").count() == 1
            db.query(Lead).filter(Lead.external_id.in_(["pg-backup", "pg-after"])).delete()
            db.commit()
        path.unlink()
    finally:
        engine.dispose()


def test_copying_a_sqlite_workspace_into_postgres_is_idempotent(migrated, tmp_path):
    """The migration script is re-runnable: a second run inserts nothing and changes nothing."""
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    spec = importlib.util.spec_from_file_location(
        "migrate_sqlite_to_postgres", ROOT / "scripts" / "migrate_sqlite_to_postgres.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from app.db import Base
    from app.models import Lead

    source = tmp_path / "source.db"
    sqlite_engine = create_engine(f"sqlite:///{source}")
    Base.metadata.create_all(sqlite_engine)
    with sessionmaker(bind=sqlite_engine)() as db:
        db.add(
            Lead(
                full_name="From SQLite",
                external_id="sqlite-1",
                contact_status="contacted",
                source_kind="import",
                stage_code="new",
                in_license=True,
                ds_flags={"high_equity": True},
            )
        )
        db.commit()
    sqlite_engine.dispose()

    first = module.run(source, URL, "MIGRATE TO POSTGRES", dry_run=False, limit=None)
    assert first == 0
    with sessions()() as db:
        copied = db.query(Lead).filter(Lead.external_id == "sqlite-1").one()
        assert copied.full_name == "From SQLite"
        assert copied.in_license is True
        assert copied.ds_flags == {"high_equity": True}
        assert copied.created_at.tzinfo is not None
    # Second run: nothing inserted, nothing duplicated.
    module.run(source, URL, "MIGRATE TO POSTGRES", dry_run=False, limit=None)
    with sessions()() as db:
        assert db.query(Lead).filter(Lead.external_id == "sqlite-1").count() == 1
        db.query(Lead).filter(Lead.external_id == "sqlite-1").delete()
        db.commit()


def test_the_migration_script_refuses_without_confirmation(migrated, tmp_path):
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    spec = importlib.util.spec_from_file_location(
        "migrate_sqlite_to_postgres", ROOT / "scripts" / "migrate_sqlite_to_postgres.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "empty.db"
    sqlite_engine = create_engine(f"sqlite:///{source}")
    from app.db import Base

    Base.metadata.create_all(sqlite_engine)
    sqlite_engine.dispose()
    with pytest.raises(ValueError):
        module.run(source, URL, "yes", dry_run=False, limit=None)


def test_health_refuses_traffic_when_the_database_is_unreachable(client, monkeypatch):
    """A 200 from /api/health with a dead database keeps traffic arriving that cannot be served."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import get_db
    from app.main import app

    # A real engine pointed at a closed port, so the failure happens inside the endpoint
    # (a dependency that raises would never reach the handler's own error path).
    dead = create_engine(
        "postgresql+psycopg://postgres@127.0.0.1:1/postgres", connect_args={"connect_timeout": 1}
    )
    dead_sessions = sessionmaker(bind=dead)

    def closed():
        with dead_sessions() as db:
            yield db

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = closed
    try:
        instance = TestClient(app, base_url="http://localhost:8010", client=("127.0.0.1", 50400))
        response = instance.get("/api/health")
        instance.close()
    finally:
        app.dependency_overrides[get_db] = previous
        dead.dispose()
    assert response.status_code == 503
    assert response.json()["database"] == "postgresql"
    assert "unreachable" in response.json()["detail"]
    # The URL, which can carry a password, is never echoed back.
    assert "postgres@127.0.0.1" not in response.text


def test_the_cron_endpoint_needs_its_own_secret_not_a_session(client, monkeypatch):
    import app.scheduler as scheduler_module
    from app.config import get_settings
    from app.security import new_session

    # The cron job opens its own session, exactly as it does in production.
    monkeypatch.setattr(scheduler_module, "SessionLocal", sessions())
    settings = get_settings()
    monkeypatch.setattr(settings, "app_access_password", "a-real-password-123")
    monkeypatch.setattr(settings, "cron_secret", "cron-secret-for-tests")
    assert client.post("/api/cron/run").status_code == 401
    # A browser session is not the cron secret.
    session = {"Authorization": f"Bearer {new_session()}"}
    assert client.post("/api/cron/run", headers=session).status_code == 401
    good = client.post("/api/cron/run", headers={"X-Cron-Secret": "cron-secret-for-tests"})
    assert good.status_code == 200
    assert good.json()["never_sent"] is True


def test_no_cron_secret_makes_the_route_look_absent(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "cron_secret", "")
    response = client.post("/api/cron/run", headers={"X-Cron-Secret": "anything"})
    assert response.status_code == 404


def test_only_an_allowlisted_origin_may_mutate(client, monkeypatch):
    from app.config import get_settings
    from app.security import new_session

    settings = get_settings()
    monkeypatch.setattr(settings, "app_access_password", "")
    monkeypatch.setattr(settings, "cors_origins", "https://interface.example.com")
    headers = {"Authorization": f"Bearer {new_session()}"}
    refusal = client.post(
        "/api/settings",
        headers={**headers, "Origin": "https://not-mine.example.com"},
        json={"cadence": []},
    )
    listed = client.post(
        "/api/settings",
        headers={**headers, "Origin": "https://interface.example.com"},
        json={"cadence": []},
    )
    assert refusal.status_code == 403
    assert "Cross-origin" in refusal.text
    # A listed origin is not refused for its origin; the request reaches the route.
    assert listed.status_code != 403


def test_cors_headers_come_from_the_configured_origin_only(monkeypatch):
    """The browser needs the allow header, and only for an origin we named."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import cors_options

    settings = Settings(_env_file=None, cors_origins="https://interface.example.com")
    probe = FastAPI()
    probe.add_middleware(CORSMiddleware, **cors_options(settings))

    @probe.get("/api/probe")
    def read():
        return {"ok": True}

    instance = TestClient(probe)
    allowed = instance.options(
        "/api/probe",
        headers={
            "Origin": "https://interface.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    refused = instance.options(
        "/api/probe",
        headers={"Origin": "https://not-mine.example.com", "Access-Control-Request-Method": "GET"},
    )
    instance.close()
    assert allowed.status_code in {200, 204}
    assert allowed.headers.get("access-control-allow-origin") == "https://interface.example.com"
    assert "access-control-allow-origin" not in {key.lower() for key in refused.headers}
    # No wildcard, and credentials are off: the token is a header, not a cookie.
    assert cors_options(settings)["allow_origins"] == ["https://interface.example.com"]
    assert cors_options(settings)["allow_credentials"] is False


def test_identity_pinned_by_the_environment_cannot_be_saved_from_settings(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "app_access_password", "")
    monkeypatch.setenv("SENDER_NAME", "Pinned Sender")
    view = client.get("/api/settings").json()
    refused = client.patch("/api/settings", json={"sender_name": "Anything Else"})
    assert view["sender_name_locked"] is True
    assert view["identity_source"] == "environment"
    assert refused.status_code == 400
    assert "environment" in refused.json()["detail"]


def test_a_fresh_timestamp_survives_a_round_trip_without_drifting(migrated):
    from app.models import Activity, Lead

    moment = datetime(2026, 3, 1, 12, 30, tzinfo=timezone.utc)
    with sessions()() as db:
        lead = Lead(
            full_name="Timestamp Test",
            external_id="pg-time",
            contact_status="unknown",
            source_kind="import",
            stage_code="new",
        )
        db.add(lead)
        db.commit()
        db.add(Activity(lead_id=lead.id, activity_type="note", summary="x", occurred_at=moment))
        db.commit()
        stored = db.query(Activity).filter(Activity.lead_id == lead.id).one().occurred_at
        db.query(Activity).filter(Activity.lead_id == lead.id).delete()
        db.query(Lead).filter(Lead.external_id == "pg-time").delete()
        db.commit()
    assert stored == moment
    assert stored.tzinfo is not None
