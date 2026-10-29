"""Grok's three jobs, all internal and all reviewable.

1. A follow-up draft built from what actually happened on the lead (the read-only activity
   sync and, only when it is switched on, the conversation text). The result goes through
   the same hard content validator as every other draft and lands in the same copy-only
   queue: a person reads it, edits it and copies it. Nothing is sent.
2. Checklist suggestions for the lead in front of you. Each one is accepted or rejected
   individually; a rejected suggestion leaves no trace on the lead.
3. An advisor note returning strict JSON: situation, next steps, what not to do, risks,
   the best exit strategy with its reasoning and what information is missing, and a
   confidence. It is labelled decision support, carries a compliance reminder written
   here rather than by the model, and is stored with its model and input hash.

Every call is counted against the daily cap, stored in ``grok_runs`` and audited without
prompt text, seller contact details or the key.
"""

import hashlib
import json
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Activity, AiChecklistSuggestion, AuditLog, GrokRun, LeadChecklistItem, Message
from .ai_grok import (
    AI_FIELDS,
    DEFAULT_AI_FIELDS,
    GrokClient,
    GrokError,
    cap_status,
    model_for,
    record_run,
    strip_pii,
)
from .templates import OPT_OUT_LINE, draft_gates, sender_identity, validate_message

ADVISOR_DISCLAIMER = (
    "Decision support only. This is not legal, financial, tax or investment advice, and it is not a "
    "valuation. Verify anything that matters with the appropriate Texas-licensed professional."
)
COMPLIANCE_REMINDER = (
    "Compliance reminder: marketing or selling another person's property for a fee generally requires a "
    "Texas real estate licence unless a specific exemption applies; disclose in writing that you are an "
    "investor buying for your own account and not the seller's agent; and honour the National and Texas "
    "Do-Not-Call lists plus TCPA restrictions on calls and texts. This is a reminder, not legal advice."
)
MAX_SUGGESTIONS = 8


class FollowupOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str
    reasoning: str
    used: list[str] = []


class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    detail: str

    @field_validator("title")
    @classmethod
    def short(cls, value):
        text = (value or "").strip()
        if not text or len(text) > 200:
            raise ValueError("A checklist item needs a title of at most 200 characters")
        return text


class ChecklistOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ChecklistItemOut]


class ExitStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    reasoning: str
    missing_information: list[str] = []


class AdvisorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    situation_summary: str
    next_steps: list[str]
    do_not: list[str]
    risks: list[str]
    exit_strategy: ExitStrategy
    confidence: Literal["low", "medium", "high"]


FOLLOWUP_SCHEMA = FollowupOutput.model_json_schema()
CHECKLIST_SCHEMA = ChecklistOutput.model_json_schema()
ADVISOR_SCHEMA = AdvisorOutput.model_json_schema()


def enabled_fields(settings) -> list[str]:
    """The fields a person allowed in Settings, kept in the documented order."""
    chosen = [item.strip() for item in (settings.grok_ai_fields or "").split(",") if item.strip()]
    ordered = [name for name in AI_FIELDS if name in chosen]
    return ordered or list(DEFAULT_AI_FIELDS)


def lead_facts(db: Session, lead, settings) -> dict:
    """Only the allowed fields, read from the lead. PII is stripped later, on the way out."""
    allowed = enabled_fields(settings)
    facts = {}
    if "property_address" in allowed:
        for prop in lead.properties or []:
            if prop.street_address:
                facts["property_address"] = ", ".join(
                    str(part) for part in (prop.street_address, prop.city, prop.state, prop.zip_code) if part
                )
                break
    if "property_facts" in allowed:
        facts["property_facts"] = {
            key: getattr(lead.properties[0], key, None)
            for key in ("bedrooms", "bathrooms", "square_feet", "year_built", "property_type")
            if lead.properties
        } if lead.properties else {}
    if "lead_type" in allowed and lead.lead_type:
        facts["lead_type"] = lead.lead_type
    if "priority" in allowed:
        facts["priority"] = {
            "tier": lead.priority_tier,
            "score": lead.score,
            "heat": lead.heat,
        }
    if "equity" in allowed and lead.equity_pct is not None:
        facts["equity"] = lead.equity_pct
    if "flags" in allowed and lead.ds_flags:
        facts["flags"] = [name for name, value in lead.ds_flags.items() if value]
    if "contact_history" in allowed:
        activities = db.scalars(
            select(Activity).where(Activity.lead_id == lead.id).order_by(Activity.occurred_at.desc()).limit(10)
        ).all()
        facts["contact_history"] = {
            "contact_status": lead.contact_status,
            "last_outcome": lead.contact_outcome,
            "attempts": [
                {
                    "at": activity.occurred_at.date().isoformat() if activity.occurred_at else None,
                    "summary": (activity.summary or "")[:300],
                    "outcome": activity.outcome,
                    "direction": activity.direction,
                }
                for activity in activities
            ],
        }
    if "conversation" in allowed:
        messages = db.scalars(
            select(Message).where(Message.lead_id == lead.id).order_by(Message.id.desc()).limit(6)
        ).all()
        facts["conversation"] = [
            {"direction": message.direction, "text": (message.body or "")[:600]} for message in messages
        ]
    return facts


def _facts_prompt(facts: dict) -> str:
    return "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False, default=str)}" for key, value in facts.items())


def input_hash(*, purpose, model, prompt):
    payload = json.dumps({"purpose": purpose, "model": model, "prompt": strip_pii(prompt)}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _cap(db: Session, settings, purpose):
    status = cap_status(db, settings)
    if not status["enabled"]:
        raise GrokError("The Grok integration is switched off in Settings", code="not_configured")
    if status["exhausted"]:
        raise GrokError(
            f"The daily AI limit of {status['limit']} calls is reached; it resets at midnight UTC",
            code="daily_cap_reached",
        )
    return purpose


def _call(db: Session, settings, lead, *, purpose, prompt, schema, name, model_cls, client=None):
    """One counted, recorded, schema-checked call. Retries once on a schema failure only."""
    _cap(db, settings, purpose)
    owned = client is None
    client = client or GrokClient(settings)
    digest = input_hash(purpose=purpose, model=model_for(purpose, settings), prompt=prompt)
    try:
        for attempt in range(2):
            result = client.complete(purpose=purpose, prompt=prompt, schema=schema, name=name)
            try:
                parsed = model_cls.model_validate(result.data or {})
            except ValidationError as exc:
                if attempt == 0:
                    continue
                record_run(
                    db,
                    run_id=str(uuid.uuid4()),
                    lead_id=lead.id if lead else None,
                    purpose=purpose,
                    input_hash=digest,
                    result=result,
                    state="invalid",
                    error=f"schema mismatch: {exc.error_count()} problem(s)",
                )
                db.commit()
                raise GrokError(
                    "The AI answer did not match the required shape twice; nothing was saved to the lead",
                    code="schema_invalid",
                ) from exc
            run_id = str(uuid.uuid4())
            record_run(
                db,
                run_id=run_id,
                lead_id=lead.id if lead else None,
                purpose=purpose,
                input_hash=digest,
                result=result,
            )
            db.add(
                AuditLog(
                    lead_id=lead.id if lead else None,
                    action="grok_call_completed",
                    details={
                        "purpose": purpose,
                        "model": result.model,
                        "api": result.api,
                        "input_hash": digest,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "run_id": run_id,
                        "never_sent": True,
                    },
                )
            )
            db.commit()
            return run_id, digest, parsed, result
    finally:
        if owned:
            client.close()
    raise GrokError("The AI call failed", code="grok_failed")


def draft_followup(db: Session, settings, lead, *, client=None):
    """A follow-up draft from the last conversation, validated and queued for copy."""
    if lead.do_not_contact:
        raise ValueError("This lead is marked do-not-contact; no draft is prepared")
    if lead.outreach_mode == "cold":
        blocking, _warnings = draft_gates(db, lead)
        if blocking:
            raise ValueError("; ".join(blocking))
    sender_name, company = sender_identity(settings)
    if not sender_name or not company:
        raise ValueError("Sender identity is missing. Set the sender name and company in Settings first")

    facts = lead_facts(db, lead, settings)
    if not facts:
        raise ValueError("No reviewed facts are available for this lead; nothing was sent to the AI")
    prompt = (
        "Write one short follow-up message for a property seller you have already spoken with.\n"
        "Rules: plain text only; no links; no emoji; no dollar amounts; no invented facts; do not promise a "
        "price; one clear question; at most 700 characters. End with the opt-out sentence below and sign "
        f"as '{sender_name} with {company}'.\n"
        f"Opt-out sentence to include verbatim: {OPT_OUT_LINE}\n"
        "Return JSON with keys body, reasoning, used. 'used' lists which facts you relied on.\n"
        f"Facts:\n{_facts_prompt(facts)}"
    )
    run_id, digest, parsed, result = _call(
        db,
        settings,
        lead,
        purpose="followup_draft",
        prompt=prompt,
        schema=FOLLOWUP_SCHEMA,
        name="followup_draft",
        model_cls=FollowupOutput,
        client=client,
    )
    body = parsed.body.strip()
    ok, reasons = validate_message(
        body,
        bool(lead.first_name or lead.full_name),
        sender_name=sender_name,
        company=company,
        first_message=lead.outreach_mode == "cold",
    )
    record = Message(
        lead_id=lead.id,
        direction="outbound",
        body=body,
        status="DRAFT",
        validator_result={"ok": ok, "reasons": reasons},
        reason_tags=["ai:followup_draft"],
    )
    db.add(record)
    db.add(
        AuditLog(
            lead_id=lead.id,
            action="draft_prepared",
            details={
                "mode": "ai_followup",
                "run_id": run_id,
                "model": result.model,
                "validator_ok": ok,
                "reasons": reasons,
                "never_sent": True,
            },
        )
    )
    db.commit()
    db.refresh(record)
    return {
        "id": record.id,
        "lead_id": lead.id,
        "body": body,
        "status": record.status,
        "validator_result": record.validator_result,
        "reasoning": parsed.reasoning,
        "used": parsed.used,
        "model": result.model,
        "run_id": run_id,
        "input_hash": digest,
        "copy_only": True,
    }


def suggest_checklist(db: Session, settings, lead, *, client=None):
    """Propose up to eight checklist lines; none of them touches the lead until accepted."""
    facts = lead_facts(db, lead, settings)
    prompt = (
        "Propose between 3 and 8 concrete, short checklist items for an acquisitions team working this lead.\n"
        "Rules: each item is an action a person can do this week; no legal, tax or investment advice; no prices; "
        "no invented facts. Return JSON with key items, each having title (max 120 characters) and detail.\n"
        f"Facts:\n{_facts_prompt(facts)}"
    )
    run_id, digest, parsed, result = _call(
        db,
        settings,
        lead,
        purpose="checklist_suggest",
        prompt=prompt,
        schema=CHECKLIST_SCHEMA,
        name="checklist_items",
        model_cls=ChecklistOutput,
        client=client,
    )
    suggestions = []
    for position, item in enumerate(parsed.items[:MAX_SUGGESTIONS]):
        row = AiChecklistSuggestion(
            lead_id=lead.id, run_id=run_id, position=position, title=item.title, detail=item.detail[:2000]
        )
        db.add(row)
        suggestions.append(row)
    db.commit()
    return {
        "run_id": run_id,
        "input_hash": digest,
        "model": result.model,
        "suggestions": [
            {"id": row.id, "title": row.title, "detail": row.detail, "status": row.status} for row in suggestions
        ],
        "accept_each": True,
    }


def decide_suggestion(db: Session, suggestion_id, accept: bool, *, template_key="ai_added"):
    """Accept one suggestion into the lead's checklist, or reject it without a trace."""
    row = db.get(AiChecklistSuggestion, suggestion_id)
    if row is None:
        raise ValueError("Suggestion not found")
    if row.status != "pending":
        raise ValueError(f"This suggestion was already {row.status}")
    from ..db import utcnow

    row.status = "accepted" if accept else "rejected"
    row.resolved_at = utcnow()
    created = None
    if accept:
        created = LeadChecklistItem(
            lead_id=row.lead_id,
            template_key=template_key,
            template_item_id=None,
            position=1000 + (row.position or 0),
            title=row.title,
            detail=row.detail,
            source="ai",
        )
        db.add(created)
        db.add(
            AuditLog(
                lead_id=row.lead_id,
                action="checklist_suggestion_accepted",
                details={"suggestion_id": row.id, "run_id": row.run_id},
            )
        )
    db.commit()
    return {
        "id": row.id,
        "status": row.status,
        "checklist_item_id": created.id if created else None,
    }


def suggestions_for(db: Session, lead_id):
    rows = db.scalars(
        select(AiChecklistSuggestion)
        .where(AiChecklistSuggestion.lead_id == lead_id)
        .order_by(AiChecklistSuggestion.id.desc())
    ).all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "detail": row.detail,
            "status": row.status,
            "position": row.position,
            "run_id": row.run_id,
        }
        for row in rows
    ]


def advise(db: Session, settings, lead, *, client=None):
    """Return strict, schema-validated decision support, labelled as such and stored."""
    facts = lead_facts(db, lead, settings)
    prompt = (
        "You advise an acquisitions manager at a Texas real-estate investment company. Assess this lead.\n"
        "Rules: no legal, tax, financial or investment advice; no invented facts; no prices you were not given; "
        "name the exit strategies you considered only inside the single best one you return; state clearly what "
        "information is missing. Return JSON with keys: situation_summary (string), next_steps (3-7 short "
        "strings), do_not (2-5 short strings), risks (2-5 short strings), exit_strategy {name, reasoning, "
        "missing_information}, confidence (low|medium|high).\n"
        f"Facts:\n{_facts_prompt(facts)}"
    )
    run_id, digest, parsed, result = _call(
        db,
        settings,
        lead,
        purpose="advisor",
        prompt=prompt,
        schema=ADVISOR_SCHEMA,
        name="advisor_note",
        model_cls=AdvisorOutput,
        client=client,
    )
    row = db.get(GrokRun, run_id)
    row.output = {
        "advice": parsed.model_dump(),
        "disclaimer": ADVISOR_DISCLAIMER,
        "compliance": COMPLIANCE_REMINDER,
    }
    db.commit()
    return {
        "run_id": run_id,
        "input_hash": digest,
        "model": result.model,
        "created_at": row.created_at,
        "advice": parsed.model_dump(),
        "disclaimer": ADVISOR_DISCLAIMER,
        "compliance": COMPLIANCE_REMINDER,
        "decision_support_only": True,
    }


def latest_advice(db: Session, lead_id) -> Optional[dict]:
    """The Exit Strategy card: the most recent advisor note for this lead, if any."""
    row = db.scalar(
        select(GrokRun)
        .where(GrokRun.lead_id == lead_id, GrokRun.purpose == "advisor", GrokRun.state == "succeeded")
        .order_by(GrokRun.created_at.desc())
    )
    if row is None:
        return None
    return {
        "run_id": row.id,
        "model": row.model_id,
        "input_hash": row.input_hash,
        "created_at": row.created_at,
        **row.output,
    }
