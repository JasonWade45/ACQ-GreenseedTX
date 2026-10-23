"""Optional AI analysis + human-reviewed message drafting.

Rules enforced here:
  * Never invent facts. Unknowns are reported as unknown.
  * Every extracted claim carries an evidence reference when one exists.
  * Do Not Contact leads never receive marketing drafts.
  * Insufficient context produces an explicit refusal, not a generic message.
  * Nothing is ever sent — drafts are stored for the human to review and copy.
  * AI is optional: when no model is reachable the app still works on rules.
    Provider order: Groq cloud (GROQ_API_KEY) → local Ollama → rules.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AiInsight, CallPlan, Lead, MessageDraft
from app.services.leads import missing_fields, primary_property
from app.services.pipeline import CONTACT_OUTCOMES, STAGES
from app.services.settings_service import followup_rules

logger = logging.getLogger("acquisitions.ai")

MOTIVATION_KEYWORDS = {
    "foreclos": "Foreclosure pressure",
    "pre-foreclos": "Pre-foreclosure",
    "lien": "Tax or mechanic's lien pressure",
    "divorce": "Divorce",
    "inherit": "Inherited property",
    "probate": "Probate / estate",
    "tired landlord": "Tired landlord",
    "tenant": "Tenant-occupied, wants out",
    "relocat": "Relocation",
    "job": "Job change",
    "downsiz": "Downsizing",
    "upsid": "Upsizing",
    "bankrupt": "Bankruptcy",
    "medical": "Medical bills",
    "tax": "Tax burden",
    "repairs": "Cannot afford repairs",
    "too much work": "Cannot manage repairs",
    "motivated": "Self-described motivated seller",
    "as soon as possible": "Urgent timeline",
    "asap": "Urgent timeline",
    "cash": "Wants cash offer",
    "fast close": "Wants a fast close",
    "wholesale": "Aware of wholesale process",
}

OBJECTION_KEYWORDS = {
    "too low": "Price objection",
    "lowball": "Price objection",
    "not enough": "Price objection",
    "market value": "Price objection",
    "waiting": "Waiting for a better offer",
    "another offer": "Competing offer",
    "think about": "Needs time to decide",
    "talk to": "Needs to consult someone",
    "spouse": "Needs spouse/family approval",
    "attorney": "Attorney review",
    "agent": "Working with an agent",
    "unsure": "Undecided",
}


def ollama_available() -> tuple[bool, list[str], Optional[str]]:
    if not settings.ai_enabled:
        return False, [], "AI disabled by configuration (AI_ENABLED=false)"
    cooldown = _cooldown_reason()
    if cooldown:
        return False, [], cooldown
    try:
        with httpx.Client(timeout=3.0) as client:
            response = client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
            data = response.json()
            models = [m.get("name") for m in data.get("models", []) if isinstance(m, dict) and m.get("name")]
            return True, models, None
    except httpx.HTTPError as exc:
        return False, [], f"Ollama not reachable at {settings.ollama_base_url}: {exc.__class__.__name__}"
    except Exception as exc:  # noqa: BLE001
        return False, [], f"Ollama check failed: {exc.__class__.__name__}"


def groq_configured() -> bool:
    return bool((settings.groq_api_key or "").strip())


# --------------------------------------------------------------------------- #
# Generation failure cooldown (keeps the UI responsive when the model can't run)
# --------------------------------------------------------------------------- #
_last_generation_failure: Optional[datetime] = None
_last_generation_error: Optional[str] = None


def _note_generation_failure(error: str) -> None:
    global _last_generation_failure, _last_generation_error
    _last_generation_failure = datetime.utcnow()
    _last_generation_error = error


def _clear_generation_failures() -> None:
    global _last_generation_failure, _last_generation_error
    _last_generation_failure = None
    _last_generation_error = None


def _cooldown_reason() -> Optional[str]:
    if _last_generation_failure is None:
        return None
    elapsed = (datetime.utcnow() - _last_generation_failure).total_seconds()
    window = float(settings.ollama_failure_cooldown_seconds)
    if elapsed >= window:
        _clear_generation_failures()
        return None
    remaining = int(window - elapsed)
    return (
        f"AI generation skipped for {remaining}s after a failure "
        f"({(_last_generation_error or 'unknown error')[:160]}). Rule-based analysis is in use."
    )


def ai_status() -> dict[str, Any]:
    ollama_ok, models, ollama_error = ollama_available()
    groq_ok = groq_configured()
    cooldown = _cooldown_reason()

    ollama_model_in_use = settings.ollama_model if ollama_ok else None
    if ollama_ok and models and settings.ollama_model not in models:
        ollama_model_in_use = models[0]

    if groq_ok and not cooldown:
        engine = "groq"
        available = True
        model_in_use = settings.groq_model
        error = None
        message = f"Groq cloud model ready ({settings.groq_model})."
        if ollama_ok:
            message += f" Local Ollama ({ollama_model_in_use}) is the fallback."
    elif ollama_ok:
        engine = "ollama"
        available = True
        model_in_use = ollama_model_in_use
        error = None if not groq_ok else cooldown
        message = f"Local model ready ({ollama_model_in_use})."
    else:
        engine = "rules"
        available = False
        model_in_use = None
        error = cooldown or ollama_error
        if cooldown:
            message = cooldown
        elif groq_ok:
            message = (
                "Groq is configured but temporarily unavailable (see details); "
                "rule-based analysis and draft templates are in use."
            )
        elif error and error.startswith("AI disabled"):
            message = (
                "Model execution is switched off (AI_ENABLED=false in backend/.env) and no Groq key is set. "
                "Rule-based analysis and draft templates are in use."
            )
        else:
            message = (
                "No AI model available — rule-based analysis and templates are in use. "
                "Set GROQ_API_KEY in backend/.env (fast, cloud) or install Ollama "
                "(https://ollama.com) and run `ollama pull llama3.1:8b`."
            )

    return {
        "available": available,
        "configured_model": settings.groq_model if groq_ok else settings.ollama_model,
        "model_in_use": model_in_use,
        "models": models,
        "base_url": settings.ollama_base_url,
        "error": error,
        "engine": engine,
        "groq": {
            "configured": groq_ok,
            "model": settings.groq_model,
            "base_url": settings.groq_base_url,
        },
        "disclaimer": (
            "AI output is advisory and must be reviewed by a person before it is used. "
            "Nothing in this application sends messages, emails or calls to sellers."
        ),
        "message": message,
    }


def _ollama_generate(prompt: str, model: str) -> Optional[str]:
    try:
        with httpx.Client(timeout=settings.ollama_timeout_seconds) as client:
            response = client.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.2, "num_ctx": int(settings.ollama_num_ctx)},
                },
            )
            response.raise_for_status()
            data = response.json()
            _clear_generation_failures()
            answer = data.get("response")
            return _repair_mojibake(answer) if isinstance(answer, str) else answer
    except httpx.HTTPStatusError as exc:
        detail = f"HTTP {exc.response.status_code}"
        try:
            body = exc.response.json()
            if isinstance(body, dict) and body.get("error"):
                detail = f"{detail}: {body['error']}"
            else:
                detail = f"{detail}: {exc.response.text[:200]}"
        except Exception:  # noqa: BLE001
            detail = f"{detail}: {exc.response.text[:200]}"
        logger.warning("Ollama generation failed: %s", detail)
        _note_generation_failure(detail)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ollama generation failed: %s", exc)
        _note_generation_failure(f"{exc.__class__.__name__}: {exc}")
        return None


def _repair_mojibake(text: str) -> str:
    """Undo UTF-8 bytes that were decoded as latin-1.

    LLM serving occasionally emits text that is UTF-8 interpreted as latin-1
    ("What\xe2\x80\x99s" arrives as 'Whatâ\\x80\\x99s'), non-deterministically.
    Strings with C1 control characters (U+0080–U+009F) never occur in clean
    prose, so they are the reliable tell; multi-pass repairs rows that were
    already double-encoded in storage. No-op for clean text.
    """
    for _ in range(4):
        if not text or not any(0x80 <= ord(ch) <= 0x9F for ch in text):
            return text
        try:
            fixed = text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return text
        if fixed == text:
            return text
        text = fixed
    return text


def _groq_generate(prompt: str) -> Optional[str]:
    """Chat completion via Groq's OpenAI-compatible API (strict JSON responses).

    HTTP 429 is retried with the server's Retry-After (capped) before giving up,
    so long batch runs ride out transient rate limits instead of failing over.
    """
    last_detail = "Groq request failed"
    for attempt in range(3):
        try:
            with httpx.Client(timeout=settings.groq_timeout_seconds) as client:
                response = client.post(
                    f"{settings.groq_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                    json={
                        "model": settings.groq_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.2,
                    },
                )
                if response.status_code == 429 and attempt < 2:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = min(float(retry_after), 30.0) if retry_after else 8.0 * (attempt + 1)
                    except ValueError:
                        delay = 8.0 * (attempt + 1)
                    logger.info("Groq rate limited; retrying in %.0fs (attempt %d)", delay, attempt + 1)
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices") if isinstance(data, dict) else None
                content = None
                if choices and isinstance(choices[0], dict):
                    message = choices[0].get("message") or {}
                    content = message.get("content")
                if isinstance(content, str) and content.strip():
                    content = _repair_mojibake(content)
                    _clear_generation_failures()
                    return content
            logger.warning("Groq returned no message content")
            _note_generation_failure("Groq returned no message content")
            return None
        except httpx.HTTPStatusError as exc:
            detail = f"HTTP {exc.response.status_code}"
            try:
                body = exc.response.json()
                if isinstance(body, dict):
                    err = body.get("error") or body.get("message")
                    detail = f"{detail}: {err}" if err else f"{detail}: {exc.response.text[:200]}"
                else:
                    detail = f"{detail}: {exc.response.text[:200]}"
            except Exception:  # noqa: BLE001
                detail = f"{detail}: {exc.response.text[:200]}"
            last_detail = detail
            if exc.response.status_code != 429:
                break
        except Exception as exc:  # noqa: BLE001
            last_detail = f"{exc.__class__.__name__}: {exc}"
            break
    logger.warning("Groq generation failed: %s", last_detail)
    _note_generation_failure(last_detail)
    return None


def _model_generate(prompt: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Provider chain: Groq (cloud) → Ollama (local) → None (rules fallback).

    Returns (text, engine, model); engine/model are None when nothing produced text.
    """
    cooldown = _cooldown_reason()
    if cooldown:
        return None, None, None
    if groq_configured():
        raw = _groq_generate(prompt)
        if raw:
            return raw, "groq", settings.groq_model
        # Groq failed (cooldown now active) — fall through to local if possible.
        if _cooldown_reason():
            return None, None, None
    available, models, _error = ollama_available()
    if available:
        model = settings.ollama_model
        if models and model not in models:
            model = models[0]
        raw = _ollama_generate(prompt, model)
        if raw:
            return raw, "ollama", model
    return None, None, None


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    text = _repair_mojibake(text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def ai_map_columns(
    headers: list[str],
    samples: dict[str, list[str]],
    targets: list[dict[str, str]],
) -> tuple[Optional[dict[str, str]], Optional[str], Optional[str]]:
    """Ask the active model to map spreadsheet headers onto CRM field keys.

    Returns ({target_key: header}, engine, error). The reply is advisory: keys
    outside `target`, headers not present in the file and reuse of an already
    mapped header are all dropped here — the caller merges only into fields the
    rule-based mapper left empty.
    """
    if not targets or not headers:
        return None, None, None
    target_lines = [f"- {t['key']}: {t['label']} ({t.get('type') or 'string'})" for t in targets]
    header_lines = []
    for header in headers:
        values = [str(v) for v in (samples.get(header) or []) if v not in (None, "")][:3]
        suffix = f" — e.g. {values}" if values else ""
        header_lines.append(f'- "{header}"{suffix}')
    prompt = (
        "You map column headers of a US residential real-estate seller-lead "
        "spreadsheet onto CRM field keys.\n"
        'Reply with ONLY one JSON object like {"field_key": "exact header from the list", ...}. '
        "Map only headers that clearly fit a field; use null for the rest. "
        "Each header may be used at most once. No commentary.\n\n"
        "Field keys:\n" + "\n".join(target_lines)
        + "\n\nHeaders (with sample values):\n" + "\n".join(header_lines)
    )
    text, engine, _model = _model_generate(prompt)
    if not text:
        return None, None, None
    parsed = _extract_json(text)
    if not parsed:
        return None, engine, "Model reply was not valid JSON"
    header_set = set(headers)
    by_lower = {h.lower(): h for h in headers}
    result: dict[str, str] = {}
    used: set[str] = set()
    for target in targets:
        raw = parsed.get(target["key"])
        if not isinstance(raw, str):
            continue
        wanted = raw.strip()
        header = wanted if wanted in header_set else by_lower.get(wanted.lower())
        if header and header not in used:
            result[target["key"]] = header
            used.add(header)
    return result, engine, None


# --------------------------------------------------------------------------- #
# Context gathering
# --------------------------------------------------------------------------- #
def _property_facts(prop: Any) -> Optional[dict[str, Any]]:
    """Distill the extracted payload blocks (propertyInfo/valuation/tax/mortgage)
    into the handful of numbers and flags that actually matter for analysis and
    call prep. Only non-empty values are kept."""
    extra = prop.extra if isinstance(getattr(prop, "extra", None), dict) else {}
    info = extra.get("property_info") if isinstance(extra.get("property_info"), dict) else {}
    valuation = extra.get("valuation") if isinstance(extra.get("valuation"), dict) else {}
    tax = extra.get("tax") if isinstance(extra.get("tax"), dict) else {}
    mortgage = extra.get("mortgage") if isinstance(extra.get("mortgage"), dict) else {}
    mls = extra.get("mls") if isinstance(extra.get("mls"), dict) else {}
    sale = extra.get("last_sale") if isinstance(extra.get("last_sale"), dict) else {}

    facts: dict[str, Any] = {
        "owner_occupied": info.get("ownerOccupied"),
        "absentee_owner": info.get("isAbsenteeOwner"),
        "out_of_state_owner": info.get("out_of_state_owner"),
        "vacant": info.get("vacant"),
        "inherited": info.get("inherited"),
        "pre_foreclosure": info.get("preForeclosure"),
        "years_owned": info.get("yearsOwned"),
        "equity_percent": info.get("equityPercent"),
        "est_equity": valuation.get("estEquity"),
        "assessed_value": tax.get("totalAssessedValue"),
        "market_value": tax.get("totalmarketValue") or tax.get("marketValue"),
        "property_taxes": tax.get("propertyTaxes"),
        "tax_delinquent_year": tax.get("taxDelinquentYear"),
        "mortgage_balance": mortgage.get("amount") or mortgage.get("currentLoanBalance"),
        "mortgage_lender": mortgage.get("lenderName"),
        "last_sale_amount": sale.get("saleAmount"),
        "mls_status": mls.get("status"),
        "mls_price": mls.get("price"),
    }
    drop = {k for k, v in facts.items() if v is None or v == "" or v == []}
    facts = {k: v for k, v in facts.items() if k not in drop}
    if facts.get("tax_delinquent_year") in (0, "0"):
        facts.pop("tax_delinquent_year", None)
    return facts or None


def build_context(lead: Lead) -> dict[str, Any]:
    prop = primary_property(lead)
    activities = []
    for a in lead.activities[:25]:
        activities.append(
            {
                "activity_id": a.id,
                "external_id": a.external_id,
                "type": a.activity_type,
                "direction": a.direction,
                "outcome": a.outcome,
                "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
                "summary": a.summary,
                "detail": (a.detail or "")[:500],
                "source": a.source,
            }
        )
    appointments = [
        {
            "id": a.id,
            "scheduled_at": a.scheduled_at.isoformat() if a.scheduled_at else None,
            "status": a.status,
            "type": a.appointment_type,
            "notes": a.notes,
            "source": a.source,
        }
        for a in lead.appointments[:10]
    ]
    followups = [
        {
            "id": f.id,
            "due_at": f.due_at.isoformat() if f.due_at else None,
            "status": f.status,
            "reason": f.reason,
            "action": f.suggested_next_action,
        }
        for f in lead.followups[:10]
    ]
    return {
        "lead": {
            "id": lead.id,
            "external_id": lead.external_id,
            "name": lead.display_name,
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "phone": lead.primary_phone,
            "email": lead.email,
            "stage": lead.pipeline_stage,
            "stage_label": STAGES.get(lead.pipeline_stage, {}).get("label"),
            "source_status": lead.source_status,
            "contact_status": lead.contact_status,
            "source": lead.lead_source,
            "created": lead.created_at.isoformat() if lead.created_at else None,
            "last_contact_at": lead.last_contact_at.isoformat() if lead.last_contact_at else None,
            "next_followup_at": lead.next_followup_at.isoformat() if lead.next_followup_at else None,
            "do_not_contact": lead.do_not_contact,
            "tags": lead.tags or [],
            "notes": lead.notes,
            "origin": lead.origin,
        },
        "property": (
            {
                "address": prop.formatted_address,
                "city": prop.city,
                "state": prop.state,
                "zip": prop.zip_code,
                "county": prop.county,
                "type": prop.property_type,
                "beds": prop.bedrooms,
                "baths": prop.bathrooms,
                "sqft": prop.square_footage,
                "year_built": prop.year_built,
                "lot_acres": prop.lot_acres,
                "latitude": prop.latitude,
                "longitude": prop.longitude,
                "asking_price": prop.asking_price,
                "estimated_value": prop.estimated_value,
                "repair_estimate": prop.repair_estimate,
                "facts": _property_facts(prop),
            }
            if prop
            else None
        ),
        "activities": activities,
        "appointments": appointments,
        "followups": followups,
        "missing": [m["label"] for m in missing_fields(lead)],
    }


def context_hash(context: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "lead": context["lead"],
            "property": context["property"],
            "activities": context["activities"][:5],
            "appointments": context["appointments"][:3],
            "followups": context["followups"][:3],
            "missing": context["missing"],
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
def analyze_lead(db: Session, lead: Lead, force: bool = False) -> AiInsight:
    context = build_context(lead)
    digest = context_hash(context)
    if not force and lead.analysis_input_hash == digest and lead.insights:
        return lead.insights[0]

    raw, engine, model = _model_generate(_analysis_prompt(context))
    parsed = _extract_json(raw or "")
    if parsed and engine:
        insight = _insight_from_model(lead, parsed, model or "", context, engine=engine)
        _store_insight(db, lead, insight, digest)
        return insight

    insight = _rule_based_analysis(lead, context)
    _store_insight(db, lead, insight, digest)
    return insight


def _store_insight(db: Session, lead: Lead, insight: AiInsight, digest: str) -> None:
    db.add(insight)
    lead.analysis_input_hash = digest
    db.commit()
    db.refresh(insight)


def _records_budget() -> int:
    """Keep the RECORDS block inside the model context window (tokens ~= chars / 4)."""
    return max(1200, (int(settings.ollama_num_ctx) - 400) * 4)


def _analysis_prompt(context: dict[str, Any]) -> str:
    return (
        "You are an analyst for a US residential real-estate acquisitions team. "
        "Analyze this seller lead using ONLY the provided records. Do not invent facts.\n"
        "Return STRICT JSON with keys: summary (string), seller_motivation (string or 'Unknown'), "
        "urgency_indicators (array of strings), price_information (object with asking_price, "
        "estimated_value, repair_estimate - use null when unknown), objections (array), "
        "missing_information (array), recommended_next_action (string), "
        "suggested_followup_timing (string like 'in 2 days' or 'Unknown'), "
        "confidence (low|medium|high), evidence (array of {ref, quote}).\n"
        "Distinguish facts stated in records from inference. If information is missing say Unknown.\n\n"
        f"RECORDS:\n{json.dumps(context, indent=2, default=str)[:_records_budget()]}"
    )


def _insight_from_model(
    lead: Lead, parsed: dict[str, Any], model: str, context: dict[str, Any], engine: str = "ollama"
) -> AiInsight:
    timing = str(parsed.get("suggested_followup_timing") or "Unknown")
    suggested_at = None
    match = re.search(r"(\d+)\s*day", timing, re.I)
    if match:
        suggested_at = datetime.utcnow() + timedelta(days=int(match.group(1)))
    elif re.search(r"today|asap|immediate", timing, re.I):
        suggested_at = datetime.utcnow()
    return AiInsight(
        lead_id=lead.id,
        summary=str(parsed.get("summary") or "")[:4000] or None,
        seller_motivation=str(parsed.get("seller_motivation") or "Unknown"),
        urgency_indicators=[str(x) for x in (parsed.get("urgency_indicators") or [])][:10],
        price_information=parsed.get("price_information") if isinstance(parsed.get("price_information"), dict) else {},
        objections=[str(x) for x in (parsed.get("objections") or [])][:10],
        missing_information=[str(x) for x in (parsed.get("missing_information") or context.get("missing") or [])][:15],
        recommended_next_action=str(parsed.get("recommended_next_action") or "")[:1000] or None,
        suggested_followup_at=suggested_at,
        evidence=parsed.get("evidence") if isinstance(parsed.get("evidence"), list) else [],
        confidence=str(parsed.get("confidence") or "low"),
        engine=engine,
        model=model,
    )


def _rule_based_analysis(lead: Lead, context: dict[str, Any]) -> AiInsight:
    """Deterministic, transparent analysis when no local model is available."""
    text_blobs: list[tuple[str, str]] = []
    if lead.notes:
        text_blobs.append(("lead notes", lead.notes))
    for a in lead.activities[:25]:
        if a.detail:
            text_blobs.append((f"activity {a.id}", a.detail))
        if a.summary:
            text_blobs.append((f"activity {a.id} summary", a.summary))
    for ap in lead.appointments[:5]:
        if ap.notes:
            text_blobs.append((f"appointment {ap.id}", ap.notes))

    motivations: list[dict[str, str]] = []
    objections: list[dict[str, str]] = []
    urgency: list[str] = []
    for ref, blob in text_blobs:
        low = blob.lower()
        for keyword, label in MOTIVATION_KEYWORDS.items():
            if keyword in low and label not in [m["label"] for m in motivations]:
                motivations.append({"label": label, "evidence": f"{ref}: {blob[:180]}"})
        for keyword, label in OBJECTION_KEYWORDS.items():
            if keyword in low and label not in [o["label"] for o in objections]:
                objections.append({"label": label, "evidence": f"{ref}: {blob[:180]}"})

    if lead.do_not_contact:
        urgency.append("Do Not Contact flag is set — no outreach permitted")
    if lead.contact_status == "callback_requested":
        urgency.append("Seller requested a callback")
    if lead.pipeline_stage in {"offer_made", "negotiation", "contract_sent", "under_contract"}:
        urgency.append(f"Active deal stage: {STAGES.get(lead.pipeline_stage, {}).get('label')}")
    if lead.next_followup_at and lead.next_followup_at < datetime.utcnow():
        urgency.append("Follow-up is overdue")

    missing = [m["label"] for m in missing_fields(lead)]
    prop = primary_property(lead)
    price_info = {
        "asking_price": prop.asking_price if prop else None,
        "estimated_value": prop.estimated_value if prop else None,
        "repair_estimate": prop.repair_estimate if prop else None,
        "source": "property record",
    }

    parts = []
    parts.append(f"{lead.display_name} is at stage '{STAGES.get(lead.pipeline_stage, {}).get('label')}'.")
    if lead.contact_status:
        parts.append(f"Contact status: {CONTACT_OUTCOMES.get(lead.contact_status, {}).get('label', lead.contact_status)}.")
    if lead.last_contact_at:
        parts.append(f"Last contact {lead.last_contact_at.date().isoformat()}.")
    else:
        parts.append("No successful contact recorded.")
    if lead.notes:
        parts.append(f"Notes on file: {lead.notes[:200]}")
    if missing:
        parts.append("Missing: " + ", ".join(missing) + ".")
    if not text_blobs and not lead.notes:
        parts.append("Not enough context for a deeper analysis — more activity history is required.")

    recommended = _default_next_action(lead)

    insight = AiInsight(
        lead_id=lead.id,
        summary=" ".join(parts),
        seller_motivation=motivations[0]["label"] if motivations else "Unknown — not stated in available records",
        urgency_indicators=urgency,
        price_information=price_info,
        objections=[o["label"] for o in objections],
        missing_information=missing,
        recommended_next_action=recommended,
        suggested_followup_at=None,
        evidence=[{"ref": m["evidence"], "quote": m["evidence"]} for m in motivations[:5]]
        + [{"ref": o["evidence"], "quote": o["evidence"]} for o in objections[:5]],
        confidence="low" if not text_blobs else "medium",
        engine="rules",
        model=None,
    )
    if lead.pipeline_stage in {"offer_made", "negotiation"}:
        insight.suggested_followup_at = datetime.utcnow() + timedelta(days=1)
    elif lead.pipeline_stage in {"contacted", "qualified", "follow_up"}:
        insight.suggested_followup_at = datetime.utcnow() + timedelta(days=2)
    return insight


def _default_next_action(lead: Lead) -> str:
    stage = lead.pipeline_stage
    if lead.do_not_contact:
        return "Do not contact. Review the restriction before any outreach."
    if lead.contact_status == "callback_requested":
        return "Call the seller back at the time they requested."
    if stage in {"new", "not_contacted"}:
        return "Make the first outreach attempt and record the outcome."
    if stage == "attempting_contact":
        return "Another contact attempt — vary the time of day and channel."
    if stage == "contacted":
        return "Qualify the seller: timeline, motivation, property condition, asking price."
    if stage == "qualified":
        return "Schedule the property visit and prepare a offer range."
    if stage == "follow_up":
        return "Work the scheduled follow-up and update the stage based on the response."
    if stage == "appointment_set":
        return "Confirm the appointment and prepare for the walkthrough."
    if stage == "offer_made":
        return "Follow up on the outstanding offer and record the seller's decision."
    if stage == "negotiation":
        return "Move the negotiation toward contract; address the stated objections."
    if stage == "contract_sent":
        return "Chase the signature and check for title/escrow blockers."
    if stage == "under_contract":
        return "Track contingency dates and keep the seller informed."
    if stage == "closed":
        return "No further acquisition activity required."
    if stage == "nurture":
        return "Re-check in the nurture window; do not over-contact."
    if stage == "dead":
        return "No action unless new information arrives."
    return "Review the lead and choose the next step."


# --------------------------------------------------------------------------- #
# Drafting
# --------------------------------------------------------------------------- #
def _has_sufficient_context(lead: Lead, context: dict[str, Any]) -> tuple[bool, Optional[str]]:
    if lead.do_not_contact:
        return False, "This lead is flagged Do Not Contact. Marketing drafts are blocked."
    if lead.pipeline_stage in {"closed", "dead"}:
        return False, f"Lead is at stage '{STAGES.get(lead.pipeline_stage, {}).get('label')}' — drafting is not appropriate."
    named = bool(lead.first_name or lead.last_name)
    has_contact = bool(lead.primary_phone or lead.email)
    has_property = bool(context.get("property"))
    has_history = bool(lead.activities or lead.notes)
    if not (named or has_property):
        return False, "Not enough verified context: we have neither a seller name nor a property address."
    if not has_contact:
        return False, "Not enough verified context: this lead has no phone number or email on file."
    if not has_history and lead.contact_status == "never_contacted" and lead.pipeline_stage in {"new", "not_contacted"}:
        # A first-touch note is acceptable, but we mark it as low-context.
        return True, None
    if not has_history and not has_property:
        return False, "Not enough context to reference anything specific in a follow-up."
    return True, None


def generate_draft(db: Session, lead: Lead, channel: str = "text", force: bool = False) -> MessageDraft:
    context = build_context(lead)
    ok, refusal = _has_sufficient_context(lead, context)
    if not ok:
        draft = MessageDraft(
            lead_id=lead.id,
            channel_hint=channel,
            body="",
            refusal_reason=refusal,
            context_used=[],
            engine="rules",
        )
        db.add(draft)
        db.commit()
        db.refresh(draft)
        return draft

    context_refs = _context_references(lead, context)
    raw, engine, model = _model_generate(_draft_prompt(lead, context, channel))
    parsed = _extract_json(raw or "")
    body = None
    if parsed:
        body = str(parsed.get("message") or parsed.get("draft") or "").strip()
    if body and len(body) > 40 and engine:
        draft = MessageDraft(
            lead_id=lead.id,
            channel_hint=channel,
            body=body,
            context_used=context_refs,
            engine=engine,
            model=model,
        )
        db.add(draft)
        db.commit()
        db.refresh(draft)
        return draft

    draft = MessageDraft(
        lead_id=lead.id,
        channel_hint=channel,
        body=_template_draft(lead, context),
        context_used=context_refs,
        engine="rules",
        model=None,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def _context_references(lead: Lead, context: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if context["property"]:
        refs.append({"type": "property", "value": context["property"]["address"]})
    if lead.last_contact_at:
        refs.append({"type": "last_contact", "value": lead.last_contact_at.isoformat()})
    for a in context["activities"][:3]:
        refs.append({"type": "activity", "id": a["activity_id"], "value": a.get("summary") or a.get("detail")})
    if lead.notes:
        refs.append({"type": "notes", "value": lead.notes[:200]})
    return refs


def _draft_prompt(lead: Lead, context: dict[str, Any], channel: str) -> str:
    first = lead.first_name or "there"
    return (
        "You draft a short, professional follow-up message from a US real-estate "
        "acquisitions manager to a property seller. Rules:\n"
        "- Natural American English, warm but professional, under 600 characters.\n"
        "- Use only verified facts from the records. Never invent offers, prices, "
        "appointments, or prior conversations.\n"
        "- Do not mention cash offers or guarantees unless present in the records.\n"
        "- Do not pressure. End with a simple question.\n"
        "- Channel: " + channel + ".\n"
        f"- Address the seller as '{first}'.\n"
        "Return STRICT JSON: {\"message\": \"...\"}.\n\n"
        f"RECORDS:\n{json.dumps(context, indent=2, default=str)[:_records_budget()]}"
    )


def _template_draft(lead: Lead, context: dict[str, Any]) -> str:
    first = lead.first_name or "there"
    address = (context.get("property") or {}).get("address")
    stage = lead.pipeline_stage
    location = f" the property at {address}" if address else " your property"

    if lead.contact_status == "callback_requested":
        base = (
            f"Hi {first}, this is the acquisitions team following up on your request for a call about"
            f"{location}. When is a good time for you today or tomorrow?"
        )
    elif stage in {"new", "not_contacted"}:
        base = (
            f"Hi {first}, this is the acquisitions team. We work with homeowners in your area and"
            f" wanted to reach out about{location}. Are you open to discussing a possible sale?"
        )
    elif stage == "attempting_contact":
        base = (
            f"Hi {first}, trying you again about{location}. If now isn't a good time, just let me know"
            " a better window and I'll work around your schedule."
        )
    elif stage == "offer_made":
        base = (
            f"Hi {first}, checking in on the offer we discussed for{location}. Happy to walk through the"
            " numbers again or answer any questions — what would help?"
        )
    elif stage == "negotiation":
        base = (
            f"Hi {first}, following up on our discussion about{location}. I want to make sure we land on"
            " terms that work for you. What's your thinking right now?"
        )
    elif stage in {"contract_sent", "under_contract"}:
        base = (
            f"Hi {first}, just checking that you received everything for{location} and answering any"
            " questions you have. Let me know the best number to reach you."
        )
    elif stage == "appointment_set":
        base = (
            f"Hi {first}, confirming our upcoming appointment for{location}. Reply here if you need to"
            " move the time and I'll adjust."
        )
    else:
        base = (
            f"Hi {first}, checking in about{location}. Is this still something you'd like to explore, "
            "or has your timeline changed?"
        )

    if lead.notes:
        snippet = lead.notes.strip().split(".")[0][:120]
        if snippet:
            base += f"\n\n(For your context — internal note: {snippet})"
    return base


def draft_history(db: Session, lead: Lead) -> list[MessageDraft]:
    return db.query(MessageDraft).filter(MessageDraft.lead_id == lead.id).order_by(MessageDraft.created_at.desc()).all()


# --------------------------------------------------------------------------- #
# Pre-call plan: opener + talking points + question checklist (advisory)
# --------------------------------------------------------------------------- #
def get_call_plan(db: Session, lead: Lead) -> Optional[CallPlan]:
    return (
        db.query(CallPlan)
        .filter(CallPlan.lead_id == lead.id)
        .order_by(CallPlan.created_at.desc())
        .first()
    )


def _call_plan_refusal(lead: Lead, context: dict[str, Any]) -> tuple[bool, Optional[str]]:
    if lead.do_not_contact:
        return True, "This lead is flagged Do Not Contact — no outreach script should be prepared."
    if not lead.primary_phone:
        return True, "No phone number on file — there is nothing to call."
    if not (lead.first_name or lead.last_name) and not context.get("property"):
        return True, "Not enough verified context: neither a seller name nor a property address."
    return False, None


def _call_plan_prompt(context: dict[str, Any]) -> str:
    return (
        "You are preparing a phone-call plan for a US residential real-estate "
        "acquisitions team that is about to call a property seller. Use ONLY the "
        "provided records — never invent facts, offers, prices, valuations or past "
        "conversations. Use the literal placeholder '[your name]' for the caller's "
        "identity; do not invent a name or company.\n"
        "Return STRICT JSON with keys:\n"
        "opener (string: 1-3 short spoken sentences of natural American English, "
        "referencing the property address when it is known),\n"
        "talking_points (array of 3-6 objects {\"text\": string}: grounded observations "
        "from the records the caller can raise and confirm, e.g. ownership duration, "
        "equity, valuation, occupancy — only when those facts exist in the records),\n"
        "questions (array of 5-9 objects {\"text\": string, \"required\": boolean}: what to "
        "ask and in what spirit; required=true ONLY for motivation, timeline, and "
        "price/offer expectation; include questions covering every item listed under "
        "'missing'),\n"
        "do_not_say (array of 3-5 short strings: compliance guardrails).\n\n"
        f"RECORDS:\n{json.dumps(context, indent=2, default=str)[:_records_budget()]}"
    )


def _sanitize_call_plan(parsed: dict[str, Any]) -> Optional[dict[str, Any]]:
    opener = str(parsed.get("opener") or "").strip()
    if len(opener) < 15:
        return None
    talking_points: list[dict[str, Any]] = []
    for item in (parsed.get("talking_points") or [])[:8]:
        text = item.get("text") if isinstance(item, dict) else item
        text = str(text or "").strip()
        if text:
            talking_points.append({"text": text[:300], "used": False})
    questions: list[dict[str, Any]] = []
    for item in (parsed.get("questions") or [])[:12]:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            required = bool(item.get("required"))
        else:
            text = str(item or "").strip()
            required = False
        if text:
            questions.append({"text": text[:300], "asked": False, "required": required})
    if not questions:
        return None
    do_not_say = [str(s).strip()[:200] for s in (parsed.get("do_not_say") or [])[:8] if str(s).strip()]
    return {
        "opener": opener[:800],
        "talking_points": talking_points,
        "questions": questions,
        "do_not_say": do_not_say,
    }


def _rule_based_call_plan(lead: Lead, context: dict[str, Any]) -> dict[str, Any]:
    first = lead.first_name or "there"
    prop = context.get("property") or {}
    facts = prop.get("facts") or {}
    address = prop.get("address")
    location = f" about the property at {address}" if address else " about your property"
    opener = f"Hi {first}, this is [your name] with [company] — I'm calling{location}. Did I catch you at a good time?"

    talking_points: list[dict[str, Any]] = []

    def point(text: str) -> None:
        if len(talking_points) < 6:
            talking_points.append({"text": text[:300], "used": False})

    est = prop.get("estimated_value")
    if est:
        point(f"REsimpli's valuation estimate for the property is ${int(est):,} — use it as context, never as an offer.")
    if facts.get("years_owned"):
        point(f"Records show {facts['years_owned']} years of ownership — ownership duration is confirmed.")
    if facts.get("equity_percent") is not None:
        point(f"Recorded equity is about {facts['equity_percent']}% of value.")
    if facts.get("mortgage_balance"):
        lender = facts.get("mortgage_lender") or "a recorded lender"
        point(f"Mortgage balance of ${int(facts['mortgage_balance']):,} with {lender} — confirm it is the only lien.")
    if facts.get("vacant"):
        point("Property is flagged vacant — confirm who holds the keys.")
    elif facts.get("owner_occupied"):
        point("County records show the owner occupies the property.")
    if facts.get("absentee_owner") or facts.get("out_of_state_owner"):
        point("Owner has a different mailing address — confirm who currently lives at the property.")
    if facts.get("inherited"):
        point("Inherited-property flag is set — expect extra decision makers.")
    if facts.get("tax_delinquent_year"):
        point(f"Tax records show a delinquency for {facts['tax_delinquent_year']} — ask if it is resolved.")
    if facts.get("pre_foreclosure"):
        point("Pre-foreclosure flag is set — timeline questions matter most.")
    if facts.get("mls_status"):
        point(f"MLS status on record: {facts['mls_status']}.")
    if prop.get("beds") and prop.get("sqft"):
        point(f"Subject: {prop['beds']} bed / {prop.get('baths') or '?'} bath, {int(prop['sqft']):,} sq ft, built {prop.get('year_built') or 'unknown year'}.")
    if not talking_points:
        point("No property facts beyond the address are on file — gather everything from scratch.")

    questions: list[dict[str, Any]] = []

    def ask(text: str, required: bool = False) -> None:
        if len(questions) < 10:
            questions.append({"text": text[:300], "asked": False, "required": required})

    if lead.pipeline_stage == "dead":
        ask("The lead was marked dead in the CRM — is the situation the same, or worth another look?", False)
    ask("What's your main reason for considering a sale?", True)
    ask("What timeline are you working with?", True)
    ask("What price did you have in mind?", True)
    ask("What condition is the property in — any repairs needed?", False)
    ask("Is it owner-occupied, vacant, or tenant-occupied?", False)
    if facts.get("mortgage_balance"):
        lender = facts.get("mortgage_lender") or "the recorded lender"
        ask(f"Balance with {lender} is about ${int(facts['mortgage_balance']):,} — is that the only lien to pay off?", False)
    else:
        ask("Are there any mortgages or liens to pay off at closing?", False)
    if lead.email and not lead.primary_phone:
        ask("What's the best phone number and time to reach you?", False)
    else:
        ask("Who else is involved in the decision, and who handles access for a walkthrough?", False)

    missing = context.get("missing") or []
    for label in missing[:3]:
        ask(f"We don't have {str(label).lower()} on file — can you fill that in?", False)

    do_not_say = [
        "Do not guarantee a sale price or that any offer will be accepted.",
        "Do not promise appraisals, repairs or closing dates you cannot control.",
        "Do not invent prior conversations, offers or valuations.",
        "No pressure tactics, false deadlines or manufactured urgency.",
    ]
    return {
        "opener": opener[:800],
        "talking_points": talking_points,
        "questions": questions,
        "do_not_say": do_not_say,
    }


def build_call_plan(db: Session, lead: Lead, force: bool = False) -> CallPlan:
    """Generate (or return the stored) pre-call plan for a lead.

    Checkbox state lives in ``talking_points[].used`` / ``questions[].asked``
    and is preserved until an explicit force-regenerate rebuilds the plan.
    """
    existing = get_call_plan(db, lead)
    if existing and not force:
        return existing

    context = build_context(lead)
    plan = existing or CallPlan(lead_id=lead.id)

    refused, reason = _call_plan_refusal(lead, context)
    if refused:
        plan.refusal_reason = reason
        plan.engine = "rules"
        plan.model = None
        plan.opener = None
        plan.talking_points = []
        plan.questions = []
        plan.do_not_say = []
        plan.context_used = []
        if existing is None:
            db.add(plan)
        db.commit()
        db.refresh(plan)
        return plan

    plan.context_used = _context_references(lead, context)
    raw, engine, model = _model_generate(_call_plan_prompt(context))
    parsed = _extract_json(raw or "")
    fields = _sanitize_call_plan(parsed) if parsed else None
    if fields and engine:
        plan.opener = fields["opener"]
        plan.talking_points = fields["talking_points"]
        plan.questions = fields["questions"]
        plan.do_not_say = fields["do_not_say"]
        plan.engine = engine
        plan.model = model
    else:
        fallback = _rule_based_call_plan(lead, context)
        plan.opener = fallback["opener"]
        plan.talking_points = fallback["talking_points"]
        plan.questions = fallback["questions"]
        plan.do_not_say = fallback["do_not_say"]
        plan.engine = "rules"
        plan.model = None
    plan.refusal_reason = None
    if existing is None:
        db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def update_call_plan(
    db: Session,
    plan: CallPlan,
    *,
    opener: Optional[str] = None,
    talking_points: Optional[list] = None,
    questions: Optional[list] = None,
) -> CallPlan:
    """Persist checkbox / text edits. Unknown keys in items are dropped."""
    if opener is not None:
        plan.opener = opener[:800]
    if talking_points is not None:
        cleaned = []
        for item in talking_points[:12]:
            if isinstance(item, dict) and str(item.get("text") or "").strip():
                cleaned.append({"text": str(item["text"]).strip()[:300], "used": bool(item.get("used"))})
        plan.talking_points = cleaned
    if questions is not None:
        cleaned = []
        for item in questions[:16]:
            if isinstance(item, dict) and str(item.get("text") or "").strip():
                cleaned.append(
                    {
                        "text": str(item["text"]).strip()[:300],
                        "asked": bool(item.get("asked")),
                        "required": bool(item.get("required")),
                    }
                )
        plan.questions = cleaned
    db.commit()
    db.refresh(plan)
    return plan


def analyze_all_changed(db: Session, limit: int = 100) -> dict[str, Any]:
    """Re-analyze leads whose context changed — and upgrade rule-engine insights
    to the live model engine when one is available."""
    model_ready = ai_status()["available"]
    leads = db.query(Lead).filter(Lead.do_not_contact.is_(False)).order_by(Lead.updated_at.desc()).limit(limit).all()
    analyzed = skipped = 0
    for index, lead in enumerate(leads):
        context = build_context(lead)
        digest = context_hash(context)
        cached = lead.analysis_input_hash == digest and bool(lead.insights)
        if cached:
            latest = lead.insights[0]
            upgrade = model_ready and latest.engine == "rules"
            if not upgrade:
                skipped += 1
                continue
            insight = analyze_lead(db, lead, force=True)
        else:
            insight = analyze_lead(db, lead, force=False)
        analyzed += 1
        _pace_batch_groq(insight, remaining=len(leads) - index - 1)
    return {"analyzed": analyzed, "skipped": skipped, "engine": ai_status()["engine"]}


def _pace_batch_groq(insight: AiInsight, remaining: int) -> None:
    """Keep batch Groq calls under the free-tier 8k tokens/min ceiling."""
    if remaining > 0 and insight.engine == "groq" and settings.groq_batch_spacing_seconds > 0:
        time.sleep(settings.groq_batch_spacing_seconds)


# --------------------------------------------------------------------------- #
# Background batch analysis (long runs under a rate limit, with live progress)
# --------------------------------------------------------------------------- #
_batch_lock = threading.Lock()
_batch_state: dict[str, Any] = {
    "running": False,
    "total": 0,
    "done": 0,
    "groq": 0,
    "rules": 0,
    "skipped": 0,
    "started_at": None,
    "finished_at": None,
    "error": None,
}


def batch_progress() -> dict[str, Any]:
    with _batch_lock:
        return dict(_batch_state)


def start_batch_analysis(limit: int) -> dict[str, Any]:
    """Start a background batch run (one at a time). Returns the progress snapshot."""
    from app.db import SessionLocal

    with _batch_lock:
        if _batch_state["running"]:
            return {**_batch_state, "already_running": True}
        _batch_state.update(
            running=True,
            total=0,
            done=0,
            groq=0,
            rules=0,
            skipped=0,
            started_at=datetime.utcnow().isoformat(),
            finished_at=None,
            error=None,
        )
    thread = threading.Thread(target=_batch_worker, args=(limit, SessionLocal), daemon=True)
    thread.start()
    return batch_progress()


def _batch_worker(limit: int, session_factory: Any) -> None:
    db = session_factory()
    try:
        model_ready = ai_status()["available"]
        leads = db.query(Lead).filter(Lead.do_not_contact.is_(False)).order_by(Lead.updated_at.desc()).limit(limit).all()
        with _batch_lock:
            _batch_state["total"] = len(leads)
        for index, lead in enumerate(leads):
            context = build_context(lead)
            digest = context_hash(context)
            cached = lead.analysis_input_hash == digest and bool(lead.insights)
            if cached:
                latest = lead.insights[0]
                upgrade = model_ready and latest.engine == "rules"
                if not upgrade:
                    with _batch_lock:
                        _batch_state["skipped"] += 1
                        _batch_state["done"] += 1
                    continue
                insight = analyze_lead(db, lead, force=True)
            else:
                insight = analyze_lead(db, lead, force=False)
            with _batch_lock:
                _batch_state["done"] += 1
                if insight.engine == "groq":
                    _batch_state["groq"] += 1
                else:
                    _batch_state["rules"] += 1
            _pace_batch_groq(insight, remaining=len(leads) - index - 1)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background analysis batch failed")
        with _batch_lock:
            _batch_state["error"] = f"{exc.__class__.__name__}: {exc}"
    finally:
        try:
            db.close()
        finally:
            with _batch_lock:
                _batch_state["running"] = False
                _batch_state["finished_at"] = datetime.utcnow().isoformat()


def ensure_scheduled_followups(db: Session, limit: int = 200) -> int:
    """Create rule-driven follow-ups for leads that have none, when appropriate."""
    rules = followup_rules(db)
    stages = rules.get("unscheduled_stage_keys") or []
    if not stages:
        return 0
    from app.services.leads import upsert_followup

    leads = (
        db.query(Lead)
        .filter(Lead.pipeline_stage.in_(stages), Lead.next_followup_at.is_(None), Lead.do_not_contact.is_(False))
        .limit(limit)
        .all()
    )
    created = 0
    for lead in leads:
        timing = datetime.utcnow() + timedelta(days=2 if lead.pipeline_stage in {"contacted", "qualified"} else 1)
        upsert_followup(
            db,
            lead,
            due_at=timing,
            reason=f"Auto-scheduled for stage '{STAGES.get(lead.pipeline_stage, {}).get('label')}'",
            action=_default_next_action(lead),
            priority=int(rules.get("default_priority", 3)),
            source="rule",
        )
        created += 1
    if created:
        db.commit()
    return created
