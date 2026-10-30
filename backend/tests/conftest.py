import os

# Must run before any app import: get_settings() is lru_cached, and app.main
# constructs it at import time. Setting these here makes pydantic-settings read
# our values (environment beats the env file) before anything caches.
# The person running the suite on their own machine has a real .env with a workspace
# password and API keys, so route tests would hit 401s and enabled-AI paths instead
# of the responses they assert on (the CI box has no .env, which is why it is green).
# This forces the same passwordless, cloud-off loopback mode CI runs in -- unless
# the caller set these variables deliberately.
os.environ.setdefault("APP_ACCESS_PASSWORD", "")
os.environ.setdefault("GROQ_API_KEY", "")
os.environ.setdefault("GROK_API_KEY", "")
# Same reasoning as above: a local .env enables the live/verified sync mode, which
# changes code paths the suite asserts against in the CI default ("disabled").
os.environ.setdefault("RESIMPLI_MODE", "disabled")

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.config import Settings
from app.db import Base, get_db
from app.main import app
from app.seed import initialize_defaults
from app.services.imports import create_local_lead


@pytest.fixture
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as db:
        initialize_defaults(db)
    yield maker
    engine.dispose()


@pytest.fixture
def db(factory):
    with factory() as session:
        yield session


@pytest.fixture
def settings():
    return Settings(_env_file=None, resimpli_mode="fixture")


@pytest.fixture
def client(db):
    def override():
        try:
            yield db
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def make_lead(db):
    def make(name="Test Seller", phone="+12025550199", address="12 Example St", state="TX", **extra):
        data = {
            "full_name": name,
            "primary_phone": phone,
            "street_address": address,
            "city": "Austin",
            "state": state,
            "zip_code": "78701",
            "normalized_address": (address + "austintx78701").lower() if address else None,
            **extra,
        }
        lead = create_local_lead(db, data, data, source_kind="local")
        db.commit()
        return lead

    return make


@pytest.fixture(autouse=True)
def reset_session_state():
    """Signed sessions live in module globals; tests must not leak them to each other."""
    from app import security

    before_cutoff = security.REVOKED_BEFORE
    security.REVOKED_TOKENS.clear()
    yield
    security.REVOKED_BEFORE = before_cutoff
    security.REVOKED_TOKENS.clear()
