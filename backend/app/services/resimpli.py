"""Only documented read operations. POST does not imply a write in this API.
Response shapes are deliberately configurable and unverified until tested on the user's account.
"""

import hashlib
import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import httpx
from pydantic import BaseModel, Field
from ..config import ROOT

BASE_URL = "https://api.resimpli.com/api/v6/openapi"
READ_PATHS = frozenset(
    {
        "/lead/list",
        "/lead/details",
        "/activityList",
        "/callLogList",
        "/appointmentList",
        "/getPipelineList",
        "/getUserInfo",
    }
)


class IntegrationError(Exception):
    pass


class AdapterResource(BaseModel):
    list_path: str = ""
    detail_path: str = ""
    total_path: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)


class ResponseAdapter(BaseModel):
    description: str
    success_path: str | None = None
    success_value: object = True
    leads: AdapterResource
    activities: AdapterResource
    calls: AdapterResource
    appointments: AdapterResource
    pipelines: AdapterResource = Field(default_factory=AdapterResource)
    contact_outcomes: dict[str, str] = Field(default_factory=dict)
    appointment_statuses: dict[str, str] = Field(default_factory=dict)


def at_path(data, path):
    if not path:
        return data
    value = data
    for key in path.split("."):
        if isinstance(value, list) and key.isdigit():
            index = int(key)
            if index >= len(value):
                return None
            value = value[index]
        elif isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None
    return value


def mapped_record(record, resource):
    if not isinstance(record, dict):
        raise IntegrationError("Malformed resource record: expected an object")
    return {field: at_path(record, path) for field, path in resource.fields.items()}


def load_adapter(settings):
    if settings.resimpli_mode == "fixture":
        path = ROOT / "backend/fixtures/response-adapter.json"
    else:
        if not settings.resimpli_adapter_verified or not settings.resimpli_adapter_path:
            raise IntegrationError(
                "Live response mapping is unverified. Configure and verify a local response adapter first."
            )
        path = Path(settings.resimpli_adapter_path).expanduser()
    try:
        return ResponseAdapter.model_validate_json(path.read_text())
    except (OSError, ValueError) as exc:
        raise IntegrationError("Response adapter file is missing or invalid; no requests were made.") from exc


class ResimpliClient:
    def __init__(self, settings, transport=None, sleeper=time.sleep, adapter=None):
        if settings.resimpli_mode == "disabled":
            raise IntegrationError("REsimpli sync is disabled. Import locally or configure the integration.")
        if settings.resimpli_mode == "live" and not settings.resimpli_api_key:
            raise IntegrationError("RESIMPLI_API_KEY is missing; configure it in the backend environment.")
        self.settings = settings
        self.adapter = adapter or load_adapter(settings)
        self.sleeper = sleeper
        self.last_request = 0
        if settings.resimpli_mode == "fixture" and transport is None:
            transport = httpx.MockTransport(self._fixture_request)
        headers = {"Accept": "application/json"}
        if settings.resimpli_api_key and settings.resimpli_mode == "live":
            headers["Authorization"] = settings.resimpli_api_key
        self.http = httpx.Client(
            base_url=BASE_URL + "/",
            headers=headers,
            timeout=httpx.Timeout(25, connect=10),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def close(self):
        self.http.close()

    def _fixture_request(self, request):
        fixture = json.loads((ROOT / "backend/fixtures/resimpli.json").read_text())
        path = request.url.path.removeprefix("/api/v6/openapi")
        body = json.loads(request.content or "{}")
        if path == "/getUserInfo":
            return httpx.Response(200, json={"ok": True, "data": {"synthetic": True}})
        if path == "/lead/details":
            record = next(
                (lead_record for lead_record in fixture["leads"] if lead_record["id"] == body.get("leadId")), None
            )
            return httpx.Response(200, json={"ok": True, "data": record})
        key = {
            "/lead/list": "leads",
            "/activityList": "activities",
            "/callLogList": "calls",
            "/appointmentList": "appointments",
            "/getPipelineList": "pipelines",
        }.get(path)
        records = fixture.get(key, [])
        if key in {"activities", "calls"}:
            records = [r for r in records if r["lead_id"] == body["subModuleId"]]
        if key == "appointments":
            records = [r for r in records if r.get("subtype", 0) == body.get("appointmentSubType", 0)]
        page, limit = body.get("page", 1), body.get("limit", 100)
        return httpx.Response(
            200,
            json={"ok": True, "data": {"records": records[(page - 1) * limit : page * limit], "total": len(records)}},
        )

    def request(self, path, body=None):
        if path not in READ_PATHS:
            raise IntegrationError("Operation blocked: only allowlisted documented read endpoints are permitted")
        for attempt in range(4):
            spacing = (
                0
                if self.settings.resimpli_mode == "fixture"
                else 60 / min(100, max(1, self.settings.sync_requests_per_minute))
            )
            wait = self.last_request + spacing - time.monotonic()
            if wait > 0:
                self.sleeper(wait)
            self.last_request = time.monotonic()
            try:
                response = self.http.post(path.lstrip("/"), json=body or {})
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == 3:
                    raise IntegrationError(f"Timeout/network failure after bounded retries on {path}") from exc
                self.sleeper(min(2**attempt, 8))
                continue
            if response.status_code in {401, 403}:
                raise IntegrationError("REsimpli rejected the credentials or account permissions (401/403)")
            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt == 3:
                    raise IntegrationError(
                        f"REsimpli transient HTTP {response.status_code} after bounded retries on {path}"
                    )
                retry = response.headers.get("Retry-After", "")
                try:
                    delay = float(retry)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError, OverflowError):
                        delay = 2**attempt
                # Do not retry sooner than a server's long Retry-After; stop this run instead.
                if delay > 120:
                    raise IntegrationError(f"REsimpli requested a long cooldown on {path}; try again later")
                self.sleeper(max(0.5, delay, 2**attempt))
                continue
            if not 200 <= response.status_code < 300:
                raise IntegrationError(f"REsimpli HTTP {response.status_code} on {path}; sensitive response omitted")
            try:
                data = response.json()
            except ValueError as exc:
                raise IntegrationError(f"Malformed JSON response on {path}") from exc
            if not isinstance(data, dict):
                raise IntegrationError(f"Expected an object response on {path}")
            if self.adapter.success_path and at_path(data, self.adapter.success_path) != self.adapter.success_value:
                raise IntegrationError(f"REsimpli response did not indicate success on {path}; check adapter/account")
            return data
        raise IntegrationError("Request exhausted retries")

    def pages(self, path, resource, extra=None, limit=100):
        if not 1 <= limit <= 100:
            raise IntegrationError("Page size must be between 1 and 100")
        seen, received = set(), 0
        for page in range(1, self.settings.sync_max_pages + 1):
            response = self.request(path, {**(extra or {}), "page": page, "limit": limit})
            records = at_path(response, resource.list_path)
            if not isinstance(records, list):
                raise IntegrationError(
                    f"Unrecognized response list at configured path for {path}; update verified adapter"
                )
            if records:
                digest = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
                if digest in seen:
                    raise IntegrationError(
                        f"Repeated page on {path}; synchronization stopped to prevent an infinite loop"
                    )
                seen.add(digest)
            for record in records:
                yield mapped_record(record, resource)
            received += len(records)
            total = at_path(response, resource.total_path) if resource.total_path else None
            if isinstance(total, int) and not isinstance(total, bool):
                if total < received:
                    raise IntegrationError(f"Inconsistent pagination total on {path}")
                if received >= total:
                    return
            elif len(records) < limit:
                return
            if not records:
                if isinstance(total, int) and received < total:
                    raise IntegrationError(f"Pagination ended before advertised total on {path}")
                return
        raise IntegrationError(f"Page safety limit reached on {path}; result is partial, not a complete sync")

    def details(self, external_id):
        response = self.request("/lead/details", {"leadId": external_id})
        record = at_path(response, self.adapter.leads.detail_path)
        return mapped_record(record, self.adapter.leads)

    def create_lead(self, *_args, **_kwargs):
        raise IntegrationError("External lead creation is disabled; use reviewed local import and approved CSV handoff")
