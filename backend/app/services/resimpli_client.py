"""REsimpli Open API v6 client.

Contract sources (fetched live during build, saved in docs/):
  * https://developer.resimpli.com            (interactive documentation)
  * https://developer.resimpli.com/openapi-endpoints.json
  * https://help.resimpli.com/en/articles/16915306-open-api-and-integrations

Documented facts this client implements:
  * Base URL          : https://api.resimpli.com/api/v6/openapi
  * Authentication    : header `Authorization: <API_KEY>` (raw key, no Bearer)
  * All endpoints are POST and take a JSON body
  * Pagination        : { page, limit } with limit 1..100
  * Rate limit        : HTTP 429 when exceeded (portal documents 100 req/min,
                        the help centre states 500 req/min as of 2026-10-01)
  * Readable modules  : leads, call logs, appointments, agents, buyers, vendors,
                        files, folders, reference data
  * Writes at launch  : create lead (/lead/add) and delete lead (/lead/delete)
                        — updating existing records is NOT available at launch

Response body shapes are not published in the developer portal, so every
extractor here is deliberately tolerant and the raw payload is stored locally
for inspection. Nothing is invented: fields that cannot be located stay None.
"""
from __future__ import annotations

import html
import logging
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

logger = logging.getLogger("acquisitions.resimpli")


class ResimpliError(Exception):
    """Base class for REsimpli integration failures."""


class ResimpliAuthError(ResimpliError):
    pass


class ResimpliRateLimitError(ResimpliError):
    pass


class ResimpliApiError(ResimpliError):
    def __init__(self, message: str, status_code: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class ResimpliNetworkError(ResimpliError):
    pass


# --------------------------------------------------------------------------- #
# Tolerant payload helpers
# --------------------------------------------------------------------------- #
LIST_KEYS = ("leads", "list", "items", "data", "result", "records", "rows")
TOTAL_KEYS = ("totalRecords", "totalCount", "total", "count", "totalCountRecords")
PAGE_KEYS = ("totalPages", "pageCount", "pages")


def extract_payload(response_json: Any) -> Any:
    """Unwrap common envelope shapes without inventing data."""
    if not isinstance(response_json, dict):
        return response_json
    for key in ("data", "result", "payload"):
        inner = response_json.get(key)
        if inner is not None:
            return inner
    return response_json


def extract_list(response_json: Any, preferred_keys: tuple[str, ...] = LIST_KEYS) -> tuple[list, dict[str, Any]]:
    payload = extract_payload(response_json)
    meta: dict[str, Any] = {}
    if isinstance(payload, list):
        return payload, meta
    if isinstance(payload, dict):
        for key in preferred_keys:
            value = payload.get(key)
            if isinstance(value, list):
                for k in TOTAL_KEYS:
                    if k in payload:
                        meta["total"] = payload[k]
                for k in PAGE_KEYS:
                    if k in payload:
                        meta["total_pages"] = payload[k]
                return value, meta
        # dict of lists (e.g. {"leads": [...], "total": n}) already handled;
        # single object payload -> wrap it
        for value in payload.values():
            if isinstance(value, list):
                return value, meta
    return [], meta


def dig(obj: Any, *paths: str, default: Any = None) -> Any:
    """Try several dotted paths; return the first non-empty hit."""
    for path in paths:
        cur = obj
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
                cur = cur[int(part)]
            else:
                ok = False
                break
        if ok and cur is not None and cur != "":
            return cur
    return default


def first_list(obj: dict, *paths: str) -> list:
    for path in paths:
        value = dig(obj, path)
        if isinstance(value, list):
            return value
    return []


def normalize_lead_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Map an undocumented REsimpli lead record onto our internal shape.

    Handles every shape seen in the wild:
      * ``/lead/list``      → flat item (``{_id, number, mainStatusTitle, ...}``)
      * ``/lead/details``   → ``{leadData: {..., contactData: [...]}}``
      * mock client         → flat item (``{contactDetails: {...}}``)

    Every field is optional; anything that cannot be located is returned as
    None rather than guessed.
    """
    if not isinstance(raw, dict):
        raw = {}
    inner = raw.get("leadData")
    if isinstance(inner, dict) and inner:
        raw = inner
    external_id = dig(raw, "_id", "id", "leadId", "lead_id", "objectId")

    # Contact record: `contactData` (live /lead/details) or `contactDetails` (mock).
    contact_records = [c for c in first_list(raw, "contactData", "contacts") if isinstance(c, dict)]
    contact: dict[str, Any] = (
        next((c for c in contact_records if c.get("isSellerContact")), None)
        or next((c for c in contact_records if c.get("isPrimary")), None)
        or (contact_records[0] if contact_records else {})
    )
    legacy = raw.get("contactDetails") if isinstance(raw.get("contactDetails"), dict) else {}

    first = dig(contact, "firstName") or dig(legacy, "firstName", "firstname") or dig(
        raw, "firstName", "firstname", "contact.firstName"
    )
    last = dig(contact, "lastName") or dig(legacy, "lastName", "lastname") or dig(
        raw, "lastName", "lastname", "contact.lastName"
    )
    full = dig(contact, "fullName") or dig(raw, "name", "fullName", "contactDetails.fullName")

    phones: list[dict[str, Any]] = []
    for item in first_list(raw, "contactDetails.phoneNumbers", "phoneNumbers", "phones", "contact.phones") + first_list(
        contact, "phoneNumbers", "phones"
    ):
        if isinstance(item, dict):
            number = dig(item, "phoneNumber", "number", "value", "phone")
            if number:
                phones.append({"number": str(number), "is_primary": bool(dig(item, "isPrimary", "primary", default=False))})
        elif item:
            phones.append({"number": str(item), "is_primary": len(phones) == 0})
    if not phones:
        # /lead/list exposes a single `number`; /lead/details adds `priorityNumber`
        single = dig(raw, "priorityNumber", "number", "phoneNumber", "mobile")
        if single:
            phones.append({"number": str(single), "is_primary": True})

    emails: list[dict[str, Any]] = []
    for item in first_list(raw, "contactDetails.emails", "emails", "contact.emails") + first_list(contact, "emails"):
        if isinstance(item, dict):
            value = dig(item, "email", "emailAddress", "value")
            if value:
                emails.append({"email": str(value), "is_primary": bool(dig(item, "isPrimary", "primary", default=False))})
        elif item:
            emails.append({"email": str(item), "is_primary": len(emails) == 0})
    if not emails:
        single_email = dig(raw, "email", "primaryEmail")
        if single_email:
            emails.append({"email": str(single_email), "is_primary": True})

    primary_phone = next((p["number"] for p in phones if p["is_primary"]), phones[0]["number"] if phones else None)
    primary_email = next((e["email"] for e in emails if e["is_primary"]), emails[0]["email"] if emails else None)

    status_obj = dig(raw, "mainStatus", "status", "leadStatus")
    if isinstance(status_obj, dict):
        status_name = dig(status_obj, "name", "title", "statusName")
        status_id = dig(status_obj, "_id", "id", "statusId")
    else:
        status_name = status_obj or dig(raw, "mainStatusTitle", "statusTitle", "leadStatusTitle")
        status_id = dig(raw, "mainStatusId", "statusId")

    pipeline_obj = dig(raw, "pipeline", "leadPipeline")
    if isinstance(pipeline_obj, dict):
        pipeline_name = dig(pipeline_obj, "name", "title")
        pipeline_id = dig(pipeline_obj, "_id", "id")
    else:
        pipeline_name = pipeline_obj
        pipeline_id = dig(raw, "pipelineId")

    address = dig(
        raw,
        "propertyDetails.address",
        "property.address",
        "propertyAddress",
        "address",
        "propertyDetails.fullAddress",
    )
    source = dig(raw, "leadSource.name", "leadSource", "source.name", "source", "listSource.name", "listSource") or dig(
        raw, "crmQuestionTitle", "marketingTitle"
    )

    dnc = bool(
        dig(raw, "contactDetails.doNotCall", "doNotCall", "dnc", default=False)
        or dig(raw, "contactDetails.doNotText", "doNotText", default=False)
        or contact.get("doNotCall")
        or contact.get("doNotText")
    )

    # Assigned user: live records store `assignUser` as {teamId: [userIds]};
    # the mock stores {name: "..."}. The id is resolved to a name during sync.
    assigned_user_id = None
    assign = raw.get("assignUser")
    if isinstance(assign, dict):
        for key, value in assign.items():
            if key == "name":
                continue
            if isinstance(value, list):
                assigned_user_id = next((str(v) for v in value if isinstance(v, str) and v), None)
            elif isinstance(value, str) and value:
                assigned_user_id = value
            if assigned_user_id:
                break
    if not assigned_user_id:
        main_user = dig(raw, "mainUserId")
        assigned_user_id = str(main_user) if isinstance(main_user, str) and main_user else None

    tags = first_list(raw, "tags", "tagList", "contactDetails.tags")
    tags = [dig(t, "name", "title", default=t) if isinstance(t, (dict, list)) else t for t in tags]
    tags = [t for t in tags if isinstance(t, str)]

    return {
        "external_id": str(external_id) if external_id else None,
        "first_name": first,
        "last_name": last,
        "full_name": full,
        "primary_phone": primary_phone,
        "phones": phones,
        "primary_email": primary_email,
        "emails": emails,
        "source_status": status_name,
        "source_status_id": str(status_id) if status_id else None,
        "pipeline_name": pipeline_name,
        "pipeline_id": str(pipeline_id) if pipeline_id else None,
        "address": address,
        "lead_source": source,
        "original_creation_date": dig(raw, "leadCreated", "createdAt", "createdDate", "created_at", "leadCreationDate"),
        "do_not_contact": dnc,
        "is_hot_lead": bool(dig(raw, "isHotLead", "hotLead", default=False)),
        "assigned_manager": dig(
            raw, "assignUser.name", "assignedTo.name", "assignee.name", "user.name", "assignedUserName"
        ),
        "assigned_user_id": assigned_user_id,
        "tags": tags,
        "notes": notes_text(raw),
        "raw": raw,
    }


def notes_text(raw: dict[str, Any]) -> Optional[str]:
    """Return the first *string* note-like field. Note collections are handled
    separately during detail enrichment so we never stringify a list."""
    for key in ("comment", "note", "description", "notes"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# Live v6 numeric activity codes (observed 2026-10-21 via /activityList).
# Unknown codes fall back to `other`; the raw payload keeps the original number.
_ACTIVITY_CODE_TYPES: dict[int, str] = {
    1: "call",
    8: "note",
    9: "task",
    10: "status_change",
    11: "status_change",
    14: "note",
    16: "status_change",
}

_HTML_TAG = re.compile(r"<[^>]+>")


def strip_html(value: Any) -> Optional[str]:
    """Flatten CRM comment HTML (``<p>...</p>``) into plain text."""
    if not isinstance(value, str):
        return None
    text = html.unescape(_HTML_TAG.sub(" ", value.replace("\r", "")))
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(ln for ln in lines if ln)
    return text or None


def normalize_activity_payload(raw: dict[str, Any], fallback_lead_id: Optional[str] = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}

    # Live direction values are `outgoingCall` / `incomingSms` / ...; the mock
    # and named payloads already use `outbound` / `inbound` / `internal`.
    direction_raw = str(dig(raw, "direction", "type.direction") or "").strip()
    low = direction_raw.lower()
    derived_type = (
        "call"
        if "call" in low
        else "text"
        if ("sms" in low or "text" in low)
        else "email"
        if "mail" in low
        else None
    )
    if direction_raw:
        direction = "outbound" if low.startswith("out") else ("inbound" if low.startswith("in") else direction_raw)
    else:
        direction = None

    # Type: direction-derived (most reliable live), then a named value, then
    # the numeric v6 code.
    raw_type = dig(raw, "activityType", "type.name", "type", "activityName")
    code: Optional[int] = None
    if isinstance(raw_type, bool):
        raw_type = None
    elif isinstance(raw_type, (int, float)):
        code = int(raw_type)
        raw_type = None
    elif isinstance(raw_type, str):
        raw_type = raw_type.strip() or None
        if raw_type and raw_type.isdigit():
            code = int(raw_type)
            raw_type = None
    activity_type = derived_type or raw_type
    if activity_type is None:
        activity_type = _ACTIVITY_CODE_TYPES.get(code, "other") if code is not None else "other"
    if direction is None and activity_type in {"note", "task", "status_change"}:
        direction = "internal"

    # Outcomes: REsimpli reports call results in `voiceCallStatus`
    # ("no-answer", "completed", ...); a connected flag overrides everything.
    # `status` is sometimes an object ({_id, name, color}) — keep only its name.
    outcome_raw = dig(raw, "outcome", "callOutcome", "status") or dig(raw, "voiceCallStatus")
    if isinstance(outcome_raw, dict):
        outcome_raw = dig(outcome_raw, "name", "title", "label") or None
    elif isinstance(outcome_raw, (list, tuple, set)):
        outcome_raw = None
    outcome = outcome_raw
    if dig(raw, "iscallConnected", default=False) or dig(raw, "isConnected", default=False):
        outcome = "connected"

    summary = strip_html(dig(raw, "summary", "title", "subject", "comment", "description"))
    detail = strip_html(dig(raw, "detail", "body", "content", "comment", "notes", "message"))
    if not summary and activity_type in {"call", "text"}:
        # Call/SMS logs frequently arrive without a comment. Build a plain label
        # from fields the record does have — presentation only, no invention.
        peer_out = dig(raw, "to")
        peer_in = dig(raw, "from")
        label = "call" if activity_type == "call" else "SMS"
        if direction == "outbound":
            summary = f"Outgoing {label}" + (f" to {peer_out}" if peer_out else "")
        elif direction == "inbound":
            summary = f"Incoming {label}" + (f" from {peer_in}" if peer_in else "")
        elif peer_out or peer_in:
            summary = f"Logged {label} ({peer_out or peer_in})"
        else:
            summary = f"Logged {label}"

    return {
        "external_id": str(dig(raw, "_id", "id", "activityId", "logId") or "") or None,
        "lead_external_id": dig(raw, "leadId", "lead._id", "subModuleId", default=fallback_lead_id),
        "activity_type": activity_type,
        "direction": direction,
        "outcome": outcome,
        "occurred_at": dig(raw, "activityDate", "date", "createdAt", "calledAt", "occurredAt", "activityTime"),
        "recorded_at": dig(raw, "createdDate", "created_at", "recordedAt", "createdAt"),
        "summary": summary,
        "detail": detail,
        "raw": raw,
    }


def normalize_appointment_payload(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    lead = dig(raw, "leadId", "lead._id", "lead", "subModuleId")
    return {
        "external_id": str(dig(raw, "_id", "id", "appointmentId") or "") or None,
        "lead_external_id": lead if isinstance(lead, str) else dig(lead, "_id", "id"),
        "lead_name": dig(raw, "leadName", "lead.name", "contactName", "name"),
        "scheduled_at": dig(raw, "appointmentDateTime", "appointmentDate", "startDateTime", "date", "scheduledAt"),
        "end_at": dig(raw, "endDateTime", "appointmentEndDate"),
        "status": dig(raw, "appointmentStatus", "status", "statusName"),
        "appointment_type": dig(raw, "appointmentType", "type", "typeName"),
        "appointment_subtype": dig(raw, "appointmentSubType", "subType"),
        "notes": notes_text(raw) if isinstance(raw, dict) else None,
        "raw": raw,
    }


# --------------------------------------------------------------------------- #
# Live client
# --------------------------------------------------------------------------- #
@dataclass
class ApiLogEntry:
    path: str
    status: Optional[int]
    duration_ms: int
    ok: bool
    error: Optional[str] = None


class ResimpliClient:
    """Synchronous REsimpli Open API v6 client with bounded retry/backoff."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.resimpli.com/api/v6/openapi",
        timeout: float = 30.0,
        rate_limit_per_minute: int = 100,
        max_retries: int = 4,
    ):
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self.rate_limit_per_minute = max(1, rate_limit_per_minute)
        self.max_retries = max(0, max_retries)
        self._request_log: list[ApiLogEntry] = []
        self._last_requests: list[float] = []
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                # Documented auth format: the raw key, no "Bearer" prefix.
                "Authorization": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "acquisitions-assistant/1.0 (+local)",
            },
            timeout=timeout,
        )

    # -- plumbing ---------------------------------------------------------- #
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ResimpliClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @property
    def request_log(self) -> list[dict[str, Any]]:
        return [vars(e) for e in self._request_log[-25:]]

    def _throttle(self) -> None:
        """Client-side spacing so we stay under the documented per-minute cap."""
        window = 60.0
        now = time.monotonic()
        self._last_requests = [t for t in self._last_requests if now - t < window]
        if len(self._last_requests) >= self.rate_limit_per_minute:
            sleep_for = window - (now - self._last_requests[0]) + 0.05
            if sleep_for > 0:
                logger.info("Client-side rate throttle: sleeping %.2fs", sleep_for)
                time.sleep(min(sleep_for, 60.0))
        self._last_requests.append(time.monotonic())

    def post(self, path: str, payload: Optional[dict[str, Any]] = None) -> Any:
        if not self.api_key:
            raise ResimpliAuthError("REsimpli API key is not configured")
        body = payload or {}
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            started = time.monotonic()
            try:
                response = self._client.post(path, json=body)
            except httpx.TimeoutException as exc:
                last_error = ResimpliNetworkError(f"Timeout calling {path}")
                self._log(path, None, started, False, str(last_error))
                if attempt < self.max_retries:
                    time.sleep(self._backoff(attempt))
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                last_error = ResimpliNetworkError(f"Network error calling {path}: {exc.__class__.__name__}")
                self._log(path, None, started, False, str(last_error))
                if attempt < self.max_retries:
                    time.sleep(self._backoff(attempt))
                    continue
                raise last_error from exc

            if response.status_code == 401 or response.status_code == 403:
                self._log(path, response.status_code, started, False, "auth failed")
                raise ResimpliAuthError(
                    f"REsimpli rejected the API key (HTTP {response.status_code}). "
                    "Check RESIMPLI_API_KEY (Settings -> Webhook - API Token -> API Token tab in REsimpli; "
                    "use the Open API token, not the Zapier token)."
                )
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else self._backoff(attempt)
                self._log(path, response.status_code, started, False, "rate limited")
                last_error = ResimpliRateLimitError(f"Rate limited by REsimpli on {path}")
                if attempt < self.max_retries:
                    time.sleep(min(wait, 60.0))
                    continue
                raise last_error
            if response.status_code >= 500:
                last_error = ResimpliApiError(f"REsimpli server error {response.status_code} on {path}", response.status_code)
                self._log(path, response.status_code, started, False, str(last_error))
                if attempt < self.max_retries:
                    time.sleep(self._backoff(attempt))
                    continue
                raise last_error
            if response.status_code >= 400:
                detail = _safe_body(response)
                self._log(path, response.status_code, started, False, "client error")
                raise ResimpliApiError(
                    f"REsimpli rejected {path} (HTTP {response.status_code})",
                    status_code=response.status_code,
                    body=detail,
                )

            self._log(path, response.status_code, started, True)
            try:
                return response.json() if response.content else {}
            except ValueError:
                return {"raw_text": response.text}

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(30.0, (2**attempt) + random.uniform(0, 0.5))

    def _log(self, path: str, status: Optional[int], started: float, ok: bool, error: Optional[str] = None) -> None:
        self._request_log.append(
            ApiLogEntry(path=path, status=status, duration_ms=int((time.monotonic() - started) * 1000), ok=ok, error=error)
        )
        if len(self._request_log) > 200:
            self._request_log = self._request_log[-100:]

    # -- documented endpoints ---------------------------------------------- #
    def get_user_info(self) -> Any:
        """POST /getUserInfo — validate the integration API key."""
        return self.post("/getUserInfo", {})

    def list_leads(
        self,
        page: int = 1,
        limit: int = 100,
        search: Optional[str] = None,
        pipeline_id: Optional[str] = None,
        main_status_ids: Optional[list[str]] = None,
    ) -> tuple[list[dict], dict[str, Any]]:
        payload: dict[str, Any] = {"page": page, "limit": max(1, min(limit, 100))}
        payload["searchStr"] = (search or "").lower()
        filter_data: dict[str, Any] = {}
        if pipeline_id:
            filter_data["pipelineId"] = pipeline_id
        if main_status_ids:
            filter_data["mainStatusId"] = main_status_ids
        payload["filterData"] = filter_data
        json_body = self.post("/lead/list", payload)
        return extract_list(json_body)

    def lead_details(self, lead_id: str) -> Any:
        return self.post("/lead/details", {"leadId": lead_id})

    def add_lead(self, body: dict[str, Any]) -> Any:
        """POST /lead/add — the only write used for approved historical imports."""
        return self.post("/lead/add", body)

    def get_pipelines(self, module_type: int = 1, page: int = 1, limit: int = 100) -> list[dict]:
        body = self.post("/getPipelineList", {"moduleType": module_type, "page": page, "limit": limit})
        items, _ = extract_list(body, ("pipelines",) + LIST_KEYS)
        return items

    def activity_list(self, sub_module_id: str, page: int = 1, limit: int = 100, type_: int = 1) -> list[dict]:
        body = self.post(
            "/activityList",
            {"moduleId": 1, "subModuleId": sub_module_id, "type": type_, "page": page, "limit": limit},
        )
        items, _ = extract_list(body, ("activities", "activityList") + LIST_KEYS)
        return items

    def call_log_list(self, sub_module_id: str, page: int = 1, limit: int = 100, type_: int = 1) -> list[dict]:
        body = self.post(
            "/callLogList",
            {"moduleId": 1, "subModuleId": sub_module_id, "type": type_, "page": page, "limit": limit},
        )
        items, _ = extract_list(body, ("callLogs", "callLogList", "logs") + LIST_KEYS)
        return items

    def appointment_list(
        self,
        page: int = 1,
        limit: int = 100,
        is_upcoming: Optional[bool] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> list[dict]:
        payload: dict[str, Any] = {
            "appointmentType": 9,
            "appointmentStatus": 9,
            "qualification": 9,
            "page": page,
            "limit": max(1, min(limit, 100)),
            "assignUserId": [],
        }
        if is_upcoming is not None:
            payload["isUpcoming"] = is_upcoming
        if start:
            payload["startDateTime"] = start
        if end:
            payload["endDateTime"] = end
        body = self.post("/appointmentList", payload)
        items, _ = extract_list(body, ("appointments", "appointmentList") + LIST_KEYS)
        return items

    def marketing_campaigns(self) -> list[dict]:
        body = self.post("/marketingCampaignList", {"page": 1, "limit": 100})
        items, _ = extract_list(body, ("marketingCampaigns", "campaigns") + LIST_KEYS)
        return items

    def markets(self) -> list[dict]:
        body = self.post("/marketList", {"page": 1, "limit": 100})
        items, _ = extract_list(body, ("markets",) + LIST_KEYS)
        return items

    def users(self) -> list[dict]:
        body = self.post("/userList", {"page": 1, "limit": 100})
        items, _ = extract_list(body, ("users", "userList") + LIST_KEYS)
        return items

    def tags(self) -> list[dict]:
        body = self.post("/tagList", {"page": 1, "limit": 100})
        items, _ = extract_list(body, ("tags", "tagList") + LIST_KEYS)
        return items

    def validate(self) -> dict[str, Any]:
        info = self.get_user_info()
        return {"ok": True, "info": _summarize_user_info(info)}


def _safe_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return {"raw": response.text[:500]}


def _summarize_user_info(info: Any) -> dict[str, Any]:
    payload = extract_payload(info)
    if not isinstance(payload, dict):
        return {"raw": str(payload)[:300]}
    return {
        "company": dig(payload, "company.name", "companyName", "name", "company"),
        "user": dig(payload, "user.name", "userName", "email", "user.email"),
        "raw_keys": sorted(payload.keys())[:30],
    }


def build_client(
    api_key: str,
    base_url: str,
    timeout: float,
    rate_limit: int,
    max_retries: int = 4,
) -> ResimpliClient:
    return ResimpliClient(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        rate_limit_per_minute=rate_limit,
        max_retries=max_retries,
    )


# --------------------------------------------------------------------------- #
# Mock client — used when no API key is configured (never hits the network)
# --------------------------------------------------------------------------- #
@dataclass
class MockResimpliClient:
    api_key: str = "mock"
    base_url: str = "mock://resimpli"
    rate_limit_per_minute: int = 100
    max_retries: int = 0
    fail_auth: bool = False
    fail_rate_limit: bool = False
    fail_next_calls: int = 0
    created_leads: list[dict[str, Any]] = field(default_factory=list)
    _request_log: list[ApiLogEntry] = field(default_factory=list)
    _counter: int = 1000

    def close(self) -> None:  # pragma: no cover - parity with live client
        pass

    def __enter__(self) -> "MockResimpliClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @property
    def request_log(self) -> list[dict[str, Any]]:
        return [vars(e) for e in self._request_log]

    def _record(self, path: str, ok: bool = True, error: Optional[str] = None) -> None:
        self._request_log.append(ApiLogEntry(path=path, status=200 if ok else 400, duration_ms=5, ok=ok, error=error))

    def _maybe_fail(self, path: str) -> None:
        if self.fail_auth:
            self._record(path, ok=False, error="auth")
            raise ResimpliAuthError("Mock auth failure")
        if self.fail_rate_limit:
            self._record(path, ok=False, error="429")
            raise ResimpliRateLimitError("Mock rate limit")
        if self.fail_next_calls > 0:
            self.fail_next_calls -= 1
            self._record(path, ok=False, error="flaky")
            raise ResimpliNetworkError("Mock transient network failure")

    def get_user_info(self) -> Any:
        self._maybe_fail("/getUserInfo")
        self._record("/getUserInfo")
        return {"data": {"company": {"name": "Mock Acquisitions Co"}, "user": {"name": "demo@local"}}}

    def list_leads(self, page=1, limit=100, search=None, pipeline_id=None, main_status_ids=None):
        self._maybe_fail("/lead/list")
        self._record("/lead/list")
        items = _mock_leads()
        if search:
            low = search.lower()
            items = [i for i in items if low in json_dumps(i).lower()]
        total = len(items)
        start = (page - 1) * limit
        return items[start : start + limit], {"total": total, "total_pages": max(1, -(-total // limit))}

    def lead_details(self, lead_id: str) -> Any:
        self._maybe_fail("/lead/details")
        self._record("/lead/details")
        for item in _mock_leads():
            if item["_id"] == lead_id:
                detail = dict(item)
                detail["notes"] = [
                    {"text": "Seller wants a fast close; roof needs work.", "createdAt": "2026-10-01T12:00:00Z"}
                ]
                return {"data": detail}
        raise ResimpliApiError(f"Mock lead {lead_id} not found", status_code=404)

    def get_pipelines(self, module_type: int = 1, page: int = 1, limit: int = 100) -> list[dict]:
        self._record("/getPipelineList")
        return [
            {
                "_id": "pl_acq",
                "name": "Acquisitions",
                "mainStatuses": [
                    {"_id": "st_new", "name": "New Lead"},
                    {"_id": "st_contact", "name": "Contact Made"},
                    {"_id": "st_app", "name": "Appointment Set"},
                    {"_id": "st_uc", "name": "Under Contract"},
                ],
            }
        ]

    def activity_list(self, sub_module_id: str, page: int = 1, limit: int = 100, type_: int = 1) -> list[dict]:
        self._record("/activityList")
        return _mock_activities().get(sub_module_id, [])

    def call_log_list(self, sub_module_id: str, page: int = 1, limit: int = 100, type_: int = 1) -> list[dict]:
        self._record("/callLogList")
        return _mock_activities().get(sub_module_id, [])

    def appointment_list(self, page=1, limit=100, is_upcoming=None, start=None, end=None) -> list[dict]:
        self._record("/appointmentList")
        return _mock_appointments()

    def marketing_campaigns(self) -> list[dict]:
        return [{"_id": "mc_1", "name": "Facebook Oct"}]

    def markets(self) -> list[dict]:
        return [{"_id": "mk_1", "name": "Columbus OH"}]

    def users(self) -> list[dict]:
        return [{"_id": "u_1", "name": "Sam Rivera"}]

    def tags(self) -> list[dict]:
        return [{"_id": "t_1", "name": "hot"}]

    def add_lead(self, body: dict[str, Any]) -> Any:
        self._maybe_fail("/lead/add")
        self._counter += 1
        created = {
            "_id": f"mock_{self._counter}",
            "contactDetails": {
                "firstName": dig(body, "contactDetails.firstName"),
                "lastName": dig(body, "contactDetails.lastName"),
                "phoneNumbers": dig(body, "contactDetails.phoneNumbers", default=[]),
                "emails": dig(body, "contactDetails.emails", default=[]),
            },
            "propertyDetails": {"address": body.get("address")},
            "mainStatus": {"_id": body.get("mainStatusId"), "name": "New Lead"},
            "createdAt": datetime.utcnow().isoformat() + "Z",
        }
        self.created_leads.append(created)
        self._record("/lead/add")
        return {"data": created}

    def validate(self) -> dict[str, Any]:
        self.get_user_info()
        return {"ok": True, "info": {"company": "Mock Acquisitions Co", "mode": "mock"}}


def json_dumps(obj: Any) -> str:
    import json

    try:
        return json.dumps(obj, default=str)
    except Exception:  # pragma: no cover
        return str(obj)


def _mock_leads() -> list[dict[str, Any]]:
    base = datetime(2026, 9, 1, 12, 0)
    rows = [
        ("66f1c2a9e4b0a1d3c8f20417", "Dana", "Whitfield", "6145550142", "dana.w@example.com", "12 Oak St, Columbus, OH 43215", "New Lead", "Facebook", 0),
        ("66f1c2a9e4b0a1d3c8f20418", "Marcus", "Reed", "6145550177", "mreed@example.com", "88 Birch Ave, Grove City, OH 43123", "Contact Made", "Craigslist", 6),
        ("66f1c2a9e4b0a1d3c8f20419", "Priya", "Nair", "6145550199", "pnair@example.com", "410 Maple Ct, Dublin, OH 43017", "Appointment Set", "Referral", 14),
        ("66f1c2a9e4b0a1d3c8f20420", "Harold", "Gibson", "6145550111", "", "7 Elm St, Reynoldsburg, OH 43068", "Under Contract", "Probate List", 40),
        ("66f1c2a9e4b0a1d3c8f20421", "Sofia", "Alvarez", "6145550155", "sofia.a@example.com", "231 Pine Rd, Hilliard, OH 43026", "New Lead", "Direct Mail", 1),
    ]
    out = []
    for idx, (lid, first, last, phone, email, address, status, source, days) in enumerate(rows):
        out.append(
            {
                "_id": lid,
                "contactDetails": {
                    "firstName": first,
                    "lastName": last,
                    "phoneNumbers": [{"phoneNumber": phone, "isPrimary": True}],
                    "emails": ([{"email": email, "isPrimary": True}] if email else []),
                    "doNotCall": False,
                    "doNotText": False,
                },
                "propertyDetails": {"address": address, "propertyType": "residential"},
                "mainStatus": {"_id": f"st_{idx}", "name": status},
                "pipeline": {"_id": "pl_acq", "name": "Acquisitions"},
                "leadSource": {"name": source},
                "leadCreated": (base + timedelta(days=days)).isoformat() + "Z",
                "assignUser": {"name": "Sam Rivera"},
                "isHotLead": idx in (2,),
                "tags": [{"name": "october"}],
            }
        )
    return out


def _mock_activities() -> dict[str, list[dict[str, Any]]]:
    return {
        "66f1c2a9e4b0a1d3c8f20418": [
            {
                "_id": "act_1",
                "activityType": "call",
                "direction": "outbound",
                "outcome": "no answer",
                "activityDate": "2026-10-05T15:30:00Z",
                "summary": "Outbound call",
                "description": "Rings out, no voicemail greeting set.",
            },
            {
                "_id": "act_2",
                "activityType": "call",
                "direction": "inbound",
                "outcome": "connected",
                "activityDate": "2026-10-08T18:05:00Z",
                "summary": "Seller called back",
                "description": "Wants an offer next week; tenants in place until January.",
            },
        ],
        "66f1c2a9e4b0a1d3c8f20419": [
            {
                "_id": "act_3",
                "activityType": "note",
                "direction": "internal",
                "outcome": "callback requested",
                "activityDate": "2026-10-10T14:00:00Z",
                "summary": "Callback requested",
                "description": "Asked us to call back after 5pm regarding repairs estimate.",
            }
        ],
    }


def _mock_appointments() -> list[dict[str, Any]]:
    now = datetime.utcnow()
    return [
        {
            "_id": "appt_1",
            "leadId": "66f1c2a9e4b0a1d3c8f20419",
            "leadName": "Priya Nair",
            "appointmentDateTime": (now + timedelta(days=2)).replace(hour=17, minute=0).isoformat() + "Z",
            "appointmentStatus": 1,
            "status": "Kept",
            "appointmentType": 0,
            "notes": "Walk the property with the seller.",
        }
    ]
