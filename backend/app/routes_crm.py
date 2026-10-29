"""Routes for the CRM push, the checklists, the AI jobs and the lead-profile cards.

Every route here is reached only through the same access middleware as the rest of the
application. The paths deliberately avoid any send-shaped segment, and the write-shaped
ones are listed on purpose in ``route_allowlist.py`` so a new one cannot appear without
being declared.

Nothing in this module sends anything to a seller. A push creates a *record* in the CRM,
which the CRM's own automations may then act on -- that is why review mode is the
default and the confirmation is typed rather than assumed.
"""

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .models import Activity, AuditLog, CrmNoteOutbox, Followup, GrokRun, Lead, Task
from .schemas import StrictModel
from .services import checklists, crm_notes, crm_push, private_settings
from .services.ai_features import (
    ADVISOR_DISCLAIMER,
    COMPLIANCE_REMINDER,
    advise,
    decide_suggestion,
    draft_followup,
    latest_advice,
    preview_for,
    suggest_checklist,
    suggestions_for,
)
from .services.ai_grok import AI_FIELDS, GrokError, cap_status, monthly_estimate
from .services.resimpli import IntegrationError, ResimpliClient
from .services.resimpli_write import CrmWriteError, ResimpliWriter

router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_db)]


class PushSettingsIn(StrictModel):
    mode: Optional[Literal["review", "auto"]] = None
    marketing_campign_id: Optional[str] = Field(default=None, max_length=64)
    market_id: Optional[str] = Field(default=None, max_length=64)
    pipeline_id: Optional[str] = Field(default=None, max_length=64)
    main_status_id: Optional[str] = Field(default=None, max_length=64)
    note_fields: Optional[dict[str, bool]] = None


class PreviewIn(StrictModel):
    include_note: bool = True


class PushIn(StrictModel):
    confirmation: str = ""
    include_note: bool = True


class BatchIn(StrictModel):
    lead_ids: list[int] = Field(min_length=1, max_length=200)
    confirmation: str = ""
    include_note: bool = True


class LinkIn(StrictModel):
    resimpli_lead_id: str = Field(min_length=1, max_length=100)


class ChecklistItemIn(StrictModel):
    done: bool


class ChecklistAddIn(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    detail: Optional[str] = Field(default=None, max_length=2000)
    template_key: str = Field(default="lead_manager", max_length=40)


class TemplateIn(StrictModel):
    name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    active: Optional[bool] = None
    items: Optional[list[dict]] = Field(default=None, max_length=100)


class SuggestionIn(StrictModel):
    accept: bool


class GrokPromptIn(StrictModel):
    purpose: Literal["followup_draft", "checklist_suggest", "advisor"]


class GrokSettingsIn(StrictModel):
    """What may be sent to the AI, and how much of it -- changed from the CRM & AI page.

    Every key is optional so a screen can change one thing without restating the rest.
    The key itself is never part of this: it is written once, through the credential
    route, and never read back.
    """

    fields: Optional[list[str]] = Field(default=None, max_length=len(AI_FIELDS))
    daily_limit: Optional[int] = Field(default=None, ge=1, le=500)
    api: Optional[Literal["responses", "chat_completions"]] = None


def _lead(db: Session, lead_id):
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "Seller lead not found")
    return lead


def _settings():
    return config.get_settings()


def _reader(settings):
    """A read-only client. Fixture mode is allowed; disabled mode is not."""
    try:
        return ResimpliClient(settings)
    except IntegrationError as error:
        raise HTTPException(400, str(error)) from None


def _writer(settings):
    if not settings.crm_writes_enabled:
        raise ValueError("CRM writes are switched off in the environment (CRM_WRITES_ENABLED)")
    try:
        return ResimpliWriter(settings)
    except CrmWriteError as error:
        raise HTTPException(400, str(error)) from None


def _note_text(db, lead, include_note):
    if not include_note:
        return None
    return crm_notes.note_for_new_lead(db, lead, crm_push.load_push_settings(db))


# --- settings ----------------------------------------------------------------------


@router.get("/integrations/resimpli/push/settings")
def push_settings(db: DB):
    settings = _settings()
    stored = crm_push.load_push_settings(db)
    return {
        "settings": stored.model_dump(),
        "crm_writes_enabled": settings.crm_writes_enabled,
        "mode": settings.resimpli_mode,
        "api_modes": list(crm_push.MODES),
        "confirmation_phrase": crm_push.CONFIRMATION,
        "note_fields": crm_push.NOTE_FIELDS,
        "write_scope": "Create a lead only. No updates, no stage changes, no deletes.",
    }


@router.patch("/integrations/resimpli/push/settings")
def push_settings_save(body: PushSettingsIn, db: DB):
    updates = {key: value for key, value in body.model_dump().items() if value is not None}
    try:
        stored = crm_push.save_push_settings(db, updates)
    except ValueError as error:
        raise HTTPException(400, f"Invalid push setting: {error}") from None
    return {"settings": stored.model_dump(), "confirmation_phrase": crm_push.CONFIRMATION}


@router.get("/integrations/resimpli/push/accounts")
def push_accounts(db: DB):
    """Read the account's campaign, market and pipeline lists so the IDs can be loaded.

    Read-only: marketingCampaignList, marketList and getPipelineList are documented reads.
    """
    settings = _settings()
    client = _reader(settings)
    try:
        result = {}
        for name, path in (
            ("marketing_campaigns", "/marketingCampaignList"),
            ("markets", "/marketList"),
            ("pipelines", "/getPipelineList"),
        ):
            try:
                data = client.request(path, {})
            except IntegrationError as error:
                result[name] = {"error": str(error), "options": []}
                continue
            result[name] = {"error": None, "options": _records(data)[:200]}
    finally:
        client.close()
    return {
        "account_options": result,
        "read_only": True,
        "field_names": {
            "marketing_campign_id": "marketingCampignId (the API spells it this way)",
            "market_id": "marketId",
            "pipeline_id": "pipelineId",
            "main_status_id": "mainStatusId",
        },
        "note": "Pick one value for each field in Settings. Nothing is written by this request.",
    }


def _records(data):
    for key in ("data", "result"):
        value = data.get(key) if isinstance(data, dict) else None
        if isinstance(value, list):
            return [item for item in value if isinstance(item, (dict, str))]
        if isinstance(value, dict):
            for inner in ("records", "items", "list"):
                if isinstance(value.get(inner), list):
                    return [item for item in value[inner] if isinstance(item, (dict, str))]
    return []


# --- queue and push ----------------------------------------------------------------


@router.get("/integrations/resimpli/push/queue")
def push_queue(db: DB):
    rows = crm_push.queue(db)
    ready = [row for row in rows if row.reason is None]
    return {
        "rows": [row.model_dump() for row in rows],
        "counts": {"total": len(rows), "ready": len(ready), "blocked": len(rows) - len(ready)},
        "failed": crm_push.failed_count(db),
        "mode": crm_push.load_push_settings(db).mode,
        "writes_enabled": _settings().crm_writes_enabled,
    }


def _plan_payload(plan):
    return {
        "lead_id": plan.lead_id,
        "eligible": plan.eligible,
        "reason": plan.reason,
        "message": plan.message,
        "body": plan.body,
        "payload_hash": plan.payload_hash,
        "warnings": plan.warnings,
        "matches": plan.matches,
        "searches": plan.searches,
        "note": plan.note,
        "mode": plan.mode,
        "dry_run": plan.dry_run,
    }


@router.post("/leads/{lead_id}/crm/preview")
def crm_preview(lead_id: int, body: PreviewIn, db: DB):
    """Dry run: the exact request body and every reason it would not be sent."""
    lead = _lead(db, lead_id)
    settings = _settings()
    reader = _reader(settings)
    try:
        note = _note_text(db, lead, body.include_note)
        plan = crm_push.plan_push(db, lead, reader, note=note, dry_run=True)
    finally:
        reader.close()
    db.rollback()  # a preview never leaves a row behind
    return {**_plan_payload(plan), "writes_nothing": True}


@router.post("/leads/{lead_id}/crm/push")
def crm_push_one(lead_id: int, body: PushIn, db: DB):
    """Create exactly one lead. The confirmation is typed; the plan is shown first."""
    lead = _lead(db, lead_id)
    settings = _settings()
    writer = _writer(settings)
    reader = _reader(settings)
    try:
        note = _note_text(db, lead, body.include_note)
        outcome = crm_push.execute_push(
            db,
            lead,
            reader=reader,
            writer=writer,
            confirmation=body.confirmation,
            note=note,
            settings=settings,
        )
    finally:
        writer.close()
        reader.close()
    return {
        "state": outcome.state,
        "reason": outcome.reason,
        "message": outcome.message,
        "resimpli_lead_id": outcome.resimpli_lead_id,
        "payload_hash": outcome.payload_hash,
        "attempts": outcome.attempts,
        "plan": _plan_payload(outcome.plan),
        "never_sent_to_seller": True,
    }


@router.post("/integrations/resimpli/push/batch")
def crm_push_batch(body: BatchIn, db: DB):
    """Push a reviewed selection. One failure is recorded; the rest continue."""
    settings = _settings()
    writer = _writer(settings)
    reader = _reader(settings)
    leads = [_lead(db, lead_id) for lead_id in body.lead_ids]
    try:
        results = crm_push.push_batch(
            db,
            leads,
            reader=reader,
            writer=writer,
            settings=settings,
            note_for=lambda lead: _note_text(db, lead, body.include_note),
            confirmation=body.confirmation,
        )
    finally:
        writer.close()
        reader.close()
    return {
        "results": [
            {
                "lead_id": result.lead_id,
                "state": result.state,
                "reason": result.reason,
                "message": result.message,
                "resimpli_lead_id": result.resimpli_lead_id,
            }
            for result in results
        ],
        "pushed": sum(1 for result in results if result.state == "pushed"),
        "failed": sum(1 for result in results if result.state in {"failed", "outcome_unknown"}),
        "blocked": sum(1 for result in results if result.state == "blocked"),
    }


@router.post("/leads/{lead_id}/crm/link")
def crm_link(lead_id: int, body: LinkIn, db: DB):
    """Say that a lead already in the CRM *is* this lead, resolving the conflict."""
    lead = _lead(db, lead_id)
    mapping = crm_push.link_existing(db, lead, body.resimpli_lead_id)
    return {"state": mapping.state, "resimpli_lead_id": mapping.resimpli_lead_id, "linked": True}


# --- notes -------------------------------------------------------------------------


@router.get("/leads/{lead_id}/notes")
def lead_notes(lead_id: int, db: DB):
    _lead(db, lead_id)
    return {
        "notes": crm_notes.notes_for_lead(db, lead_id),
        "prefix": crm_push.NOTE_PREFIX,
        "copy_only": True,
        "note_endpoint_exists": False,
    }


@router.post("/leads/{lead_id}/notes")
def lead_note_build(lead_id: int, db: DB):
    """Build (or re-use) the structured note for a lead and show it for copying."""
    lead = _lead(db, lead_id)
    result = crm_notes.note_for_existing_lead(db, lead, crm_push.load_push_settings(db))
    return {**result, "copy_only": True}


# --- checklists --------------------------------------------------------------------


@router.get("/checklists/templates")
def checklist_templates(db: DB):
    return {"templates": checklists.template_view(db)}


@router.patch("/checklists/templates/{key}")
def checklist_template_save(key: str, body: TemplateIn, db: DB):
    updated = checklists.update_template(
        db,
        key,
        name=body.name,
        description=body.description,
        active=body.active,
        items=body.items,
    )
    return {"templates": updated, "note": "Leads that already have their copy are untouched"}


@router.get("/leads/{lead_id}/checklists")
def lead_checklists(lead_id: int, db: DB):
    _lead(db, lead_id)
    return checklists.progress(db, lead_id)


@router.patch("/checklists/items/{item_id}")
def checklist_item_set(item_id: int, body: ChecklistItemIn, db: DB):
    return checklists.set_item(db, item_id, body.done)


@router.post("/leads/{lead_id}/checklists/items")
def checklist_item_add(lead_id: int, body: ChecklistAddIn, db: DB):
    _lead(db, lead_id)
    return checklists.add_item(db, lead_id, body.title, body.detail, body.template_key)


# --- AI ----------------------------------------------------------------------------


@router.get("/integrations/grok/status")
def grok_status(db: DB):
    settings = _settings()
    return {
        **cap_status(db, settings),
        "api": settings.grok_api,
        "monthly_estimate": monthly_estimate(settings, db),
        "fields": [{"key": key, "label": label} for key, label in AI_FIELDS.items()],
        "enabled_fields": [item.strip() for item in (settings.grok_ai_fields or "").split(",") if item.strip()],
        "disclaimer": ADVISOR_DISCLAIMER,
        "compliance": COMPLIANCE_REMINDER,
        "drafts_are_copy_only": True,
    }


@router.patch("/integrations/grok/settings")
def grok_settings_save(body: GrokSettingsIn, db: DB):
    """Change the per-field sharing list, the daily cap and the API surface.

    Local only: the values land in the private settings file the app already reads at
    startup, and the settings cache is cleared so the next call uses them.
    """
    updates = {}
    fields = None
    if body.fields is not None:
        chosen = [name.strip() for name in body.fields if name and name.strip()]
        unknown = sorted(set(chosen) - set(AI_FIELDS))
        if unknown:
            raise HTTPException(400, "Unknown AI field: " + ", ".join(unknown))
        if not chosen:
            raise HTTPException(400, "Keep at least one field, or the AI cannot answer anything useful")
        fields = list(dict.fromkeys(chosen))
        updates["GROK_AI_FIELDS"] = ",".join(fields)
    if body.daily_limit is not None:
        updates["GROK_DAILY_REQUEST_LIMIT"] = body.daily_limit
    if body.api is not None:
        updates["GROK_API"] = body.api
    if not updates:
        raise HTTPException(400, "Nothing to change")
    private_settings.write_private(updates)
    db.add(
        AuditLog(
            action="grok_settings_changed",
            details={"keys": sorted(updates), "values_logged": False},
        )
    )
    db.commit()
    # Echo what was just saved, not what the previous settings object happened to hold.
    settings = _settings()
    return {
        "saved": sorted(updates),
        "enabled_fields": (
            fields
            if fields is not None
            else [item.strip() for item in (settings.grok_ai_fields or "").split(",") if item.strip()]
        ),
        "daily_limit": body.daily_limit if body.daily_limit is not None else settings.grok_daily_request_limit,
        "api": body.api or settings.grok_api,
        "key_logged": False,
        "key_returned": False,
    }


@router.post("/leads/{lead_id}/grok/preview")
def grok_preview(lead_id: int, body: GrokPromptIn, db: DB):
    """Exactly which fields would be sent for this lead and purpose, PII stripped."""
    return preview_for(db, _settings(), _lead(db, lead_id), body.purpose)


@router.post("/leads/{lead_id}/grok/followup")
def grok_followup(lead_id: int, db: DB):
    lead = _lead(db, lead_id)
    try:
        return draft_followup(db, _settings(), lead)
    except GrokError as error:
        raise HTTPException(400, str(error)) from None


@router.post("/leads/{lead_id}/grok/checklist")
def grok_checklist(lead_id: int, db: DB):
    lead = _lead(db, lead_id)
    try:
        return suggest_checklist(db, _settings(), lead)
    except GrokError as error:
        raise HTTPException(400, str(error)) from None


@router.get("/leads/{lead_id}/grok/checklist")
def grok_checklist_list(lead_id: int, db: DB):
    _lead(db, lead_id)
    return {"suggestions": suggestions_for(db, lead_id), "accept_each": True}


@router.post("/grok/suggestions/{suggestion_id}")
def grok_suggestion_decide(suggestion_id: int, body: SuggestionIn, db: DB):
    return decide_suggestion(db, suggestion_id, body.accept)


@router.post("/leads/{lead_id}/grok/advice")
def grok_advice(lead_id: int, db: DB):
    lead = _lead(db, lead_id)
    try:
        return advise(db, _settings(), lead)
    except GrokError as error:
        raise HTTPException(400, str(error)) from None


@router.get("/leads/{lead_id}/grok/advice")
def grok_advice_latest(lead_id: int, db: DB):
    _lead(db, lead_id)
    return {
        "advice": latest_advice(db, lead_id),
        "disclaimer": ADVISOR_DISCLAIMER,
        "compliance": COMPLIANCE_REMINDER,
        "decision_support_only": True,
    }


# --- lead profile and dashboard ----------------------------------------------------


def _next_action(db: Session, lead_id):
    task = db.scalar(
        select(Task).where(Task.lead_id == lead_id, Task.status == "open").order_by(Task.priority, Task.id)
    )
    if task:
        return {"kind": "task", "title": task.title, "due_at": task.due_at, "detail": task.description}
    followup = db.scalar(
        select(Followup).where(Followup.lead_id == lead_id, Followup.status == "pending").order_by(Followup.due_at)
    )
    if followup:
        return {
            "kind": "followup",
            "title": followup.suggested_action or followup.reason,
            "due_at": followup.due_at,
            "detail": followup.reason,
        }
    return {"kind": None, "title": "No next action set", "due_at": None, "detail": None}


def _last_conversation(db: Session, lead_id):
    row = db.scalar(
        select(Activity).where(Activity.lead_id == lead_id).order_by(Activity.occurred_at.desc()).limit(1)
    )
    if row is None:
        return None
    return {
        "occurred_at": row.occurred_at,
        "direction": row.direction,
        "summary": row.summary,
        "outcome": row.outcome,
    }


@router.get("/leads/{lead_id}/cards")
def lead_cards(lead_id: int, db: DB):
    """The six lead-profile cards, each with its status and what can be done next."""
    lead = _lead(db, lead_id)
    settings = _settings()
    return {
        "lead_id": lead.id,
        "full_name": lead.full_name,
        "next_action": _next_action(db, lead.id),
        "checklist": checklists.progress(db, lead.id),
        "exit_strategy": latest_advice(db, lead.id),
        "last_conversation": _last_conversation(db, lead.id),
        "crm_sync": crm_push.sync_status(db, lead.id),
        "notes": crm_notes.notes_for_lead(db, lead.id),
        "ai": {"enabled": bool(settings.grok_enabled), "remaining_today": cap_status(db, settings)["remaining"]},
    }


@router.get("/dashboard/integrations")
def dashboard_integrations(db: DB):
    rows = crm_push.queue(db)
    ready = sum(1 for row in rows if row.reason is None)
    advisor_ready = len(
        {
            row.lead_id
            for row in db.scalars(
                select(GrokRun).where(GrokRun.purpose == "advisor", GrokRun.state == "succeeded")
            ).all()
            if row.lead_id
        }
    )
    return {
        "push_queue": {"ready": ready, "blocked": len(rows) - ready, "total": len(rows)},
        "failed_syncs": crm_push.failed_count(db),
        "checklists_due": checklists.open_items(db),
        "advisor_ready": advisor_ready,
        "notes_blocked": len(db.scalars(select(CrmNoteOutbox).where(CrmNoteOutbox.state == "blocked")).all()),
    }
