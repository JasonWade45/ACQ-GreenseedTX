"""Human-approved, redacted Groq requests. Never called by sync/scheduler."""

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import threading
from uuid import uuid4
from sqlalchemy import select, func
from ..db import utcnow
from ..models import Lead, CloudRequest, Draft, Activity, AuditLog
from .ai import FACT_KEYS, context_for, context_hash, analyze_lead
from .groq_client import GroqClient, GroqError, CloudDraft

EXECUTION_LOCK = threading.Lock()
EMAIL = re.compile(r"[^\s@<>]+@[^\s@<>]+\.[A-Za-z]{2,}")
PHONE = re.compile(
    r"(?<!\w)(?:\+?1[ .()-]*)?(?:\(?\d{3}\)?[ .-]*)\d{3}[ .-]*\d{4}(?:\s*(?:ext\.?|x)\s*\d+)?(?!\w)", re.I
)
TOKEN = re.compile(r"(?<!\w)(?:gsk_[A-Za-z0-9_-]{12,}|[A-Za-z0-9_-]{32,})(?!\w)")
ADDRESS = re.compile(
    r"\b\d{1,6}\s+(?:[A-Za-z0-9.'-]+\s+){1,6}(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Boulevard|Blvd|Way|Place|Pl)\b(?:\s*(?:#|Apt\.?|Unit)\s*\w+)?",
    re.I,
)


class ReviewError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).encode()).hexdigest()


def _privacy_terms(lead, extra):
    result = []
    for value in (
        lead.full_name,
        lead.first_name,
        lead.last_name,
        lead.primary_phone,
        lead.email,
        lead.assigned_manager,
    ):
        if value:
            result.append((str(value), "[PERSONAL DETAIL]"))
    for word in (lead.full_name or "").split():
        if len(word) >= 3:
            result.append((word, "[SELLER]"))
    for prop in lead.properties:
        for value in (prop.street_address, prop.city, prop.zip_code):
            if value:
                result.append((str(value), "[PROPERTY DETAIL]"))
    result.extend((value, "[ADDITIONAL REDACTION]") for value in extra if len(value.strip()) >= 2)
    return sorted(set(result), key=lambda item: -len(item[0]))


def redacted_context(db, lead, extra=()):
    records = []
    source_map = {}
    replacements = 0
    characters = 0
    truncated = False
    for record in context_for(db, lead):
        if record["ref"].rsplit(":", 1)[-1] in {"full_name", "primary_phone", "street_address"}:
            continue
        text = str(record["text"])
        for value, label in _privacy_terms(lead, extra):
            text, count = re.subn(r"(?<!\w)" + re.escape(value) + r"(?!\w)", lambda _: label, text, flags=re.I)
            replacements += count
        for pattern, label in (
            (EMAIL, "[EMAIL REDACTED]"),
            (PHONE, "[PHONE REDACTED]"),
            (ADDRESS, "[ADDRESS REDACTED]"),
            (TOKEN, "[CREDENTIAL / IDENTIFIER REDACTED]"),
        ):
            text, count = pattern.subn(label, text)
            replacements += count
        if len(text) > 3000:
            text = text[:3000] + " [SOURCE EXCERPT TRUNCATED]"
            truncated = True
        if characters + len(text) > 24000 or len(records) >= 100:
            truncated = True
            break
        if not text.strip():
            continue
        reference = "E" + str(len(records) + 1).zfill(3)
        item = {
            "ref": reference,
            "text": text,
            "label": record["ref"].split(":")[0] + " · " + record["ref"].rsplit(":", 1)[-1]
            if not record["ref"].split(":")[-1].isdigit()
            else record["ref"].split(":")[0] + " record",
        }
        if record.get("outcome"):
            item["outcome"] = record["outcome"]
        if record.get("timestamp"):
            item["timestamp"] = record["timestamp"]
        records.append(item)
        source_map[reference] = record["ref"]
        characters += len(text)
    return records, source_map, replacements, truncated


def ensure_draft_allowed(lead):
    if not lead.full_name:
        raise ValueError("Owner identity is unknown; identify and review the seller before drafting")
    if lead.do_not_contact:
        raise ReviewError("Do Not Contact: marketing drafts are blocked")
    if lead.restriction_status != "reviewed_clear":
        raise ReviewError("Review contact restrictions using actual evidence before preparing a draft")
    if lead.contact_outcome != "Callback Requested" and not lead.source_data.get("normalized", {}).get(
        "seller_motivation"
    ):
        raise ReviewError(
            "Insufficient verified relationship context. An explicit callback or source seller motivation is required; no generic draft will be generated."
        )


def usage_today(db):
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.count()).select_from(CloudRequest).where(CloudRequest.started_at >= start)) or 0


def cloud_status(db, settings):
    return {
        "provider": "groq",
        "enabled": settings.groq_enabled,
        "key_configured": bool(settings.groq_api_key),
        "model": settings.groq_model,
        "daily_limit": settings.groq_daily_request_limit,
        "used_today": usage_today(db),
        "max_output_tokens": settings.groq_max_output_tokens,
        "consent_mode": "redacted_review_each_request",
        "external_data_flow": "Only the selected redacted records, after explicit per-request approval. Redaction is not a guarantee; review the preview.",
        "automatic_processing": False,
        "automatic_communication": False,
        "crm_writes": False,
    }


def create_preview(db, lead, purpose, settings, extra=()):
    if not settings.groq_enabled or not settings.groq_api_key:
        raise ReviewError("Enable Groq and save a replacement key in Settings first")
    if purpose == "draft":
        ensure_draft_allowed(lead)
    records, mapping, count, truncated = redacted_context(db, lead, extra)
    if not records:
        raise ReviewError("No useful source context is available after redaction; add verified information first")
    flags = {
        "restriction": lead.restriction_status,
        "callback_requested": lead.contact_outcome == "Callback Requested",
        "has_explicit_motivation": bool(lead.source_data.get("normalized", {}).get("seller_motivation")),
        "has_name_placeholder": bool(lead.first_name or lead.full_name),
        "has_address_placeholder": len(lead.properties) == 1 and bool(lead.properties[0].street_address),
    }
    request = CloudRequest(
        id=str(uuid4()),
        lead_id=lead.id,
        purpose=purpose,
        provider="groq",
        model_id=settings.groq_model,
        state="pending_review",
        context_hash=context_hash(lead, context_for(db, lead)),
        payload_hash=_hash(
            {"records": records, "constraints": flags, "purpose": purpose, "model": settings.groq_model}
        ),
        records=records,
        source_map=mapping,
        result={
            "constraints": flags,
            "_credential_fingerprint": _hash(settings.groq_api_key),
            "redactions": count,
            "truncated": truncated,
        },
        expires_at=utcnow() + timedelta(minutes=15),
    )
    db.add(request)
    db.add(
        AuditLog(
            lead_id=lead.id,
            action="cloud_context_previewed",
            details={"request_id": request.id, "purpose": purpose, "records": len(records), "transmitted": False},
        )
    )
    db.commit()
    return request


def request_dict(request, lead=None, current_hash=None):
    value = {
        key: getattr(request, key)
        for key in (
            "id",
            "lead_id",
            "purpose",
            "provider",
            "model_id",
            "state",
            "payload_hash",
            "records",
            "result",
            "usage",
            "error",
            "created_at",
            "expires_at",
            "started_at",
            "completed_at",
        )
    }
    value["result"] = {
        key: item for key, item in request.result.items() if not key.startswith("_") and key != "approved_digest"
    }
    value["source_context_stale"] = current_hash is not None and current_hash != request.context_hash
    if lead is not None and request.purpose == "draft" and lead.restriction_status != "reviewed_clear":
        value["result"] = {key: item for key, item in value["result"].items() if key not in {"body", "draft_id"}}
        value["result"]["draft_blocked_by_current_restriction"] = True
    return value


def _grounded(item, records):
    if (
        not item.evidence
        or any(ref not in records for ref in item.evidence)
        or not item.quote
        or not any(item.quote in records[ref]["text"] for ref in item.evidence)
    ):
        raise GroqError(
            "AI output did not match the reviewed evidence. No source fields were changed.", "ungrounded_output"
        )


def _numbers(text):
    values = set()
    for item in re.findall(r"\d[\d,.]*", str(text)):
        try:
            values.add(format(Decimal(item.replace(",", "").rstrip(".")).normalize(), "f"))
        except InvalidOperation:
            pass
    return values


def validate_grounding(output, records, purpose, flags):
    by_ref = {r["ref"]: r for r in records}
    all_text = "\n".join(r["text"] for r in records)
    known_numbers = _numbers(all_text)
    if purpose == "draft":
        _grounded(output, by_ref)
        body = output.body
        required = "Hi {{seller_first_name}}," if flags["has_name_placeholder"] else "Hello,"
        if not body.startswith(required) or re.search(r"\d|[$€£]", body):
            raise GroqError(
                "Draft introduced an unsupported greeting, amount, or date. No draft was saved.", "unsafe_draft"
            )
        placeholders = set(re.findall(r"\{\{([^{}]+)\}\}", body))
        allowed = {"seller_first_name"} if flags["has_name_placeholder"] else set()
        if flags["has_address_placeholder"]:
            allowed.add("property_address")
        if placeholders - allowed or EMAIL.search(body) or PHONE.search(body) or TOKEN.search(body):
            raise GroqError("Draft introduced unsupported personal details. No draft was saved.", "unsafe_draft")
        forbidden = r"as we discussed|we spoke|we talked|our conversation|we agreed|i can pay|we will buy|we.ll close|guarantee|our offer|my offer|i promise|we promise|i.ll buy|we.ll buy"
        if re.search(forbidden, body, re.I) or ("callback" in body.lower() and not flags["callback_requested"]):
            raise GroqError(
                "Draft introduced an unsupported conversation or commitment. No draft was saved.", "unsafe_draft"
            )
        return
    if set(output.facts) != set(FACT_KEYS):
        raise GroqError("AI returned unexpected fact fields.", "invalid_output")
    _grounded(output.summary, by_ref)
    for fact in output.facts.values():
        if fact.category == "unknown":
            if fact.value is not None or fact.evidence:
                raise GroqError("Unknown AI facts must remain empty.", "invalid_output")
        else:
            if fact.value is None:
                raise GroqError("Known AI facts require a grounded value.", "invalid_output")
            _grounded(fact, by_ref)
            if _numbers(fact.value) - known_numbers:
                raise GroqError("AI introduced a number not present in the reviewed evidence.", "ungrounded_output")
    for item in [output.summary, *output.organized_notes, *output.conflicts]:
        _grounded(item, by_ref)
        if (
            _numbers(item.text) - known_numbers
            or EMAIL.search(item.text)
            or PHONE.search(item.text)
            or TOKEN.search(item.text)
        ):
            raise GroqError("AI added unsupported numeric or personal information.", "ungrounded_output")


def _artifact(db, lead, request, output, settings, records):
    if isinstance(output, CloudDraft):
        body = output.body.replace("{{seller_first_name}}", lead.first_name or lead.full_name.split()[0])
        if "{{property_address}}" in body:
            body = body.replace("{{property_address}}", lead.properties[0].street_address)
        draft = Draft(lead_id=lead.id, body=body, context=context_for(db, lead), model_id="groq:" + request.model_id)
        db.add(draft)
        db.flush()
        return {
            "draft_id": draft.id,
            "body": body,
            "review_note": output.review_note,
            "evidence": output.evidence,
            "quote": output.quote,
        }
    result = output.model_dump()
    if request.purpose == "notes":
        return result
    # Existing source facts remain authoritative; a differing model value is a visible conflict.
    base, _, _ = analyze_lead(db, lead, settings.model_copy(update={"ollama_enabled": False}), force=True)
    facts = deepcopy(base.facts)
    for key, value in output.facts.items():
        if value.category == "unknown":
            continue
        candidate = value.model_dump()
        candidate["evidence"] = ["review:" + request.id + ":" + ref for ref in value.evidence]
        if facts[key]["value"] is not None and str(facts[key]["value"]) != str(value.value):
            candidate = {
                "value": str(facts[key]["value"]) + " | Groq interpretation: " + str(value.value),
                "category": "conflict",
                "evidence": facts[key]["evidence"] + candidate["evidence"],
                "quote": value.quote,
            }
        facts[key] = candidate
    base.summary = output.summary.text
    base.facts = facts
    base.model_id = "groq:" + request.model_id
    base.conflicts = list(base.conflicts) + [item.text for item in output.conflicts]
    base.missing_information = list(dict.fromkeys([*base.missing_information, *output.missing_information]))
    base.evidence = list(base.evidence) + [
        {**r, "ref": "review:" + request.id + ":" + r["ref"], "original_ref": request.source_map[r["ref"]]}
        for r in records
    ]
    base.confidence = "AI proposal · reviewed redacted context · human verification required"
    db.flush()
    result["insight_id"] = base.id
    return result


def execute_request(
    db, request_id, settings, confirmation, payload_hash, selected_refs, force_refresh=False, client_factory=None
):
    request = db.get(CloudRequest, request_id)
    if not request:
        raise ReviewError("Cloud review not found", 404)
    if confirmation != "SEND REVIEWED CONTEXT":
        raise ReviewError("Explicitly approve the reviewed redacted context before sending")
    current_lead = db.get(Lead, request.lead_id)
    if request.purpose == "draft":
        ensure_draft_allowed(current_lead)
    if request.state == "completed":
        return request
    if request.state != "pending_review":
        raise ReviewError("This review cannot be sent again; inspect its result or prepare a new preview", 409)
    if payload_hash != request.payload_hash:
        raise ReviewError("Review digest changed; prepare a new preview", 409)
    if request.expires_at < utcnow():
        request.state = "expired"
        db.commit()
        raise ReviewError("This review expired; preview current data again", 409)
    if (
        not settings.groq_enabled
        or not settings.groq_api_key
        or settings.groq_model != request.model_id
        or request.result.get("_credential_fingerprint") != _hash(settings.groq_api_key)
    ):
        raise ReviewError("Groq configuration changed or is disabled; preview again", 409)
    lead = db.get(Lead, request.lead_id)
    if request.purpose == "draft":
        ensure_draft_allowed(lead)
    if context_hash(lead, context_for(db, lead)) != request.context_hash:
        raise ReviewError("Source context changed after this preview. Nothing was sent; review again.", 409)
    known = {r["ref"] for r in request.records}
    if not selected_refs or set(selected_refs) - known:
        raise ReviewError("Select valid reviewed evidence records")
    records = [r for r in request.records if r["ref"] in set(selected_refs)]
    selected_hash = _hash(
        {
            "records": records,
            "constraints": request.result["constraints"],
            "purpose": request.purpose,
            "model": request.model_id,
            "source": request.context_hash,
        }
    )
    if not EXECUTION_LOCK.acquire(blocking=False):
        raise ReviewError(
            "Another cloud request is running. Wait for it to finish; no duplicate request was sent.", 409
        )
    client = None
    try:
        # Re-read after claiming the single-worker lock: another approval may
        # have completed while this request was between its first read/claim.
        db.rollback()
        request = db.get(CloudRequest, request_id)
        lead = db.get(Lead, request.lead_id)
        if request.state == "completed":
            return request
        if request.state != "pending_review":
            raise ReviewError("This review is already being processed; no duplicate request was sent", 409)
        if request.expires_at < utcnow():
            request.state = "expired"
            db.commit()
            raise ReviewError("This review expired; preview current data again", 409)
        if request.purpose == "draft":
            ensure_draft_allowed(lead)
        if context_hash(lead, context_for(db, lead)) != request.context_hash:
            raise ReviewError("Source context changed before processing. Nothing was sent; review again.", 409)
        if not force_refresh:
            candidates = db.scalars(
                select(CloudRequest)
                .where(
                    CloudRequest.state == "completed",
                    CloudRequest.lead_id == lead.id,
                    CloudRequest.purpose == request.purpose,
                    CloudRequest.model_id == request.model_id,
                )
                .order_by(CloudRequest.created_at.desc())
                .limit(20)
            ).all()
            cached = next((item for item in candidates if item.result.get("approved_digest") == selected_hash), None)
            if cached:
                request.result = {**deepcopy(cached.result), "cached_from": cached.id}
                request.records = records
                request.state = "completed"
                request.completed_at = utcnow()
                db.commit()
                return request
        if usage_today(db) >= settings.groq_daily_request_limit:
            raise ReviewError("Your configured UTC daily Groq request cap has been reached. No request was sent.", 429)
        request.records = records
        request.state = "running"
        request.started_at = utcnow()
        request.result = {**request.result, "approved_digest": selected_hash}
        db.add(
            AuditLog(
                lead_id=lead.id,
                action="cloud_context_approved",
                details={
                    "request_id": request.id,
                    "purpose": request.purpose,
                    "record_count": len(records),
                    "provider": "groq",
                },
            )
        )
        db.commit()
        client = (client_factory or GroqClient)(settings)
        output, usage = client.complete(request.purpose, records, request.result["constraints"])
        validate_grounding(output, records, request.purpose, request.result["constraints"])
        # Edits in another tab while the provider is working must not silently apply stale output.
        db.expire_all()
        request = db.get(CloudRequest, request_id)
        lead = db.get(Lead, request.lead_id)
        request.usage = usage
        request.completed_at = utcnow()
        if context_hash(lead, context_for(db, lead)) != request.context_hash or (
            request.purpose == "draft" and lead.restriction_status != "reviewed_clear"
        ):
            request.state = "completed_stale"
            request.error = "Source context/restrictions changed during analysis. Output was not applied."
            db.commit()
            return request
        artifact = _artifact(db, lead, request, output, settings, records)
        request = db.get(CloudRequest, request_id)
        request.result = {**request.result, **artifact}
        request.state = "completed"
        request.completed_at = utcnow()
        db.add(
            AuditLog(
                lead_id=lead.id,
                action="cloud_result_prepared",
                details={
                    "request_id": request.id,
                    "purpose": request.purpose,
                    "crm_writes": False,
                    "never_sent_to_seller": True,
                },
            )
        )
        db.commit()
        return request
    except GroqError as error:
        db.rollback()
        request = db.get(CloudRequest, request_id)
        request.state = "outcome_unknown" if error.uncertain else "failed"
        request.error = str(error)
        request.completed_at = utcnow()
        db.commit()
        return request
    except ReviewError:
        raise
    except Exception:
        db.rollback()
        request = db.get(CloudRequest, request_id)
        if request.started_at:
            request.state = "failed"
            request.error = "Local result processing failed. No automatic retry was made."
            request.completed_at = utcnow()
            db.commit()
            return request
        raise ReviewError("The request could not be prepared; nothing was sent", 500) from None
    finally:
        if client:
            client.close()
        EXECUTION_LOCK.release()


def save_organized_notes(db, request_id, confirm):
    request = db.get(CloudRequest, request_id)
    if not request or request.state != "completed" or request.purpose != "notes":
        raise ReviewError("A completed organized-notes proposal is required")
    if not confirm:
        raise ReviewError("Confirm that you reviewed these AI-proposed notes")
    if request.result.get("saved_note_id"):
        return db.get(Activity, request.result["saved_note_id"])
    lead = db.get(Lead, request.lead_id)
    if context_hash(lead, context_for(db, lead)) != request.context_hash:
        raise ReviewError("Source context changed. Review a new notes proposal first.", 409)
    entries = request.result.get("organized_notes", [])
    if not entries:
        raise ReviewError("No grounded organized notes were returned")
    text = "Human-reviewed AI-assisted organization (original source notes preserved):\n\n" + "\n\n".join(
        item["text"] + "\nEvidence: " + ", ".join(item["evidence"]) for item in entries
    )
    note = Activity(
        lead_id=lead.id,
        activity_type="note",
        summary=text,
        occurred_at=utcnow(),
        source="local",
        source_metadata={
            "cloud_request_id": request.id,
            "human_reviewed": True,
            "original_notes_preserved": True,
            "not_sent_by_app": True,
        },
    )
    db.add(note)
    db.flush()
    request.result = {**request.result, "saved_note_id": note.id}
    db.add(
        AuditLog(
            lead_id=lead.id,
            action="organized_notes_saved_locally",
            details={"request_id": request.id, "note_id": note.id, "crm_write": False},
        )
    )
    db.commit()
    return note
