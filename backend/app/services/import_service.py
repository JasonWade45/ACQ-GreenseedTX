"""Legacy seller-lead import center (CSV + XLSX).

Workflow: upload -> inspect -> auto/manual column mapping -> normalize ->
validate -> duplicate classification -> preview -> explicit commit -> report.

Idempotency: an import batch stores the file checksum. Re-importing the same
file is detected and refused unless the user explicitly forces a new batch.
Nothing is written to REsimpli unless the user opts in AND the account-specific
identifiers required by the documented `/lead/add` endpoint are supplied.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Appointment, Followup, ImportBatch, ImportRecord, Lead, MappingTemplate
from app.services import settings_service
from app.services.audit import audit
from app.services.dedupe import (
    NEW,
    Candidate,
    FileSeenIndex,
    find_matches,
)
from app.services.export import rows_to_csv
from app.services.leads import link_property, refresh_lead_rollups, serialize_lead
from app.services.normalization import (
    address_key,
    clean_str,
    extract_property_details,
    is_empty,
    normalize_email,
    normalize_money,
    normalize_phone,
    normalize_state,
    parse_date_flexible,
    parse_datetime_flexible,
    split_full_name,
)

logger = logging.getLogger("acquisitions.import")

# --------------------------------------------------------------------------- #
# Field catalogue
# --------------------------------------------------------------------------- #
FIELD_SPECS: list[dict[str, Any]] = [
    {"key": "external_ref", "label": "Existing REsimpli lead ID", "aliases": ["resimpliid", "resimpli", "externalid", "leadid", "lead", "crmid", "resimplileadid"], "type": "string"},
    {"key": "first_name", "label": "First name", "aliases": ["firstname", "first", "fname", "sellerfirst", "sellerfirstname", "contactfirst"], "type": "string"},
    {"key": "last_name", "label": "Last name", "aliases": ["lastname", "last", "lname", "sellerlast", "sellerlastname", "contactlast"], "type": "string"},
    {"key": "full_name", "label": "Full name", "aliases": ["name", "sellername", "fullname", "contactname", "seller", "leadname", "ownername", "sellerfullname"], "type": "string"},
    {"key": "phone", "label": "Phone number", "aliases": ["phone", "phonenumber", "mobile", "cell", "cellphone", "telephone", "mobilephone", "primaryphone", "sellerphone", "contactphone", "phone1"], "type": "phone"},
    {"key": "phone2", "label": "Alternate phone", "aliases": ["phone2", "phonenumber2", "altphone", "alternatephone", "secondaryphone", "homephone"], "type": "phone"},
    {"key": "email", "label": "Email address", "aliases": ["email", "emailaddress", "mail", "primaryemail", "selleremail", "contactemail", "e-mail"], "type": "email"},
    {"key": "address_line1", "label": "Property street address", "aliases": ["address", "propertyaddress", "streetaddress", "property", "siteaddress", "subjectproperty", "fulladdress", "address1", "street", "addressline1"], "type": "string"},
    {"key": "address_line2", "label": "Address line 2", "aliases": ["address2", "unit", "suite", "apt", "apartment", "addressline2"], "type": "string"},
    {"key": "city", "label": "City", "aliases": ["city", "town", "propertycity"], "type": "string"},
    {"key": "state", "label": "State", "aliases": ["state", "st", "provincestate", "propertystate"], "type": "string"},
    {"key": "zip_code", "label": "ZIP code", "aliases": ["zip", "zipcode", "postal", "postalcode", "zip4", "propertyzip"], "type": "string"},
    {"key": "property_type", "label": "Property type", "aliases": ["propertytype", "type", "housetype", "buildingtype"], "type": "string"},
    {"key": "lead_source", "label": "Lead source", "aliases": ["leadsource", "source", "campaign", "marketingsource", "listsource", "channel", "origin"], "type": "string"},
    {"key": "creation_date", "label": "Original lead creation date", "aliases": ["createddate", "creationdate", "leaddate", "dateadded", "leadcreated", "created", "datecreated", "acquiredate"], "type": "date"},
    {"key": "last_contact_date", "label": "Last contact date", "aliases": ["lastcontact", "lastcontactdate", "lastcontacted", "lastactivitydate", "lasttouch", "contactdate"], "type": "date"},
    {"key": "last_contact_outcome", "label": "Last contact outcome", "aliases": ["lastoutcome", "outcome", "lastresult", "callresult", "lastcontactoutcome", "disposition"], "type": "string"},
    {"key": "lead_status", "label": "Lead status", "aliases": ["status", "leadstatus", "stage", "pipelinestatus", "currentstatus"], "type": "string"},
    {"key": "assigned_manager", "label": "Assigned acquisitions manager", "aliases": ["assignedto", "assignee", "manager", "agent", "owner", "assignedmanager", "acquisitionsmanager", "rep"], "type": "string"},
    {"key": "motivation", "label": "Seller motivation", "aliases": ["motivation", "reasonforselling", "whyselling", "seller motivation"], "type": "string"},
    {"key": "asking_price", "label": "Asking price", "aliases": ["askingprice", "price", "listprice", "wholesaleprice", "sellerprice", "asking"], "type": "number"},
    {"key": "estimated_value", "label": "Estimated property value", "aliases": ["estimatedvalue", "arv", "marketvalue", "value", "estvalue"], "type": "number"},
    {"key": "repair_estimate", "label": "Repair estimate", "aliases": ["repaircost", "repairs", "repair estimate", "repair", "rehabestimate", "rehab"], "type": "number"},
    {"key": "bedrooms", "label": "Bedrooms", "aliases": ["beds", "bedrooms", "bed", "br"], "type": "number"},
    {"key": "bathrooms", "label": "Bathrooms", "aliases": ["baths", "bathrooms", "bath", "ba"], "type": "number"},
    {"key": "square_footage", "label": "Square footage", "aliases": ["sqft", "squarefeet", "size", "squarefootage"], "type": "number"},
    {"key": "appointment_date", "label": "Appointment date", "aliases": ["appointment", "appointmentdate", "showingdate", "meetingdate"], "type": "datetime"},
    {"key": "follow_up_date", "label": "Follow-up date", "aliases": ["followup", "followupdate", "nextfollowup", "callbackdate", "nexttouch"], "type": "datetime"},
    {"key": "notes", "label": "Notes", "aliases": ["notes", "note", "comments", "comment", "description", "details", "remarks"], "type": "string"},
    {"key": "do_not_contact", "label": "Do Not Contact", "aliases": ["donotcall", "dnc", "donotcontact", "donottext", "donotemail"], "type": "boolean"},
]


def _canon(header: str) -> str:
    return "".join(ch for ch in str(header).lower() if ch.isalnum())


CANON_TARGETS = {spec["key"]: {_canon(a) for a in spec["aliases"]} | {_canon(spec["key"])} for spec in FIELD_SPECS}
KEY_BY_CANON = {k: spec["key"] for spec in FIELD_SPECS for k in CANON_TARGETS[spec["key"]]}

# --------------------------------------------------------------------------- #
# External creation (/lead/add) configuration
# --------------------------------------------------------------------------- #
EXTERNAL_KEYS = ("pipelineId", "mainStatusId", "marketId", "marketingCampignId")

# Account ObjectIds required by the documented `/lead/add` endpoint, extracted
# from the live account's own lead payloads (marketId is identical across all
# 704 synced leads; the pipeline/status/campaign values are the active
# "New Leads" pipeline). Used when Settings has no override — see
# GET/POST /api/imports/external-config. Overridable per account.
KNOWN_LEAD_IDS: dict[str, str] = {
    "pipelineId": "6aa4dc48d18014f8fc5bd81e",
    "mainStatusId": "6aa4dc48d18014f8fc5bd81f",
    "marketId": "68d6eda6e1e2edad75b1f894",
    "marketingCampignId": "6aa4e64cab4bfde2eb52d93a",
    "propertyType": "residential",
}


def resolve_external_ids(db: Session, override: Optional[dict[str, Any]] = None) -> dict[str, str]:
    """Merge order: request override > stored setting > known account ids."""
    stored = settings_service.resimpli_lead_ids(db)
    override = override or {}
    resolved: dict[str, str] = {}
    for key in (*EXTERNAL_KEYS, "propertyType"):
        value = str(override.get(key) or stored.get(key) or KNOWN_LEAD_IDS.get(key) or "").strip()
        if value:
            resolved[key] = value
    return resolved


def external_config(db: Session) -> dict[str, Any]:
    ids = resolve_external_ids(db)
    stored = settings_service.resimpli_lead_ids(db)
    stored_count = sum(1 for k in EXTERNAL_KEYS if stored.get(k))
    if not all(ids.get(k) for k in EXTERNAL_KEYS):
        source = "missing"
    elif stored_count == len(EXTERNAL_KEYS):
        source = "settings"
    elif stored_count:
        source = "mixed"
    else:
        source = "known"
    return {"ids": ids, "source": source, "available": source != "missing"}


@dataclass
class FileInspection:
    filename: str
    sheets: list[str] = field(default_factory=list)
    active_sheet: Optional[str] = None
    headers: list[str] = field(default_factory=list)
    row_count: int = 0
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    auto_mapping: dict[str, Optional[str]] = field(default_factory=dict)
    unmapped_headers: list[str] = field(default_factory=list)
    checksum: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "sheets": self.sheets,
            "active_sheet": self.active_sheet,
            "headers": self.headers,
            "row_count": self.row_count,
            "sample_rows": self.sample_rows,
            "auto_mapping": self.auto_mapping,
            "unmapped_headers": self.unmapped_headers,
            "checksum": self.checksum,
            "error": self.error,
            "field_catalogue": [{"key": s["key"], "label": s["label"]} for s in FIELD_SPECS],
        }


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_rows(path: Path, sheet_name: Optional[str]) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
        sheets = workbook.sheetnames
        target = sheet_name if sheet_name in sheets else sheets[0]
        ws = workbook[target]
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            workbook.close()
            return [], [], sheets
        headers = [str(h).strip() if h is not None else f"column_{i+1}" for i, h in enumerate(header_row)]
        records: list[dict[str, Any]] = []
        for raw in rows_iter:
            if raw is None or all(is_empty(c) for c in raw):
                continue
            record = {}
            for i, header in enumerate(headers):
                record[header] = raw[i] if i < len(raw) else None
            records.append(record)
        workbook.close()
        return headers, records, sheets
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(fh, dialect=dialect)
            headers = [h.strip() for h in (reader.fieldnames or [])]
            records = [dict(row) for row in reader if any(not is_empty(v) for v in row.values())]
        return headers, records, ["CSV"]
    raise ValueError(f"Unsupported file type '{suffix}'. Upload .csv or .xlsx")


def inspect_file(path: Path, filename: str, sheet_name: Optional[str] = None) -> FileInspection:
    inspection = FileInspection(filename=filename, checksum=file_checksum(path))
    try:
        headers, records, sheets = _read_rows(path, sheet_name)
        inspection.sheets = sheets
        inspection.active_sheet = sheet_name if sheet_name in sheets else (sheets[0] if sheets else None)
        inspection.headers = headers
        inspection.row_count = len(records)
        inspection.sample_rows = [
            {k: (v if isinstance(v, (int, float, bool)) else str(v) if v is not None else None) for k, v in r.items()}
            for r in records[:5]
        ]
        inspection.auto_mapping = auto_map_columns(headers)
        mapped = {v for v in inspection.auto_mapping.values() if v}
        inspection.unmapped_headers = [h for h in headers if h not in mapped]
    except Exception as exc:  # noqa: BLE001
        inspection.error = f"{exc.__class__.__name__}: {exc}"
    return inspection


def auto_map_columns(headers: list[str]) -> dict[str, Optional[str]]:
    """target_key -> source header (or None)."""
    mapping: dict[str, Optional[str]] = {spec["key"]: None for spec in FIELD_SPECS}
    taken: set[str] = set()
    for header in headers:
        canon = _canon(header)
        target = KEY_BY_CANON.get(canon)
        if target and mapping.get(target) is None and target not in taken:
            mapping[target] = header
            taken.add(target)
    # exact label match fallback
    lower_labels = {_canon(s["label"]): s["key"] for s in FIELD_SPECS}
    for header in headers:
        canon = _canon(header)
        target = lower_labels.get(canon)
        if target and mapping.get(target) is None:
            mapping[target] = header
    return mapping


def ai_map_for_file(
    path: Path,
    filename: str,
    mapping: Optional[dict[str, str]] = None,
    sheet_name: Optional[str] = None,
) -> dict[str, Any]:
    """Rule-based mapping first, then the active AI model fills the gaps.

    The user's existing mapping wins, then alias-table rules, then (only for
    fields both left empty) the model — whose reply is validated against the
    real headers before it is accepted. Falls back to pure rules when no model
    is configured, so this endpoint is always safe to call.
    """
    from app.services.ai_service import ai_map_columns

    inspection = inspect_file(path, filename, sheet_name)
    if inspection.error:
        raise ValueError(inspection.error)
    headers = inspection.headers

    base: dict[str, Optional[str]] = {spec["key"]: None for spec in FIELD_SPECS}
    base.update(auto_map_columns(headers))
    for key, header in (mapping or {}).items():
        if header and key in base:
            base[key] = header

    engine = "rules"
    ai_error: Optional[str] = None
    used = {h for h in base.values() if h}
    free_headers = [h for h in headers if h not in used]
    empty_targets = [s for s in FIELD_SPECS if not base.get(s["key"])]
    if free_headers and empty_targets:
        samples: dict[str, list[str]] = {}
        for header in free_headers:
            values: list[str] = []
            for row in inspection.sample_rows:
                value = row.get(header)
                if value not in (None, "") and str(value) not in values:
                    values.append(str(value))
            samples[header] = values[:3]
        ai_mapping, ai_engine, ai_error = ai_map_columns(
            free_headers,
            samples,
            [{"key": s["key"], "label": s["label"], "type": s["type"]} for s in empty_targets],
        )
        for key, header in (ai_mapping or {}).items():
            if not base.get(key) and header in free_headers:
                base[key] = header
        engine = ai_engine or "rules"

    used = {h for h in base.values() if h}
    return {
        "mapping": base,
        "engine": engine,
        "error": ai_error,
        "mapped_fields": sum(1 for value in base.values() if value),
        "unmapped_headers": [h for h in headers if h not in used],
        "unmapped_fields": [s["label"] for s in FIELD_SPECS if not base.get(s["key"])],
    }


# --------------------------------------------------------------------------- #
# Row normalization
# --------------------------------------------------------------------------- #
@dataclass
class NormalizedRow:
    row_number: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    phone_normalized: Optional[str] = None
    phone_display: Optional[str] = None
    phone2: Optional[str] = None
    email: Optional[str] = None
    email_normalized: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    property_type: Optional[str] = None
    lead_source: Optional[str] = None
    creation_date: Optional[str] = None
    last_contact_date: Optional[str] = None
    last_contact_outcome: Optional[str] = None
    lead_status: Optional[str] = None
    assigned_manager: Optional[str] = None
    motivation: Optional[str] = None
    asking_price: Optional[float] = None
    estimated_value: Optional[float] = None
    repair_estimate: Optional[float] = None
    bedrooms: Optional[float] = None
    bathrooms: Optional[float] = None
    square_footage: Optional[float] = None
    appointment_date: Optional[str] = None
    follow_up_date: Optional[str] = None
    notes: Optional[str] = None
    do_not_contact: bool = False
    external_ref: Optional[str] = None
    address_key: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    original: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "phone": self.phone,
            "phone_normalized": self.phone_normalized,
            "phone_display": self.phone_display,
            "phone2": self.phone2,
            "email": self.email,
            "email_normalized": self.email_normalized,
            "address_line1": self.address_line1,
            "address_line2": self.address_line2,
            "city": self.city,
            "state": self.state,
            "zip_code": self.zip_code,
            "property_type": self.property_type,
            "lead_source": self.lead_source,
            "creation_date": self.creation_date,
            "last_contact_date": self.last_contact_date,
            "last_contact_outcome": self.last_contact_outcome,
            "lead_status": self.lead_status,
            "assigned_manager": self.assigned_manager,
            "motivation": self.motivation,
            "asking_price": self.asking_price,
            "estimated_value": self.estimated_value,
            "repair_estimate": self.repair_estimate,
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "square_footage": self.square_footage,
            "appointment_date": self.appointment_date,
            "follow_up_date": self.follow_up_date,
            "notes": self.notes,
            "do_not_contact": self.do_not_contact,
            "external_ref": self.external_ref,
            "address_key": self.address_key,
            "warnings": self.warnings,
            "errors": self.errors,
            "original": self.original,
        }


def _truthy(value: Any) -> bool:
    if is_empty(value):
        return False
    return str(value).strip().lower() in {"yes", "y", "true", "1", "dnc", "do not contact", "do-not-contact"}


def normalize_row(row: dict[str, Any], mapping: dict[str, str], row_number: int) -> NormalizedRow:
    def value_for(target: str) -> Any:
        header = mapping.get(target)
        if not header:
            return None
        return row.get(header)

    result = NormalizedRow(row_number=row_number, original={k: (str(v) if v is not None else None) for k, v in row.items()})

    first, last = split_full_name(value_for("full_name"), value_for("first_name"), value_for("last_name"))
    result.first_name = first
    result.last_name = last
    result.full_name = clean_str(value_for("full_name")) or " ".join(p for p in (first, last) if p)

    phone_norm, phone_display, phone_warnings = normalize_phone(value_for("phone"))
    result.phone = clean_str(value_for("phone"))
    result.phone_normalized = phone_norm
    result.phone_display = phone_display
    result.warnings.extend(phone_warnings)
    phone2_norm, _, _ = normalize_phone(value_for("phone2"))
    result.phone2 = phone2_norm

    result.email = clean_str(value_for("email"))
    result.email_normalized = normalize_email(value_for("email"))
    if result.email and not result.email_normalized:
        result.warnings.append(f"Email '{result.email}' does not look valid and was ignored for matching")

    # Address: a single combined field may include ", City, ST zip"
    address_raw = clean_str(value_for("address_line1"))
    city = clean_str(value_for("city"))
    state, state_warnings = normalize_state(value_for("state"))
    zip_code = clean_str(value_for("zip_code"))
    result.warnings.extend(state_warnings)
    if address_raw and (not city or not state or not zip_code):
        parsed_city, parsed_state, parsed_zip = _split_address_tail(address_raw)
        city = city or parsed_city
        state = state or parsed_state
        zip_code = zip_code or parsed_zip
        if parsed_city or parsed_state or parsed_zip:
            address_raw = address_raw.split(",")[0].strip()
    result.address_line1 = address_raw
    result.address_line2 = clean_str(value_for("address_line2"))
    result.city = city
    result.state = state
    result.zip_code = zip_code
    result.address_key = address_key(result.address_line1, result.city, result.state, result.zip_code)

    result.property_type = clean_str(value_for("property_type"))
    result.lead_source = clean_str(value_for("lead_source"))

    created, warns, ambiguous = parse_date_flexible(value_for("creation_date"), "creation_date")
    result.creation_date = created.isoformat() if created else None
    result.warnings.extend(warns)
    if ambiguous:
        result.warnings.append("Creation date was ambiguous — please verify")

    last_contact, warns, _a = parse_datetime_flexible(value_for("last_contact_date"), "last_contact_date")
    result.last_contact_date = last_contact.isoformat() if last_contact else None
    result.warnings.extend(warns)
    result.last_contact_outcome = clean_str(value_for("last_contact_outcome"))
    result.lead_status = clean_str(value_for("lead_status"))
    result.assigned_manager = clean_str(value_for("assigned_manager"))
    result.motivation = clean_str(value_for("motivation"))

    for target, attr in (
        ("asking_price", "asking_price"),
        ("estimated_value", "estimated_value"),
        ("repair_estimate", "repair_estimate"),
    ):
        number, warns = normalize_money(value_for(target))
        setattr(result, attr, number)
        result.warnings.extend(warns)

    # Beds / baths / sqft: one cell often carries a compound description
    # ('4 & 2', '3 beds 3 baths 2,007 sqft') — extract first, fall back to a
    # plain number, and cross-fill the other fields when only one cell was filled.
    own: dict[str, tuple[Optional[float], Optional[float], Optional[float]]] = {}
    detail_warns: list[str] = []
    for target in ("bedrooms", "bathrooms", "square_footage"):
        beds_n, baths_n, sqft_n, warns = extract_property_details(value_for(target))
        own[target] = (beds_n, baths_n, sqft_n)
        detail_warns.extend(warns)
    for target, index, raw in (
        ("bedrooms", 0, value_for("bedrooms")),
        ("bathrooms", 1, value_for("bathrooms")),
        ("square_footage", 2, value_for("square_footage")),
    ):
        value = own[target][index]
        if value is None:
            value, warns = normalize_money(raw)
            result.warnings.extend(warns)
        if value is None:
            for src in ("bedrooms", "bathrooms", "square_footage"):
                candidate = own[src][index]
                if candidate is not None:
                    value = candidate
                    break
        setattr(result, target, value)
    result.warnings.extend(dict.fromkeys(detail_warns))

    appt, warns, _a = parse_datetime_flexible(value_for("appointment_date"), "appointment_date")
    result.appointment_date = appt.isoformat() if appt else None
    result.warnings.extend(warns)
    follow_up, warns, _a = parse_datetime_flexible(value_for("follow_up_date"), "follow_up_date")
    result.follow_up_date = follow_up.isoformat() if follow_up else None
    result.warnings.extend(warns)

    result.notes = clean_str(value_for("notes"))
    result.do_not_contact = _truthy(value_for("do_not_contact"))
    result.external_ref = clean_str(value_for("external_ref"))

    # Validation: reject only rows with nothing to identify them. A property
    # address alone is a usable lead (contact_status stays `never`); missing
    # contact info is reported as a warning, never invented.
    has_phone = bool(result.phone_normalized)
    has_email = bool(result.email_normalized)
    has_name = bool(result.first_name or result.last_name)
    has_address = bool(result.address_line1)
    if not (has_phone or has_email or has_name or has_address):
        result.errors.append("Row has no phone, email, seller name or property address — nothing to import")
    elif not (has_phone or has_email):
        if has_name and has_address:
            result.warnings.append("No phone or email — matching will rely on name + address")
        elif has_name:
            result.warnings.append("No phone or email — matching will rely on the seller name alone")
        else:
            result.warnings.append(
                "Address-only row — no seller contact info (kept locally; REsimpli push needs a phone)"
            )
    if result.do_not_contact:
        result.warnings.append("Marked Do Not Contact — outreach will be blocked")

    return result


def _split_address_tail(address: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    parts = [p.strip() for p in address.split(",")]
    city = state = zip_code = None
    if len(parts) >= 2:
        tail = parts[-1]
        import re

        m = re.search(r"([A-Z]{2})?\s*(\d{5}(?:-\d{4})?)$", tail, flags=re.I)
        if m:
            state = m.group(1).upper() if m.group(1) else None
            zip_code = m.group(2)
            tail = tail[: m.start()].strip()
        elif re.fullmatch(r"\d{5}(?:-\d{4})?", parts[-1]):
            zip_code = parts[-1]
            tail = parts[-2] if len(parts) >= 2 else None
            m2 = re.search(r"([A-Z]{2})\s*$", tail or "", flags=re.I)
            if m2:
                state = m2.group(1).upper()
                tail = tail[: m2.start()].strip()
        if tail:
            city = tail
        elif len(parts) >= 2:
            city = parts[-2]
    return city, state, zip_code


# --------------------------------------------------------------------------- #
# Preview
# --------------------------------------------------------------------------- #
def preview_import(
    db: Session,
    path: Path,
    filename: str,
    mapping: dict[str, str],
    sheet_name: Optional[str] = None,
) -> dict[str, Any]:
    inspection = inspect_file(path, filename, sheet_name)
    if inspection.error:
        raise ValueError(inspection.error)

    existing_batch = (
        db.query(ImportBatch)
        .filter(ImportBatch.checksum == inspection.checksum, ImportBatch.status == "committed")
        .order_by(ImportBatch.created_at.desc())
        .first()
    )

    batch = ImportBatch(
        filename=filename,
        checksum=inspection.checksum,
        sheet_name=inspection.active_sheet,
        status="preview",
    )
    db.add(batch)
    db.flush()

    effective_mapping = {k: v for k, v in (mapping or {}).items() if v}
    headers, records, _sheets = _read_rows(path, sheet_name)
    seen = FileSeenIndex()
    counts = {"new": 0, "likely_duplicate": 0, "exact_duplicate": 0, "same_seller_diff_property": 0, "same_property_diff_seller": 0, "existing_resimpli": 0, "rejected": 0}
    missing = {"phone": 0, "email": 0, "address": 0, "name": 0}
    warning_count = 0

    for index, raw in enumerate(records, start=2):  # row 1 = headers
        row = normalize_row(raw, effective_mapping, index)
        if not row.phone_normalized:
            missing["phone"] += 1
        if not row.email_normalized:
            missing["email"] += 1
        if not row.address_line1:
            missing["address"] += 1
        if not (row.full_name or (row.first_name and row.last_name)):
            missing["name"] += 1
        if row.errors:
            status = "rejected"
            reason = "; ".join(row.errors)
        else:
            dup, dup_reason = seen.check(Candidate(
                external_id=row.external_ref,
                phone_normalized=row.phone_normalized,
                email_normalized=row.email_normalized,
                address_key=row.address_key,
            ), index)
            if dup:
                status = "exact_duplicate"
                reason = f"Duplicate within file: {dup_reason}"
            else:
                seen.add(Candidate(
                    external_id=row.external_ref,
                    phone_normalized=row.phone_normalized,
                    email_normalized=row.email_normalized,
                    address_key=row.address_key,
                ), index)
                match = find_matches(db, Candidate(
                    external_id=row.external_ref,
                    phone_normalized=row.phone_normalized,
                    email_normalized=row.email_normalized,
                    address_key=row.address_key,
                    first_name=row.first_name,
                    last_name=row.last_name,
                ))
                status = match.status
                reason = match.reason
                if match.matched_details:
                    reason += " — " + "; ".join(
                        f"{d['name']} ({d.get('phone') or d.get('email') or d.get('address') or 'no contact'})" for d in match.matched_details[:3]
                    )
                if row.external_ref and status == NEW:
                    # An explicit REsimpli id that is not in the local DB is still
                    # treated as an existing CRM record for reporting purposes.
                    reason = "REsimpli id supplied but not found locally"
                    row.warnings.append(reason)
        counts[status] = counts.get(status, 0) + 1
        warning_count += len(row.warnings)
        db.add(
            ImportRecord(
                batch_id=batch.id,
                row_number=index,
                status=status,
                reason=reason,
                payload=row.to_payload(),
                warnings=row.warnings,
                external_ref=row.external_ref,
            )
        )

    batch.total_rows = len(records)
    batch.new_count = counts.get("new", 0)
    batch.duplicate_count = sum(counts.get(k, 0) for k in ("exact_duplicate", "likely_duplicate", "same_seller_diff_property", "same_property_diff_seller", "existing_resimpli"))
    batch.rejected_count = counts.get("rejected", 0)
    batch.warning_count = warning_count
    db.commit()
    audit(db, "import.preview", "import_batch", batch.id, {"filename": filename, "rows": len(records), "new": counts.get("new", 0)}, commit=True)

    return {
        "batch": _serialize_batch(db, batch),
        "counts": counts,
        "missing": missing,
        "already_imported_file": bool(existing_batch),
        "previous_batch_id": existing_batch.id if existing_batch else None,
        "sample": [
            {
                "row_number": r.row_number,
                "status": r.status,
                "reason": r.reason,
                "warnings": r.warnings or [],
                "name": (r.payload or {}).get("full_name"),
                "phone": (r.payload or {}).get("phone_display") or (r.payload or {}).get("phone"),
                "email": (r.payload or {}).get("email"),
                "address": (r.payload or {}).get("address_line1"),
            }
            for r in db.query(ImportRecord).filter(ImportRecord.batch_id == batch.id).limit(25).all()
        ],
    }


# --------------------------------------------------------------------------- #
# Commit
# --------------------------------------------------------------------------- #
def commit_import(
    db: Session,
    batch_id: str,
    record_ids: Optional[list[str]] = None,
    skip_duplicates: bool = True,
    external: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Write the selected preview records into the local database.

    `external` (optional) enables creation inside REsimpli through the
    documented `/lead/add` endpoint. It requires the account-specific
    pipeline/status/market/campaign ObjectIds, which only the account owner can
    supply — see the Import Center UI.
    """
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise ValueError("Import batch not found")
    if batch.status == "committed":
        raise ValueError("This batch has already been committed")

    query = db.query(ImportRecord).filter(ImportRecord.batch_id == batch_id)
    if record_ids:
        query = query.filter(ImportRecord.id.in_(record_ids))
    records = query.all()

    from app.services.resimpli_client import ResimpliAuthError, ResimpliError
    from app.services.sync_service import get_client, is_mock

    client = None
    external_enabled = bool(external and external.get("enabled"))
    external_ids: dict[str, str] = {}
    if external_enabled:
        if is_mock() and not (external or {}).get("force_mock"):
            raise ValueError(
                "REsimpli API key is not configured — external lead creation is unavailable. "
                "Import locally and export the REsimpli CSV instead."
            )
        external_ids = resolve_external_ids(db, external)
        missing_ids = [k for k in EXTERNAL_KEYS if not external_ids.get(k)]
        if missing_ids:
            raise ValueError(
                "External creation requires account-specific REsimpli ids: " + ", ".join(missing_ids)
            )
        client = get_client()

    imported = failed = skipped = 0
    external_pushed = external_failed = external_no_phone = 0
    auth_dead = False
    errors: list[str] = []
    external_errors: list[str] = []
    for record in records:
        if record.status == "rejected":
            skipped += 1
            continue
        if skip_duplicates and record.status in {"exact_duplicate", "likely_duplicate", "existing_resimpli", "same_seller_diff_property", "same_property_diff_seller"}:
            record.status = "skipped"
            record.reason = (record.reason or "") + " — skipped as duplicate"
            skipped += 1
            continue
        payload = record.payload or {}
        try:
            lead = _create_lead_from_payload(db, payload, batch)
            record.lead_id = lead.id
            if external_enabled and client is not None:
                if auth_dead:
                    external_failed += 1
                    external_errors.append(
                        f"Row {record.row_number}: skipped after an earlier authentication failure"
                    )
                    record.reason = (record.reason or "") + " — created locally; REsimpli push skipped (auth failure)"
                elif len("".join(ch for ch in (payload.get("phone_normalized") or "") if ch.isdigit())) < 10:
                    # /lead/add requires a phone number — keep the lead local instead.
                    external_no_phone += 1
                    record.reason = (record.reason or "") + " — created locally; REsimpli push skipped (no phone)"
                else:
                    try:
                        body = _build_external_lead_body(payload, external_ids)
                        response = client.add_lead(body)
                        data = response.get("data") if isinstance(response, dict) else None
                        external_id = None
                        if isinstance(data, dict):
                            external_id = data.get("_id") or data.get("id") or data.get("leadId")
                        if external_id:
                            lead.external_id = str(external_id)
                            lead.last_synced_at = datetime.utcnow()
                        record.reason = (record.reason or "") + f" — created in REsimpli ({external_id})"
                        external_pushed += 1
                    except ResimpliAuthError as exc:
                        # Keep the local lead: the report shows the push failure.
                        auth_dead = True
                        external_failed += 1
                        external_errors.append(
                            f"Row {record.row_number}: {exc} — further REsimpli pushes stopped"
                        )
                        record.error = str(exc)
                        record.reason = (record.reason or "") + " — created locally; REsimpli push failed (auth)"
                    except ResimpliError as exc:
                        # Do not blindly retry writes: surface for manual review.
                        external_failed += 1
                        external_errors.append(f"Row {record.row_number}: {exc} (verify in REsimpli before retrying)")
                        record.error = str(exc)
                        record.reason = (record.reason or "") + " — created locally; REsimpli push failed"
            record.status = "imported"
            imported += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            record.status = "failed"
            record.error = f"{exc.__class__.__name__}: {exc}"
            failed += 1
            errors.append(f"Row {record.row_number}: {exc}")

    batch.imported_count = imported
    batch.failed_count = failed
    batch.skipped_count = skipped
    batch.status = "committed" if failed == 0 else "partially_committed"
    batch.finished_at = datetime.utcnow()
    db.commit()
    audit(
        db,
        "import.commit",
        "import_batch",
        batch.id,
        {
            "imported": imported,
            "failed": failed,
            "skipped": skipped,
            "external": external_enabled,
            "external_pushed": external_pushed,
            "external_failed": external_failed,
            "external_no_phone": external_no_phone,
        },
    )
    return {
        "batch": _serialize_batch(db, batch),
        "imported": imported,
        "failed": failed,
        "skipped": skipped,
        "errors": errors[:25],
        "external_enabled": external_enabled,
        "external": {
            "enabled": external_enabled,
            "pushed": external_pushed,
            "failed": external_failed,
            "skipped_no_phone": external_no_phone,
            "errors": external_errors[:25],
            "ids": external_ids or None,
        },
    }


def _create_lead_from_payload(db: Session, payload: dict[str, Any], batch: ImportBatch) -> Lead:
    external_ref = payload.get("external_ref")
    lead: Optional[Lead] = None
    if external_ref:
        lead = db.query(Lead).filter(Lead.external_id == str(external_ref)).first()
    if lead is None and payload.get("phone_normalized"):
        lead = db.query(Lead).filter(Lead.phone_normalized == payload["phone_normalized"]).first()
    if lead is None and payload.get("email_normalized"):
        lead = db.query(Lead).filter(Lead.email_normalized == payload["email_normalized"]).first()

    created = lead is None
    if lead is None:
        lead = Lead(origin="import", import_batch_id=batch.id)
        db.add(lead)

    lead.external_id = str(external_ref) if external_ref else lead.external_id
    lead.first_name = payload.get("first_name") or lead.first_name
    lead.last_name = payload.get("last_name") or lead.last_name
    lead.full_name = payload.get("full_name") or lead.full_name or " ".join(
        p for p in (payload.get("first_name"), payload.get("last_name")) if p
    )
    if payload.get("phone_display"):
        lead.primary_phone = payload["phone_display"]
    elif payload.get("phone"):
        lead.primary_phone = payload["phone"]
    lead.phone_normalized = payload.get("phone_normalized") or lead.phone_normalized
    lead.email = payload.get("email") or lead.email
    lead.email_normalized = payload.get("email_normalized") or lead.email_normalized
    lead.lead_source = payload.get("lead_source") or lead.lead_source
    lead.assigned_manager = payload.get("assigned_manager") or lead.assigned_manager
    lead.do_not_contact = bool(payload.get("do_not_contact")) or lead.do_not_contact
    if payload.get("lead_status"):
        lead.source_status = payload["lead_status"]
    if payload.get("creation_date"):
        try:
            lead.original_creation_date = datetime.fromisoformat(payload["creation_date"]).date()
        except ValueError:
            pass
    if payload.get("last_contact_date"):
        try:
            lead.last_contact_at = datetime.fromisoformat(payload["last_contact_date"])
        except ValueError:
            pass
    if payload.get("notes"):
        lead.notes = payload["notes"]

    lead.import_batch_id = batch.id

    if payload.get("address_line1"):
        prop = link_property(
            db,
            lead,
            address_line1=payload.get("address_line1"),
            city=payload.get("city"),
            state=payload.get("state"),
            zip_code=payload.get("zip_code"),
            property_type=payload.get("property_type"),
            replace=created,
        )
        prop.asking_price = payload.get("asking_price") or prop.asking_price
        prop.estimated_value = payload.get("estimated_value") or prop.estimated_value
        prop.repair_estimate = payload.get("repair_estimate") or prop.repair_estimate
        prop.bedrooms = payload.get("bedrooms") or prop.bedrooms
        prop.bathrooms = payload.get("bathrooms") or prop.bathrooms
        prop.square_footage = payload.get("square_footage") or prop.square_footage

    db.flush()

    # Stage mapping happens after flush so the lead has an id
    from app.services.pipeline import map_stage
    from app.services.settings_service import stage_mapping

    if payload.get("lead_status"):
        lead.pipeline_stage = map_stage(payload["lead_status"], stage_mapping(db))

    if payload.get("last_contact_outcome"):
        from app.services.pipeline import infer_outcome_from_text

        outcome = infer_outcome_from_text(payload["last_contact_outcome"]) or "other"
        lead.contact_status = outcome
        db.add(
            ActivityPlaceholder(lead_id=lead.id, outcome=outcome, occurred_at=lead.last_contact_at, summary=payload["last_contact_outcome"], source="import")
        )

    if payload.get("follow_up_date"):
        try:
            due = datetime.fromisoformat(payload["follow_up_date"])
            db.add(
                Followup(
                    lead_id=lead.id,
                    due_at=due,
                    reason="Imported follow-up date",
                    suggested_next_action="Contact the seller per the imported schedule",
                    creation_source="import",
                    priority=3,
                    status="open",
                )
            )
        except ValueError:
            pass

    if payload.get("appointment_date"):
        try:
            when = datetime.fromisoformat(payload["appointment_date"])
            db.add(
                Appointment(
                    lead_id=lead.id,
                    scheduled_at=when,
                    status="scheduled",
                    notes="Imported appointment",
                    source="import",
                )
            )
        except ValueError:
            pass

    refresh_lead_rollups(db, lead)
    db.flush()
    return lead


def ActivityPlaceholder(**kwargs: Any):  # noqa: N802 - thin alias kept local to this module
    from app.models import Activity

    occurred = kwargs.pop("occurred_at", None) or datetime.utcnow()
    return Activity(occurred_at=occurred, **kwargs)


def _build_external_lead_body(payload: dict[str, Any], external: dict[str, Any]) -> dict[str, Any]:
    """Build the documented `/lead/add` request body.

    Required per the official endpoint catalogue: contactDetails.firstName,
    contactDetails.phoneNumbers[].phoneNumber, propertyType (land|residential),
    marketingCampignId, marketId, pipelineId, mainStatusId.
    """
    phone_digits = "".join(ch for ch in (payload.get("phone_normalized") or "") if ch.isdigit())
    body: dict[str, Any] = {
        "contactDetails": {
            "firstName": payload.get("first_name") or payload.get("full_name") or "Unknown",
            "phoneNumbers": [{"phoneNumber": phone_digits, "isPrimary": True}],
        },
        "propertyType": (payload.get("property_type") or external.get("propertyType") or "residential").lower(),
        "marketingCampignId": external["marketingCampignId"],
        "marketId": external["marketId"],
        "pipelineId": external["pipelineId"],
        "mainStatusId": external["mainStatusId"],
    }
    if payload.get("last_name"):
        body["contactDetails"]["lastName"] = payload["last_name"]
    if payload.get("email_normalized"):
        body["contactDetails"]["emails"] = [{"email": payload["email_normalized"], "isPrimary": True}]
    address_parts = [p for p in (payload.get("address_line1"), payload.get("address_line2")) if p]
    if address_parts:
        tail = ", ".join(p for p in (payload.get("city"), payload.get("state")) if p)
        zip_code = payload.get("zip_code") or ""
        address = ", ".join([", ".join(address_parts)] + ([tail] if tail else []) + ([zip_code] if zip_code else []))
        body["address"] = address
    if payload.get("creation_date"):
        body["leadCreated"] = payload["creation_date"][:10]
    if payload.get("do_not_contact"):
        body["contactDetails"]["doNotCall"] = True
        body["contactDetails"]["doNotText"] = True
    if payload.get("notes"):
        body["comment"] = str(payload["notes"])[:500]
    return body


# --------------------------------------------------------------------------- #
# Serialisation / exports
# --------------------------------------------------------------------------- #
def _serialize_batch(db: Session, batch: ImportBatch) -> dict[str, Any]:
    return {
        "id": batch.id,
        "filename": batch.filename,
        "sheet_name": batch.sheet_name,
        "checksum": batch.checksum,
        "status": batch.status,
        "total_rows": batch.total_rows,
        "new_count": batch.new_count,
        "duplicate_count": batch.duplicate_count,
        "warning_count": batch.warning_count,
        "rejected_count": batch.rejected_count,
        "imported_count": batch.imported_count,
        "failed_count": batch.failed_count,
        "error": batch.error,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "finished_at": batch.finished_at.isoformat() if batch.finished_at else None,
        "record_status_counts": _record_status_counts(db, batch.id),
    }


def _record_status_counts(db: Session, batch_id: str) -> dict[str, int]:
    from sqlalchemy import func

    rows = (
        db.query(ImportRecord.status, func.count(ImportRecord.id))
        .filter(ImportRecord.batch_id == batch_id)
        .group_by(ImportRecord.status)
        .all()
    )
    return {status: count for status, count in rows}


def list_batches(db: Session, limit: int = 50) -> list[dict[str, Any]]:
    batches = db.query(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(limit).all()
    return [_serialize_batch(db, b) for b in batches]


def get_batch(db: Session, batch_id: str, include_records: bool = False, limit: int = 200) -> dict[str, Any]:
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise ValueError("Import batch not found")
    data = _serialize_batch(db, batch)
    if include_records:
        records = (
            db.query(ImportRecord).filter(ImportRecord.batch_id == batch_id).order_by(ImportRecord.row_number).limit(limit).all()
        )
        data["records"] = [
            {
                "id": r.id,
                "row_number": r.row_number,
                "status": r.status,
                "reason": r.reason,
                "warnings": r.warnings or [],
                "error": r.error,
                "lead_id": r.lead_id,
                "external_ref": r.external_ref,
                "name": (r.payload or {}).get("full_name"),
                "phone": (r.payload or {}).get("phone_display") or (r.payload or {}).get("phone"),
                "email": (r.payload or {}).get("email"),
                "address": (r.payload or {}).get("address_line1"),
            }
            for r in records
        ]
    return data


def rejected_records_csv(db: Session, batch_id: str) -> str:
    records = db.query(ImportRecord).filter(ImportRecord.batch_id == batch_id, ImportRecord.status.in_(["rejected", "failed"])).all()
    headers = ["row_number", "status", "reason", "error", "name", "phone", "email", "address", "original_json"]
    rows = []
    for r in records:
        p = r.payload or {}
        rows.append(
            [
                r.row_number,
                r.status,
                r.reason,
                r.error,
                p.get("full_name"),
                p.get("phone_display") or p.get("phone"),
                p.get("email"),
                p.get("address_line1"),
                json.dumps(p.get("original") or {}, ensure_ascii=False),
            ]
        )
    return rows_to_csv(headers, rows)


def resimpli_template_csv(db: Session, batch_id: str) -> str:
    """REsimpli-compatible CSV fallback for the documented `/lead/add` fields."""
    records = (
        db.query(ImportRecord)
        .filter(ImportRecord.batch_id == batch_id, ImportRecord.status.in_(["new", "imported", "likely_duplicate"]))
        .all()
    )
    headers = [
        "firstName", "lastName", "phoneNumber", "email", "address", "propertyType",
        "leadSource", "leadCreated", "comment", "doNotCall",
    ]
    rows = []
    for r in records:
        p = r.payload or {}
        rows.append(
            [
                p.get("first_name") or "",
                p.get("last_name") or "",
                (p.get("phone_normalized") or "").replace("+", ""),
                p.get("email_normalized") or "",
                p.get("address_line1") or "",
                (p.get("property_type") or "residential").lower(),
                p.get("lead_source") or "",
                (p.get("creation_date") or "")[:10],
                p.get("notes") or "",
                "true" if p.get("do_not_contact") else "false",
            ]
        )
    return rows_to_csv(headers, rows)


# --------------------------------------------------------------------------- #
# Mapping templates
# --------------------------------------------------------------------------- #
def save_template(db: Session, name: str, mapping: dict[str, str]) -> dict[str, Any]:
    row = db.query(MappingTemplate).filter(MappingTemplate.name == name).first()
    if row is None:
        row = MappingTemplate(name=name, columns=mapping)
        db.add(row)
    else:
        row.columns = mapping
    db.commit()
    return {"id": row.id, "name": row.name, "columns": row.columns}


def list_templates(db: Session) -> list[dict[str, Any]]:
    return [{"id": t.id, "name": t.name, "columns": t.columns, "created_at": t.created_at.isoformat()} for t in db.query(MappingTemplate).all()]


def delete_template(db: Session, template_id: str) -> None:
    row = db.get(MappingTemplate, template_id)
    if row:
        db.delete(row)
        db.commit()


def upload_path(filename: str) -> tuple[Path, str]:
    """Persist an uploaded file and return (path, checksum)."""
    import secrets

    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    safe_name = "".join(ch for ch in filename if ch.isalnum() or ch in "._- ").strip() or "upload.csv"
    path = Path(settings.upload_dir) / f"{secrets.token_hex(8)}_{safe_name}"
    return path, safe_name


def leads_created_by_batch(db: Session, batch_id: str) -> list[dict[str, Any]]:
    leads = db.query(Lead).filter(Lead.import_batch_id == batch_id).all()
    return [serialize_lead(lead, db) for lead in leads]
