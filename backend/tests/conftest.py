"""Shared pytest fixtures.

Environment is configured *before* any application import so every test runs
against an isolated temporary database, the mock REsimpli client and a
deliberately unreachable Ollama endpoint (deterministic rule-based AI).
"""
from __future__ import annotations

import os
import pathlib
import tempfile

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="acquisitions_test_"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
        "ENVIRONMENT": "test",
        "RESIMPLI_API_KEY": "",
        "RESIMPLI_MOCK": "true",
        "AI_ENABLED": "true",
        "OLLAMA_BASE_URL": "http://127.0.0.1:9",
        "OLLAMA_TIMEOUT_SECONDS": "1",
        "GROQ_API_KEY": "",
        "SYNC_ENABLED": "false",
        "SYNC_DETAIL_BUDGET": "5",
        "UPLOAD_DIR": str(_TMP / "uploads"),
        "LOG_LEVEL": "WARNING",
    }
)

import pytest
from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, init_db
from app.main import app
from app.models import Lead, LeadProperty, Property
from app.services.normalization import normalize_email, normalize_phone, split_full_name

# The very first test file may take no fixtures at all, so the session-scoped
# client (which normally runs migrations) has not started yet. Create the temp
# schema up front — create_all is idempotent and matches current metadata.
init_db()


def _purge() -> None:
    db = SessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_db():
    _purge()
    yield
    _purge()


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def make_lead(db):
    """Create and commit a seller lead (plus optional property)."""

    def _make(
        name: str = "Dana Seller",
        phone: str | None = "6145550100",
        email: str | None = None,
        address: str | None = "412 Sycamore St",
        city: str = "Columbus",
        state: str = "OH",
        zip_code: str = "43215",
        stage: str = "new",
        contact_status: str = "never_contacted",
        source: str = "Facebook",
        do_not_contact: bool = False,
        notes: str | None = None,
        origin: str = "manual",
        external_id: str | None = None,
        **extra,
    ) -> Lead:
        first, last = split_full_name(name)
        phone_norm, _errors, _warnings = normalize_phone(phone) if phone else (None, [], [])
        lead = Lead(
            first_name=first,
            last_name=last,
            full_name=name,
            primary_phone=phone,
            phone_normalized=phone_norm,
            email=email,
            email_normalized=normalize_email(email) if email else None,
            pipeline_stage=stage,
            contact_status=contact_status,
            lead_source=source,
            do_not_contact=do_not_contact,
            notes=notes,
            origin=origin,
            external_id=external_id,
        )
        for key, value in extra.items():
            setattr(lead, key, value)
        db.add(lead)
        db.flush()
        if address:
            prop = Property(
                address_line1=address,
                city=city,
                state=state,
                zip_code=zip_code,
                address_normalized=f"{address.lower()} {city.lower()} {state.lower()} {zip_code}",
            )
            db.add(prop)
            db.flush()
            db.add(LeadProperty(lead_id=lead.id, property_id=prop.id, is_primary=True))
        db.commit()
        db.refresh(lead)
        return lead

    return _make
