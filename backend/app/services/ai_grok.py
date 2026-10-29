"""The xAI Grok client: one thin adapter, no key in a log, no PII in a prompt by default.

The vendor now documents two text surfaces with the same structured-output guarantee:

* ``POST /v1/responses`` -- the primary interface. A schema is sent as
  ``text.format = {"type": "json_schema", ...}`` and the docs state that when supported
  schema features are used the response is *guaranteed* to match the schema.
* ``POST /v1/chat/completions`` -- the stateless predecessor, same guarantee via
  ``response_format``.

xAI's docs recommend the Responses API for new integrations, so it is the default here.
Switching is one settings value, and the only code that differs is the pair of
functions in ``ADAPTERS`` below.

This module never decides what a message should say and cannot send anything: it returns
text, and the caller stores it as a draft, a suggestion or advice.
"""

import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import GrokRun

BASE_URL = "https://api.x.ai/v1"
APIS = ("responses", "chat_completions")

# Documented list prices, US dollars per 1,000,000 tokens (input, output).
PRICES = {
    "grok-4.7": (2.00, 6.00),
    "grok-4.6": (2.00, 6.00),
    "grok-4.5": (2.00, 6.00),
    "grok-4.3": (1.25, 2.50),
    "grok-build-0.1": (1.00, 2.00),
}
DEFAULT_PRICE = (2.00, 6.00)

# The fields a lead may contribute to a prompt. Only these are ever assembled, and only
# the enabled ones are sent; the Settings screen shows this list verbatim.
AI_FIELDS = {
    "property_address": "Property address (street, city, state, ZIP)",
    "property_facts": "Bedrooms, bathrooms, square feet, year built",
    "lead_type": "Lead type (for example probate or tax deed)",
    "priority": "Priority tier, score and heat",
    "equity": "Estimated equity percentage",
    "flags": "Data Syndicate flags",
    "contact_history": "Whether contact was attempted, and the last outcome",
    "conversation": "Recent conversation text from synced activity",
}
DEFAULT_AI_FIELDS = ("property_address", "property_facts", "lead_type", "priority", "equity", "flags", "contact_history")

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
TOKEN = re.compile(r"\b(sk|xai|gsk)-[A-Za-z0-9_\-]{8,}\b")


class GrokError(Exception):
    """A call that did not produce usable text. Carries a code the UI can translate."""

    def __init__(self, message, code="grok_failed", retryable=False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class GrokResult(BaseModel):
    text: str
    data: Optional[dict] = None
    api: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    request_preview: dict = Field(default_factory=dict)


def strip_pii(text):
    """Replace anything that identifies a person or carries a credential."""
    if text is None:
        return ""
    cleaned = TOKEN.sub("[CREDENTIAL REDACTED]", str(text))
    cleaned = EMAIL.sub("[EMAIL REDACTED]", cleaned)
    cleaned = PHONE.sub("[PHONE REDACTED]", cleaned)
    return cleaned


def sanitize(value):
    """Strip PII from every string in a nested structure, leaving structure intact."""
    if isinstance(value, str):
        return strip_pii(value)
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    return value


def model_for(purpose, settings):
    """The model is a setting, never a constant: follow-ups, checklists and advice differ."""
    return {
        "followup_draft": settings.grok_followup_model,
        "checklist_suggest": settings.grok_checklist_model,
        "advisor": settings.grok_advisor_model,
    }.get(purpose, settings.grok_checklist_model)


def pricing(model):
    return PRICES.get(model, DEFAULT_PRICE)


def cost_usd(input_tokens, output_tokens, model):
    price_in, price_out = pricing(model)
    return (input_tokens / 1_000_000) * price_in + (output_tokens / 1_000_000) * price_out


def monthly_estimate(settings, db: Optional[Session] = None):
    """What the AI is expected to cost per month, from observed usage or from a plan.

    Observed usage wins when there is any: the last 30 days of runs give the average
    tokens per call and the number of calls per day, and those averages are priced with
    the documented list price of the model actually used.
    """
    if db is not None:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        rows = db.execute(
            select(GrokRun.model_id, func.count(GrokRun.id), func.sum(GrokRun.input_tokens), func.sum(GrokRun.output_tokens))
            .where(GrokRun.created_at >= since, GrokRun.state == "succeeded")
            .group_by(GrokRun.model_id)
        ).all()
        if rows:
            monthly = 0.0
            for model_id, calls, tokens_in, tokens_out in rows:
                monthly += cost_usd(tokens_in or 0, tokens_out or 0, model_id)
            days = 30.0
            return {
                "basis": "observed_last_30_days",
                "monthly_usd": round(monthly, 2),
                "monthly_usd_at_planned_volume": round(monthly / days * settings.grok_expected_daily_calls * 30, 2),
                "calls": sum(row[1] for row in rows),
                "models": sorted({row[0] for row in rows}),
            }
    per_call = cost_usd(settings.grok_expected_tokens_in, settings.grok_expected_tokens_out, settings.grok_advisor_model)
    monthly = per_call * settings.grok_expected_daily_calls * 30
    return {
        "basis": "planned_volume",
        "monthly_usd": round(monthly, 2),
        "per_call_usd": round(per_call, 4),
        "calls_per_day": settings.grok_expected_daily_calls,
        "model": settings.grok_advisor_model,
        "note": "Estimate only. xAI bills the tokens actually used, and long-context calls cost more.",
    }


def usage_today(db: Session, now: Optional[datetime] = None):
    """How many AI calls have been made today, UTC, for the daily cap."""
    moment = (now or utcnow()).astimezone(timezone.utc)
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.count(GrokRun.id)).where(GrokRun.created_at >= start)) or 0


def cap_status(db: Session, settings):
    used = usage_today(db)
    limit = settings.grok_daily_request_limit
    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "exhausted": used >= limit,
        "enabled": bool(settings.grok_enabled),
        "key_configured": bool(settings.grok_api_key),
        "api": settings.grok_api,
        "models": {
            "followup_draft": settings.grok_followup_model,
            "checklist_suggest": settings.grok_checklist_model,
            "advisor": settings.grok_advisor_model,
        },
    }


def _responses_body(model, system, prompt, schema, name, max_tokens, temperature):
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_output_tokens": max_tokens,
        "temperature": temperature,
        "store": False,
    }
    if schema is not None:
        body["text"] = {"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}}
    return body


def _responses_parse(data):
    usage = data.get("usage") or {}
    text_parts = []
    for item in data.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                text_parts.append(content["text"])
    if not text_parts and isinstance(data.get("output_text"), str):
        text_parts.append(data["output_text"])
    return {
        "text": "".join(text_parts).strip(),
        "input_tokens": int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
    }


def _chat_body(model, system, prompt, schema, name, max_tokens, temperature):
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if schema is not None:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}}
    return body


def _chat_parse(data):
    usage = data.get("usage") or {}
    choices = data.get("choices") or []
    text = ""
    if choices:
        text = ((choices[0].get("message") or {}).get("content") or "").strip()
    return {
        "text": text,
        "input_tokens": int(usage.get("prompt_tokens") or 0),
        "output_tokens": int(usage.get("completion_tokens") or 0),
    }


# The whole difference between the two surfaces lives in this table.
ADAPTERS = {
    "responses": {"path": "/responses", "build": _responses_body, "parse": _responses_parse},
    "chat_completions": {"path": "/chat/completions", "build": _chat_body, "parse": _chat_parse},
}


class GrokClient:
    """A bounded xAI caller. Validate what it returns; it is a model, not an authority."""

    def __init__(self, settings, transport=None, sleeper=time.sleep, clock=time.monotonic):
        if not settings.grok_enabled:
            raise GrokError("The Grok integration is switched off in Settings", code="not_configured")
        if not settings.grok_api_key:
            raise GrokError("GROK_API_KEY is missing; configure it in the backend environment", code="not_configured")
        if settings.grok_api not in ADAPTERS:
            raise GrokError(f"Unknown Grok API surface {settings.grok_api!r}", code="not_configured")
        self.settings = settings
        self.sleeper = sleeper
        self.clock = clock
        self.http = httpx.Client(
            base_url=BASE_URL + "/",
            headers={
                "Authorization": f"Bearer {settings.grok_api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(settings.grok_timeout_seconds, connect=10),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def close(self):
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def preview(self, *, purpose, prompt, system="", schema=None, name="result", model=None):
        """Exactly what the request would contain, PII-free, for the "what was sent" panel."""
        model = model or model_for(purpose, self.settings)
        adapter = ADAPTERS[self.settings.grok_api]
        body = adapter["build"](model, sanitize(system), sanitize(prompt), schema, name, self.settings.grok_max_output_tokens, 0.2)
        return {
            "api": self.settings.grok_api,
            "path": adapter["path"],
            "model": model,
            "body": sanitize(body),
            "pii_stripped": True,
        }

    def complete(self, *, purpose, prompt, system="", schema=None, name="result", model=None):
        """One request, retried on transient failures only. Raises ``GrokError`` otherwise."""
        model = model or model_for(purpose, self.settings)
        adapter = ADAPTERS[self.settings.grok_api]
        body = adapter["build"](
            model,
            sanitize(system),
            sanitize(prompt),
            schema,
            name,
            self.settings.grok_max_output_tokens,
            0.2,
        )
        preview = {"api": self.settings.grok_api, "path": adapter["path"], "model": model, "body": sanitize(body)}
        started = self.clock()
        last_error = None
        for attempt in range(3):
            try:
                response = self.http.post(adapter["path"].lstrip("/"), json=body)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = GrokError("The AI service did not answer in time", code="timeout", retryable=True)
                if attempt == 2:
                    raise last_error from exc
                self.sleeper(2**attempt)
                continue
            if response.status_code == 429:
                last_error = GrokError("The AI service is rate limiting", code="rate_limited", retryable=True)
                if attempt == 2:
                    raise last_error
                self.sleeper(max(1, self._retry_after(response, attempt)))
                continue
            if 500 <= response.status_code < 600:
                last_error = GrokError("The AI service returned an error", code="server_error", retryable=True)
                if attempt == 2:
                    raise last_error
                self.sleeper(2**attempt)
                continue
            if response.status_code in {401, 403}:
                raise GrokError("The AI service rejected the key", code="rejected_credentials")
            if response.status_code == 400:
                raise GrokError(f"The AI service rejected the request: {self._reason(response)}", code="rejected_request")
            if not 200 <= response.status_code < 300:
                raise GrokError(f"The AI service returned HTTP {response.status_code}", code="http_error")
            try:
                data = response.json()
            except ValueError as exc:
                raise GrokError("The AI service returned malformed JSON", code="bad_response") from exc
            parsed = adapter["parse"](data)
            text = parsed["text"]
            if not text:
                raise GrokError("The AI service returned an empty answer", code="empty_response")
            result = {
                "text": text,
                "data": None,
                "api": self.settings.grok_api,
                "model": model,
                "input_tokens": parsed["input_tokens"],
                "output_tokens": parsed["output_tokens"],
                "duration_ms": int((self.clock() - started) * 1000),
                "request_preview": preview,
            }
            if schema is not None:
                try:
                    result["data"] = json.loads(text)
                except ValueError as exc:
                    raise GrokError(
                        "The AI service returned text that is not valid JSON; nothing was saved",
                        code="invalid_json",
                    ) from exc
            return GrokResult(**result)
        raise last_error or GrokError("The AI service call failed", code="grok_failed")

    def _retry_after(self, response, attempt):
        try:
            return float(response.headers.get("Retry-After", ""))
        except ValueError:
            return float(2**attempt)

    def _reason(self, response, limit=300):
        try:
            data = response.json()
        except ValueError:
            return f"HTTP {response.status_code}"
        if isinstance(data, dict):
            for key in ("error", "message", "detail"):
                value = data.get(key)
                if isinstance(value, dict):
                    value = value.get("message")
                if isinstance(value, str) and value.strip():
                    return strip_pii(value)[:limit]
        return f"HTTP {response.status_code}"


def record_run(
    db: Session,
    *,
    run_id,
    lead_id,
    purpose,
    input_hash,
    result=None,
    error=None,
    model=None,
    api="responses",
    state=None,
    preview=None,
):
    """Store one call: the model, the input hash and the PII-free preview, never the key."""
    row = GrokRun(
        id=run_id,
        lead_id=lead_id,
        purpose=purpose,
        api=(result.api if result else api),
        model_id=(result.model if result else model or ""),
        state=state or ("succeeded" if result else "failed"),
        input_hash=input_hash,
        request_preview=(result.request_preview if result else sanitize(preview or {})),
        output={"text": result.text, "data": result.data} if result else {},
        usage={"input_tokens": result.input_tokens, "output_tokens": result.output_tokens} if result else {},
        input_tokens=(result.input_tokens if result else 0),
        output_tokens=(result.output_tokens if result else 0),
        error=(strip_pii(str(error))[:2000] if error else None),
        duration_ms=(result.duration_ms if result else 0),
    )
    db.add(row)
    return row
