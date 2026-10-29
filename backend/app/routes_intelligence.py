"""Private credentials and explicitly approved cloud processing routes."""

import hashlib
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.orm import Session
from sqlalchemy import select
from . import config
from .db import get_db, utcnow
from .models import Lead, CloudRequest, AuditLog, AppSetting
from .schemas import StrictModel
from .services.ai import context_for, context_hash
from .services import private_settings
from .services.groq_client import GroqClient, GroqError, SUPPORTED_MODELS
from .services.cloud_ai import (
    cloud_status,
    create_preview,
    request_dict,
    execute_request,
    save_organized_notes,
    ReviewError,
)
from .services.resimpli import ResimpliClient, IntegrationError, load_adapter

router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_db)]


class CredentialIn(StrictModel):
    provider: Literal["groq", "resimpli", "grok"]
    action: Literal["save", "remove"] = "save"
    api_key: str | None = Field(default=None, max_length=2000, repr=False)
    confirm_private_storage: bool = False


class GroqConfigIn(StrictModel):
    enabled: bool
    model: str = Field(default="openai/gpt-oss-20b", max_length=100)
    daily_request_limit: int = Field(default=30, ge=1, le=500)
    max_output_tokens: int = Field(default=3000, ge=512, le=4096)


class AdapterIn(StrictModel):
    adapter_json: str = Field(max_length=150000, repr=False)
    confirm_verified_against_account: bool = False


class ResimpliModeIn(StrictModel):
    enabled: bool
    confirmation: str = ""


class PreviewIn(StrictModel):
    purpose: Literal["analyze", "notes", "draft"]
    additional_redactions: list[str] = Field(default_factory=list, max_length=20)


class ExecuteIn(StrictModel):
    confirmation: str
    payload_hash: str = Field(min_length=64, max_length=64)
    selected_refs: list[str] = Field(min_length=1, max_length=100)
    force_refresh: bool = False


class ConfirmIn(StrictModel):
    confirm: bool


def _lead(db, id):
    lead = db.get(Lead, id)
    if not lead:
        raise HTTPException(404, "Seller lead not found")
    return lead


def _health(db):
    row = db.get(AppSetting, "integration_checks")
    return row.value if row else {}


def _set_health(db, provider, value):
    row = db.get(AppSetting, "integration_checks")
    stored = {**(row.value if row else {}), provider: value}
    if row:
        row.value = stored
    else:
        db.add(AppSetting(key="integration_checks", value=stored))


def _key_hash(key):
    return hashlib.sha256(key.encode()).hexdigest() if key else None


@router.get("/integrations")
def integrations(db: DB):
    settings = config.get_settings()
    checks = _health(db)

    def health(provider, key):
        value = checks.get(provider, {})
        return {
            "checked_at": value.get("checked_at"),
            "validated": bool(key and value.get("fingerprint") == _key_hash(key) and value.get("ok")),
        }

    return {
        "groq": {
            **cloud_status(db, settings),
            **health("groq", settings.groq_api_key),
            "supported_models": [{"id": id, "label": label} for id, label in SUPPORTED_MODELS.items()],
        },
        "resimpli": {
            "key_configured": bool(settings.resimpli_api_key),
            "mode": settings.resimpli_mode,
            "adapter_verified": settings.resimpli_adapter_verified,
            "adapter_configured": bool(settings.resimpli_adapter_path),
            "writes_enabled": False,
            **health("resimpli", settings.resimpli_api_key),
        },
        "environment_overrides": private_settings.environment_overrides(),
        "secret_storage": "Backend-only .env.secrets, excluded from code/ZIP/Git. Values are never returned. Restrict OS permissions and protect backups.",
        "consent_policy": "redacted_review_each_request",
        "automatic_communication": False,
    }


@router.post("/integrations/credentials")
def credentials(body: CredentialIn, db: DB):
    if not body.confirm_private_storage:
        raise ValueError("Confirm backend-only private key storage")
    name = {"groq": "GROQ_API_KEY", "resimpli": "RESIMPLI_API_KEY", "grok": "GROK_API_KEY"}[body.provider]
    if body.action == "save" and not body.api_key:
        raise ValueError("Enter a replacement key; do not reuse a key posted in chat")
    private_settings.write_private({name: body.api_key if body.action == "save" else None})
    db.add(
        AuditLog(
            action="private_credential_changed",
            details={"provider": body.provider, "action": body.action, "secret_logged": False},
        )
    )
    db.commit()
    return integrations(db)


@router.patch("/integrations/groq")
def groq_configuration(body: GroqConfigIn, db: DB):
    if body.model not in SUPPORTED_MODELS:
        raise ValueError("Select a supported structured-output model")
    if body.enabled and not config.get_settings().groq_api_key:
        raise ValueError("Save a replacement Groq key before enabling cloud processing")
    private_settings.write_private(
        {
            "GROQ_ENABLED": body.enabled,
            "GROQ_MODEL": body.model,
            "GROQ_DAILY_REQUEST_LIMIT": body.daily_request_limit,
            "GROQ_MAX_OUTPUT_TOKENS": body.max_output_tokens,
        }
    )
    db.add(
        AuditLog(
            action="groq_configuration_changed",
            details={"enabled": body.enabled, "model": body.model, "consent": "review_each_request"},
        )
    )
    db.commit()
    return integrations(db)


@router.post("/integrations/groq/test")
def groq_test(body: ConfirmIn, db: DB):
    if not body.confirm:
        raise ValueError("Confirm this key-only Groq model-list request; no seller context is sent")
    settings = config.get_settings()
    client = None
    try:
        client = GroqClient(settings)
        models = client.models()
        if not models:
            raise GroqError(
                "The key responded but no supported structured-output model was listed", "unsupported_model"
            )
        _set_health(
            db,
            "groq",
            {"ok": True, "checked_at": utcnow().isoformat(), "fingerprint": _key_hash(settings.groq_api_key)},
        )
        db.add(AuditLog(action="groq_key_checked", details={"seller_context_sent": False}))
        db.commit()
        return {
            "ok": True,
            "models": models,
            "seller_context_sent": False,
            "message": "Model-list access checked. Actual generation still requires a reviewed request.",
        }
    except GroqError as error:
        raise HTTPException(400, str(error)) from None
    finally:
        if client:
            client.close()


@router.post("/integrations/resimpli/adapter")
def adapter_save(body: AdapterIn, db: DB):
    private_settings.save_adapter(body.adapter_json, body.confirm_verified_against_account)
    db.add(
        AuditLog(
            action="private_response_adapter_saved", details={"asserted_verified_by_user": True, "crm_writes": False}
        )
    )
    db.commit()
    return integrations(db)


@router.post("/integrations/resimpli/test")
def resimpli_test(body: ConfirmIn, db: DB):
    if not body.confirm:
        raise ValueError("Confirm one documented read-only account request")
    settings = config.get_settings().model_copy(update={"resimpli_mode": "live"})
    client = None
    try:
        client = ResimpliClient(settings)
        client.request("/getUserInfo")
        _set_health(
            db,
            "resimpli",
            {"ok": True, "checked_at": utcnow().isoformat(), "fingerprint": _key_hash(settings.resimpli_api_key)},
        )
        db.add(
            AuditLog(action="resimpli_read_access_checked", details={"endpoint": "/getUserInfo", "crm_writes": False})
        )
        db.commit()
        return {
            "ok": True,
            "message": "Read response matched your configured adapter. Reconcile a manual seller sync before treating the full integration as verified.",
            "full_sync_verified": False,
            "crm_writes": False,
        }
    except IntegrationError as error:
        raise HTTPException(400, str(error)) from None
    finally:
        if client:
            client.close()


@router.patch("/integrations/resimpli")
def resimpli_mode(body: ResimpliModeIn, db: DB):
    settings = config.get_settings()
    if body.enabled:
        if body.confirmation != "ENABLE READ ONLY":
            raise ValueError("Confirm ENABLE READ ONLY")
        if not settings.resimpli_api_key:
            raise ValueError("Save an authorized replacement CRM key first")
        load_adapter(settings.model_copy(update={"resimpli_mode": "live"}))
    private_settings.write_private({"RESIMPLI_MODE": "live" if body.enabled else "disabled"})
    db.add(AuditLog(action="read_only_crm_mode_changed", details={"enabled": body.enabled, "crm_writes": False}))
    db.commit()
    return integrations(db)


@router.post("/leads/{lead_id}/cloud/preview")
def cloud_preview(lead_id: int, body: PreviewIn, db: DB):
    if any(len(term) > 200 or len(term.strip()) < 2 for term in body.additional_redactions):
        raise ValueError("Additional redactions must be 2–200 characters each")
    try:
        return request_dict(
            create_preview(db, _lead(db, lead_id), body.purpose, config.get_settings(), body.additional_redactions)
        )
    except ReviewError as error:
        raise HTTPException(error.status, str(error)) from None


@router.get("/leads/{lead_id}/cloud/requests")
def cloud_history(lead_id: int, db: DB):
    lead = _lead(db, lead_id)
    current_hash = context_hash(lead, context_for(db, lead))
    return [
        request_dict(item, lead, current_hash)
        for item in db.scalars(
            select(CloudRequest)
            .where(CloudRequest.lead_id == lead_id)
            .order_by(CloudRequest.created_at.desc())
            .limit(12)
        )
    ]


@router.post("/cloud/requests/{request_id}/execute")
def cloud_execute(request_id: str, body: ExecuteIn, db: DB):
    try:
        return request_dict(
            execute_request(
                db,
                request_id,
                config.get_settings(),
                body.confirmation,
                body.payload_hash,
                body.selected_refs,
                body.force_refresh,
            )
        )
    except ReviewError as error:
        raise HTTPException(error.status, str(error)) from None


@router.post("/cloud/requests/{request_id}/save-notes")
def organized_notes_save(request_id: str, body: ConfirmIn, db: DB):
    try:
        note = save_organized_notes(db, request_id, body.confirm)
        return {"note_id": note.id, "saved_locally": True, "crm_write": False, "contact_inferred": False}
    except ReviewError as error:
        raise HTTPException(error.status, str(error)) from None
