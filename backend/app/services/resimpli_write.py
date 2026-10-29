"""The only code in this application that may create a record in REsimpli.

Write scope is one endpoint: ``/lead/add``. Everything else the Open API documents is
a read, and nothing in the v6 catalogue updates a record -- there is no note endpoint,
no status endpoint and no delete worth calling. ``WRITE_PATHS`` is the allow-list, the
same way ``READ_PATHS`` fences the sync client, and a test asserts that any other path
is refused before a socket is opened.

Two behaviours are deliberate and both are about not making a mess in someone's CRM:

* A request that may have reached the server is never retried. A read timeout after the
  body was sent means the lead may exist; retrying would create a duplicate. The error
  is reported as ``outcome_unknown`` and a person checks the CRM.
* Nothing is invented. A first name that is not on the lead is not sent (the live schema
  marks it optional), a land lead without an APN is blocked rather than given a fake one,
  and the ``propertyType`` assumption, when one is made, is carried in ``warnings`` so
  the dry run can show it.
"""

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx
from pydantic import BaseModel, Field, field_validator

from .normalization import normalize_phone
from .resimpli import BASE_URL, IntegrationError

WRITE_PATHS = frozenset({"/lead/add"})
PROPERTY_TYPES = ("land", "residential")
MAX_PHONES = 10
LAND_WORDS = ("land", "lot", "acreage", "acre", "vacant", "undeveloped", "unimproved")
RESIDENTIAL_WORDS = (
    "residential",
    "single family",
    "single-family",
    "sfr",
    "house",
    "home",
    "duplex",
    "triplex",
    "fourplex",
    "multi",
    "condo",
    "townhouse",
    "townhome",
    "mobile",
    "manufactured",
    "apartment",
    "unit",
)


class CrmWriteError(IntegrationError):
    """A write failed, or was never attempted because a local rule said no."""

    def __init__(self, message, code="crm_write_failed", status=None):
        super().__init__(message)
        self.code = code
        self.status = status


class CrmPushBlocked(CrmWriteError):
    """Eligibility failed locally: nothing was sent, and nothing will be until it is fixed."""

    def __init__(self, reason, message):
        super().__init__(message, code=reason)
        self.reason = reason


class CrmDefaults(BaseModel):
    """The four account ObjectIds every creation needs, as configured in Settings.

    ``marketing_campign_id`` reproduces REsimpli's own spelling of ``marketingCampignId``
    in the request body; the field would be sent wrong if the typo were "fixed".
    """

    model_config = {"extra": "forbid"}
    marketing_campign_id: str = Field(min_length=1, max_length=64)
    market_id: str = Field(min_length=1, max_length=64)
    pipeline_id: str = Field(min_length=1, max_length=64)
    main_status_id: str = Field(min_length=1, max_length=64)

    @field_validator("marketing_campign_id", "market_id", "pipeline_id", "main_status_id")
    @classmethod
    def identifier(cls, value):
        text = (value or "").strip()
        if not text:
            raise ValueError("Load the account IDs from REsimpli before pushing")
        if len(text) > 64 or any(character.isspace() for character in text):
            raise ValueError("An account ID is one token of at most 64 characters")
        return text

    def as_body(self):
        return {
            "marketingCampignId": self.marketing_campign_id,
            "marketId": self.market_id,
            "pipelineId": self.pipeline_id,
            "mainStatusId": self.main_status_id,
        }


def ten_digit_phone(value):
    """Return the 10-digit US number REsimpli expects, or None when it is not one.

    The local store keeps E.164, which is the right thing to keep; the CRM's documented
    phone format is 10 digits, so the conversion happens here and nowhere else.
    """
    if not value:
        return None
    try:
        e164 = normalize_phone(value)
    except ValueError:
        return None
    digits = re.sub(r"\D", "", e164 or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


def lead_phones(lead):
    """Every distinct usable phone on a lead, primary first, capped at the API maximum."""
    candidates = []
    for phone in (lead.primary_phone, lead.phone2, lead.phone3, lead.phone4, lead.phone5):
        if phone:
            candidates.append(phone)
    for record in lead.phones or []:
        if record.phone:
            candidates.append(record.phone)
        elif record.phone_normalized:
            candidates.append(record.phone_normalized)
    numbers, seen = [], set()
    for candidate in candidates:
        digits = ten_digit_phone(candidate)
        if digits and digits not in seen:
            seen.add(digits)
            numbers.append(digits)
    return numbers[:MAX_PHONES]


def lead_address(lead):
    """The property address as one line, or None when the lead has no street address."""
    properties = list(lead.properties or [])
    for prop in properties:
        if prop.street_address:
            parts = [prop.street_address, prop.city, prop.state]
            line = ", ".join(part.strip() for part in parts if part and str(part).strip())
            if prop.zip_code:
                line = f"{line} {str(prop.zip_code).strip()}".strip()
            return line or None
    return None


def lead_apn(lead):
    """The APN, read from wherever the importer stored it. Never generated."""
    for prop in lead.properties or []:
        metadata = prop.property_metadata or {}
        for value in (metadata.get("apn"), (metadata.get("facts") or {}).get("apn")):
            if value and str(value).strip():
                return str(value).strip()
    normalized = (lead.source_data or {}).get("normalized") or {}
    value = normalized.get("apn")
    return str(value).strip() if value and str(value).strip() else None


def property_type_for(lead):
    """Return ``(property_type, warning_or_None)`` for the two values the API accepts.

    A land-ish label is land; a residential label is residential; a blank or unrecognised
    label becomes residential *with a warning*, because land is the branch that demands a
    real APN and quietly labelling something land would either block the push or invite a
    made-up APN.
    """
    labels = []
    for prop in lead.properties or []:
        if prop.property_type:
            labels.append(str(prop.property_type).strip().lower())
    normalized = (lead.source_data or {}).get("normalized") or {}
    if normalized.get("property_type"):
        labels.append(str(normalized["property_type"]).strip().lower())
    text = " ".join(labels).strip()
    if not text:
        return "residential", "No property type recorded; sending residential (REsimpli accepts land or residential only)"
    if any(word in text for word in LAND_WORDS):
        return "land", None
    if any(word in text for word in RESIDENTIAL_WORDS):
        return "residential", None
    return (
        "residential",
        f"Unrecognised property type {text!r}; sending residential (REsimpli accepts land or residential only)",
    )


def contact_flags(lead):
    """Do-not-contact flags that travel with the lead, in REsimpli's own field names."""
    flags = {}
    if lead.do_not_contact or lead.source_do_not_contact is True:
        flags.update({"doNotCall": True, "doNotText": True, "doNotEmail": True})
    return flags


def build_lead_payload(lead, defaults, comment=None):
    """Build the exact body ``/lead/add`` will receive, or raise ``CrmPushBlocked``.

    Pure function: it reads the lead and the configured account IDs and touches nothing.
    The dry run prints this body, and the push sends this same body, so what a person
    reviews is what the CRM gets.
    """
    warnings = []
    phones = lead_phones(lead)
    if not phones:
        has_any = any(
            value
            for value in (
                lead.primary_phone,
                lead.phone2,
                lead.phone3,
                lead.phone4,
                lead.phone5,
                *(record.phone or record.phone_normalized for record in lead.phones or []),
            )
        )
        if has_any:
            raise CrmPushBlocked(
                "invalid_phone",
                "The lead has phone numbers but none is a valid 10-digit US number; nothing was sent",
            )
        raise CrmPushBlocked(
            "needs_phone",
            "REsimpli requires a phone to create a lead; run skip trace and review a phone before pushing",
        )
    if contact_flags(lead):
        raise CrmPushBlocked(
            "do_not_contact",
            "This lead is marked do-not-contact; restricted leads are never pushed to the CRM",
        )
    address = lead_address(lead)
    if not address:
        raise CrmPushBlocked("missing_address", "This lead has no property address; nothing was sent")
    property_type, warning = property_type_for(lead)
    if warning:
        warnings.append(warning)
    apn = lead_apn(lead)
    if property_type == "land" and not apn:
        raise CrmPushBlocked(
            "land_without_apn",
            "REsimpli requires an APN for a land lead; add the APN before pushing (no APN was invented)",
        )

    contact = {"phoneNumbers": [{"phoneNumber": phones[0], "isPrimary": True}]}
    contact["phoneNumbers"].extend({"phoneNumber": number, "isPrimary": False} for number in phones[1:])
    # The live schema marks the first name optional. Only a name that exists is sent.
    if lead.first_name and str(lead.first_name).strip():
        contact["firstName"] = str(lead.first_name).strip()
    if lead.last_name and str(lead.last_name).strip():
        contact["lastName"] = str(lead.last_name).strip()
    if lead.email and "@" in str(lead.email):
        contact["emails"] = [{"email": str(lead.email).strip(), "isPrimary": True}]
    contact.update(contact_flags(lead))

    body = {
        "contactDetails": contact,
        "propertyType": property_type,
        "address": address,
        **defaults.as_body(),
    }
    if property_type == "land":
        body["apn"] = apn
    if comment:
        body["comment"] = comment
    payload = {"body": body, "warnings": warnings, "phone_count": len(phones)}
    return payload


def payload_hash(body):
    """A stable hash of exactly what would be sent, for the mapping and the audit trail."""
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def candidate_lead_ids(data):
    """Best-effort read of the new lead's id from a response shape nobody has verified.

    The v6 catalogue documents the request body but not the success payload, and there is
    no live account here, so several documented-looking keys are tried. When none matches,
    the push still counts as created and the mapping keeps ``None`` -- the address and
    phone search before the next attempt is what prevents a duplicate, not this id.
    """
    if isinstance(data, str):
        return [data] if data.strip() else []
    if not isinstance(data, dict):
        return []
    found = []
    for value in (data.get("leadId"), data.get("lead_id"), data.get("_id"), data.get("id")):
        if isinstance(value, (str, int)) and str(value).strip():
            found.append(str(value).strip())
    for key in ("data", "lead", "result", "record"):
        nested = data.get(key)
        if isinstance(nested, str) and nested.strip():
            found.append(nested.strip())
        elif isinstance(nested, dict):
            for value in (nested.get("_id"), nested.get("id"), nested.get("leadId"), nested.get("lead_id")):
                if isinstance(value, (str, int)) and str(value).strip():
                    found.append(str(value).strip())
    return found


class CrmWriteResult(BaseModel):
    path: str
    resimpli_lead_id: Optional[str] = None
    response_keys: list[str] = Field(default_factory=list)
    attempts: int = 1


def _message_from(response, limit=300):
    """A short, non-sensitive reason from an error response; the body itself is discarded."""
    try:
        data = response.json()
    except ValueError:
        return f"HTTP {response.status_code} with no JSON body"
    if isinstance(data, dict):
        for key in ("message", "error", "detail", "errorMessage"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:limit]
    return f"HTTP {response.status_code}"


class ResimpliWriter:
    """Creates leads in REsimpli. Live mode only, one allow-listed path, no blind retries."""

    def __init__(self, settings, transport=None, sleeper=time.sleep, clock=time.monotonic, timeout=25):
        if settings.resimpli_mode != "live":
            raise CrmWriteError(
                "CRM writes require live mode with a real key; fixture mode never writes",
                code="writes_need_live_mode",
            )
        if not settings.resimpli_api_key:
            raise CrmWriteError("RESIMPLI_API_KEY is missing; configure it in the backend environment", code="missing_api_key")
        self.settings = settings
        self.sleeper = sleeper
        self.clock = clock
        self.last_request = 0.0
        self.http = httpx.Client(
            base_url=BASE_URL + "/",
            headers={"Accept": "application/json", "Authorization": settings.resimpli_api_key},
            timeout=httpx.Timeout(timeout, connect=10),
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

    def _pace(self):
        spacing = 60 / min(100, max(1, self.settings.sync_requests_per_minute))
        wait = self.last_request + spacing - self.clock()
        if wait > 0:
            self.sleeper(wait)
        self.last_request = self.clock()

    def post(self, path, body):
        """POST to an allow-listed write path and return ``(json, attempts)``."""
        if path not in WRITE_PATHS:
            raise CrmWriteError(
                f"Operation blocked: {path} is not an authorized CRM write; only lead creation is allowed",
                code="path_not_authorized",
            )
        attempts = 0
        for attempt in range(4):
            attempts = attempt + 1
            self._pace()
            try:
                response = self.http.post(path.lstrip("/"), json=body)
            except httpx.ConnectError as exc:
                # Nothing was sent: the connection never opened. Safe to retry.
                if attempt == 3:
                    raise CrmWriteError(
                        "Could not reach REsimpli; no lead was created", code="network_unreachable"
                    ) from exc
                self.sleeper(min(2**attempt, 8))
                continue
            except (httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
                # The body may have been received. A retry here is how duplicates happen.
                raise CrmWriteError(
                    "The request timed out after it was sent, so the lead may exist. Check REsimpli "
                    "for this address before pushing again.",
                    code="outcome_unknown",
                ) from exc
            if response.status_code in {401, 403}:
                raise CrmWriteError(
                    "REsimpli rejected the credentials or account permissions (401/403); no lead was created",
                    code="rejected_credentials",
                    status=response.status_code,
                )
            if response.status_code == 429:
                if attempt == 3:
                    raise CrmWriteError(
                        "REsimpli is rate limiting; no lead was created. Try again later.",
                        code="rate_limited",
                        status=429,
                    )
                delay = self._retry_after(response, attempt)
                if delay > 120:
                    raise CrmWriteError(
                        "REsimpli asked for a long cooldown; no lead was created. Try again later.",
                        code="rate_limited",
                        status=429,
                    )
                self.sleeper(max(0.5, delay))
                continue
            if 500 <= response.status_code < 600:
                raise CrmWriteError(
                    f"REsimpli returned HTTP {response.status_code} while creating the lead; the lead may "
                    "exist. Check REsimpli for this address before pushing again.",
                    code="outcome_unknown",
                    status=response.status_code,
                )
            if not 200 <= response.status_code < 300:
                raise CrmWriteError(
                    f"REsimpli refused the lead ({response.status_code}): {_message_from(response)}",
                    code="rejected_payload",
                    status=response.status_code,
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise CrmWriteError(
                    "REsimpli accepted the request but returned malformed JSON; check the CRM for this lead",
                    code="outcome_unknown",
                ) from exc
            return data, attempts
        raise CrmWriteError("Request exhausted retries", code="retries_exhausted")

    def _retry_after(self, response, attempt):
        retry = response.headers.get("Retry-After", "")
        try:
            return float(retry)
        except ValueError:
            if not retry:
                return 2**attempt
            try:
                return (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                return 2**attempt

    def add_lead(self, body):
        """Create one lead. Returns the id when the response exposes one."""
        data, attempts = self.post("/lead/add", body)
        candidates = candidate_lead_ids(data)
        return CrmWriteResult(
            path="/lead/add",
            resimpli_lead_id=candidates[0] if candidates else None,
            response_keys=sorted(data.keys()) if isinstance(data, dict) else [],
            attempts=attempts,
        )
