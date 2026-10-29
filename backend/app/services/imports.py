import csv
import hashlib
import io
import zipfile
import threading
from collections import defaultdict
from pathlib import Path
from datetime import datetime
from openpyxl import load_workbook
from sqlalchemy import select
from ..models import (
    Lead,
    LeadPhone,
    Property,
    LeadProperty,
    Activity,
    Followup,
    Appointment,
    ImportBatch,
    ImportRow,
    MappingTemplate,
    AuditLog,
    StageHistory,
)
from ..db import utcnow
from ..seed import record_source_status, stage_mapping
from .normalization import normalize_record, guess_mapping, detect_profile, FIELDS, normalize_phone
from .property_facts import EXTRA_FACTS
from .leads import CONTACTED, ATTEMPTED, source_date_is_connection


def validate_headers(headers, name):
    if not headers or len(headers) > 300 or any(not h.strip() for h in headers):
        raise ValueError(f"{name}: use 1–300 non-empty column headers")
    if len(headers) != len(set(headers)):
        raise ValueError(f"{name}: duplicate headers must be renamed")
    if any(len(h) > 300 for h in headers):
        raise ValueError("Column header exceeds 300 characters")


def inspect_file(content, filename, max_rows):
    suffix = Path(filename).suffix.lower()
    sheets = {}
    if suffix == ".csv":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("cp1252")
        try:
            dialect = csv.Sniffer().sniff(text[:16000], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text), dialect)
        headers = next(reader, [])
        validate_headers(headers, "CSV")
        rows = []
        for number, values in enumerate(reader, 2):
            if not any(str(v).strip() for v in values):
                continue
            if len(values) > len(headers):
                raise ValueError(f"CSV row {number} has more columns than its header")
            rows.append((number, dict(zip(headers, values + [""] * (len(headers) - len(values))))))
            if len(rows) > max_rows:
                raise ValueError(f"File exceeds {max_rows} records")
        sheets["CSV"] = (headers, rows)
    elif suffix == ".xlsx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if sum(x.file_size for x in archive.infolist()) > 150_000_000:
                    raise ValueError("Workbook decompressed size exceeds the safety limit")
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
        except (zipfile.BadZipFile, KeyError) as exc:
            raise ValueError("Invalid XLSX file") from exc
        total = 0
        try:
            for ws in wb.worksheets:
                ws.reset_dimensions()  # Ignore inflated/untrusted worksheet dimensions.
                iterator = ws.iter_rows(values_only=True)
                first = next(iterator, [])
                headers = [str(h).strip() if h is not None else "" for h in first]
                # Ignore truly empty trailing columns only.
                while headers and headers[-1] == "":
                    headers.pop()
                if headers:
                    validate_headers(headers, ws.title)
                rows = []
                for number, values in enumerate(iterator, 2):
                    if number > max_rows * 5 + 1:
                        raise ValueError("Workbook contains too many sparse physical rows")
                    if any(v is not None and str(v).strip() for v in values[len(headers) :]):
                        raise ValueError(
                            f"{ws.title}: row {number} has values without a column header; name every populated column"
                        )
                    if not any(v is not None and str(v).strip() for v in values):
                        continue
                    total += 1
                    if total > max_rows:
                        raise ValueError(f"Workbook exceeds {max_rows} records")
                    converted = [v.isoformat() if isinstance(v, datetime) else v for v in values[: len(headers)]]
                    rows.append((number, dict(zip(headers, converted))))
                if headers:
                    sheets[ws.title] = (headers, rows)
        finally:
            wb.close()
    else:
        raise ValueError("Only CSV and XLSX files are supported")
    if not sheets:
        raise ValueError("No non-empty sheets found")
    for name, (headers, _) in sheets.items():
        validate_headers(headers, name)
    return sheets


def upload_batch(db, content, filename, settings, profile: str = "auto"):
    checksum = hashlib.sha256(content).hexdigest()
    existing = db.scalar(select(ImportBatch).where(ImportBatch.checksum == checksum))
    if existing:
        return existing, True
    sheets = inspect_file(content, filename, settings.max_import_rows)
    if profile not in {"auto", "standard", "address_only", "skip_trace_results"}:
        raise ValueError("Choose the standard or Data Syndicate (address-only) profile")
    detected = ""
    if profile == "auto":
        detected = detect_profile(next(iter(sheets.values()))[0]) if sheets else "standard"
        profile = detected
    metadata = {
        name: {"headers": headers, "record_count": len(rows), "suggested_mapping": guess_mapping(headers)}
        for name, (headers, rows) in sheets.items()
    }
    batch = ImportBatch(
        filename=Path(filename).name[:300],
        checksum=checksum,
        sheets=metadata,
        row_count=sum(len(rows) for _, rows in sheets.values()),
        profile=profile,
    )
    db.add(batch)
    db.flush()
    for sheet, (_, rows) in sheets.items():
        db.add_all(
            [
                ImportRow(batch_id=batch.id, sheet=sheet, row_number=number, original=original)
                for number, original in rows
            ]
        )
    db.add(AuditLog(action="import_uploaded", details={"batch_id": batch.id, "rows": batch.row_count}))
    db.commit()
    return batch, False


class DuplicateIndex:
    def __init__(self, db):
        self.external, self.phone, self.email, self.address = (
            {},
            defaultdict(list),
            defaultdict(list),
            defaultdict(list),
        )
        for lead in db.scalars(select(Lead)).all():
            self.add(
                {
                    "lead_id": lead.id,
                    "full_name": lead.full_name,
                    "external_id": lead.external_id,
                    "primary_phone": lead.primary_phone,
                    "email": lead.email,
                    "addresses": [p.normalized_address for p in lead.properties if p.normalized_address],
                }
            )

    def add(self, item):
        if item.get("external_id"):
            self.external[item["external_id"]] = item
        if item.get("primary_phone"):
            self.phone[item["primary_phone"]].append(item)
        if item.get("email"):
            self.email[item["email"]].append(item)
        for address in item.get("addresses", []):
            self.address[address].append(item)

    def match(self, data):
        ext = data.get("external_id")
        if ext and ext in self.external:
            return "existing_resimpli_record", [self.external[ext]]
        people = []
        for key, index in [("primary_phone", self.phone), ("email", self.email)]:
            if data.get(key):
                people += index[data[key]]
        addresses = self.address.get(data.get("normalized_address"), [])

        def dedup(items):
            return list({str(x.get("lead_id") or "row:" + str(x.get("row_id"))): x for x in items}.values())

        people = dedup(people)
        if people:
            exact = [p for p in people if data.get("normalized_address") in p.get("addresses", [])]
            if exact:
                return "exact_duplicate", exact
            if data.get("normalized_address") and any(p.get("addresses") for p in people):
                return "same_seller_different_property", people
            return "likely_duplicate", people
        if addresses:
            return "same_property_different_seller", dedup(addresses)
        return "new_record", []


def preview_batch(db, batch, request, settings):
    if len(request.mapping.values()) != len(set(request.mapping.values())):
        raise ValueError("Map each destination field at most once")
    if not request.sheets or any(s not in batch.sheets for s in request.sheets):
        raise ValueError("Select at least one valid sheet")
    if not request.mapping:
        raise ValueError("Column mapping is required")
    if any(k not in FIELDS for k in request.mapping.values()):
        raise ValueError("Unknown destination field")
    available = set().union(*(set(batch.sheets[s]["headers"]) for s in request.sheets))
    if not set(request.mapping).issubset(available):
        raise ValueError("Mapping refers to a missing source column")
    batch.mapping_config = request.model_dump()
    index = DuplicateIndex(db)
    for row in db.scalars(select(ImportRow).where(ImportRow.batch_id == batch.id).order_by(ImportRow.id)):
        if row.state in {"imported", "linked", "skipped"}:
            continue
        if row.sheet not in request.sheets:
            row.state = "excluded"
            continue
        data, errors, warnings = normalize_record(
            row.original,
            request.mapping,
            settings.app_timezone,
            request.date_order,
            profile=batch.profile or "standard",
        )
        kind, candidates = index.match(data)
        row.normalized, row.errors, row.warnings = data, errors, warnings
        row.duplicate_kind, row.candidates = kind, candidates
        # A re-imported Data Syndicate file is idempotent: the same address is the same
        # lead, and the review step offers an explicit refresh instead of a new record.
        if kind != "new_record" and str(data.get("external_id") or "").startswith("ds:"):
            row.duplicate_kind = "data_syndicate_refresh"
        row.state = "invalid" if errors else "ready"
        row.error = None
        if not errors:
            index.add(
                {
                    "row_id": row.id,
                    "full_name": data.get("full_name"),
                    "external_id": data.get("external_id"),
                    "primary_phone": data.get("primary_phone"),
                    "email": data.get("email"),
                    "addresses": [data["normalized_address"]] if data.get("normalized_address") else [],
                }
            )
    if request.template_name:
        template = db.scalar(select(MappingTemplate).where(MappingTemplate.name == request.template_name))
        if template:
            template.mapping, template.date_order = request.mapping, request.date_order
        else:
            db.add(MappingTemplate(name=request.template_name, mapping=request.mapping, date_order=request.date_order))
    batch.state = "previewed"
    update_counts(db, batch)
    db.commit()
    return batch


def update_counts(db, batch):
    db.flush()
    rows = db.scalars(select(ImportRow).where(ImportRow.batch_id == batch.id)).all()
    batch.counts = {
        "total": len(rows),
        "new": sum(r.duplicate_kind == "new_record" and not r.errors for r in rows),
        "duplicates": sum(r.duplicate_kind not in {"new_record", "unreviewed"} and r.state != "excluded" for r in rows),
        "warnings": sum(bool(r.warnings) for r in rows),
        "invalid": sum(r.state == "invalid" for r in rows),
        "imported": sum(r.state == "imported" for r in rows),
        "linked": sum(r.state == "linked" for r in rows),
        "enriched": sum(any(w.startswith("Filled local missing fields:") for w in r.warnings) for r in rows),
        "skipped": sum(r.state == "skipped" for r in rows),
        "failed": sum(r.state == "failed" for r in rows),
        "excluded": sum(r.state == "excluded" for r in rows),
    }


DS_REFRESH_FIELDS = [
    "score",
    "heat",
    "equity_pct",
    "lead_type",
    "county",
    "priority_tier",
    "priority_rank",
    "dedupe_key",
    "needs_skip_trace",
]
DS_JSON_FIELDS = {
    "ds_flags": "flags",
    "ds_flags_raw": "flags_raw",
    "ds_extra_flags": "extra_flags",
    "ds_compatible_offers": "compatible_offers",
}


def update_data_syndicate_lead(db, lead, data, batch_id):
    """Refresh vendor fields on a re-import without touching anything Jason edited.

    Rules: never create a second lead, never overwrite a field listed in
    ``user_edited_fields``, never blank a field because the new file left it empty,
    and never touch a name/phone that came from a skip trace.
    """
    if not str(lead.external_id or "").startswith("ds:"):
        raise ValueError("Only Data Syndicate leads can be refreshed from a re-import")
    edited = set(lead.user_edited_fields or [])
    changed = []
    for field in DS_REFRESH_FIELDS:
        if field in edited:
            continue
        incoming = data.get(field)
        if incoming is None:
            continue
        if getattr(lead, field) != incoming:
            setattr(lead, field, incoming)
            changed.append(field)
    for column, key in DS_JSON_FIELDS.items():
        if column in edited:
            continue
        incoming = data.get(key)
        if incoming in (None, [], {}):
            continue
        if getattr(lead, column) != incoming:
            setattr(lead, column, incoming)
            changed.append(column)
    recorded = _dt(data.get("recorded_date"))
    if recorded and lead.recorded_date != recorded:
        lead.recorded_date = recorded
        changed.append("recorded_date")
    lead.import_batch_id = str(batch_id)
    attach_property(db, lead, data, {"batch_id": batch_id, "refreshed": True}, update_from_source=True)
    db.add(
        AuditLog(
            lead_id=lead.id,
            action="data_syndicate_refreshed",
            details={"batch_id": batch_id, "changed": changed, "user_edited_fields": sorted(edited)},
        )
    )
    return changed


PROPERTY_FIELDS = [
    "street_address",
    "city",
    "state",
    "zip_code",
    "normalized_address",
    "property_type",
    "bedrooms",
    "bathrooms",
    "square_feet",
    "year_built",
    "asking_price",
    "estimated_value",
    "repair_estimate",
]


def attach_property(db, lead, data, metadata=None, update_from_source=False):
    if not data.get("street_address"):
        return None
    prop = None
    external_id = data.get("external_property_id")
    if external_id:
        prop = db.scalar(select(Property).where(Property.external_id == external_id))
    # Conservative local matching: never compare a street-only string across unrelated towns.
    if (
        not prop
        and data.get("normalized_address")
        and (data.get("zip_code") or (data.get("city") and data.get("state")))
    ):
        candidates = db.scalars(select(Property).where(Property.normalized_address == data["normalized_address"])).all()
        if len(candidates) == 1 and not (
            external_id and candidates[0].external_id and candidates[0].external_id != external_id
        ):
            prop = candidates[0]
    if not prop:
        prop = Property(
            external_id=external_id, **{k: data.get(k) for k in PROPERTY_FIELDS}, property_metadata=metadata or {}
        )
        db.add(prop)
        db.flush()
    elif update_from_source:
        changes = list(prop.property_metadata.get("source_changes", []))
        for field in PROPERTY_FIELDS:
            incoming = data.get(field)
            previous = getattr(prop, field)
            if incoming is not None and incoming != previous:
                if previous is not None:
                    changes.append(
                        {
                            "field": field,
                            "previous": previous,
                            "incoming": incoming,
                            "observed_at": utcnow().isoformat(),
                        }
                    )
                setattr(prop, field, incoming)
        if external_id and not prop.external_id:
            prop.external_id = external_id
        prop.property_metadata = {**prop.property_metadata, **(metadata or {}), "source_changes": changes[-100:]}
    extras = {key: data[key] for key in EXTRA_FACTS if data.get(key) is not None}
    if extras:
        stored = dict(prop.property_metadata.get("facts", {}))
        for key, value in extras.items():
            if update_from_source or key not in stored:
                stored[key] = value
        prop.property_metadata = {
            **prop.property_metadata,
            "facts": stored,
            "fact_source": (metadata or {}).get("source", "reviewed import"),
        }
    if data.get("_value_sources"):
        prop.property_metadata = {
            **prop.property_metadata,
            "value_source_labels": {**prop.property_metadata.get("value_source_labels", {}), **data["_value_sources"]},
        }
    if not db.get(LeadProperty, (lead.id, prop.id)):
        db.add(LeadProperty(lead_id=lead.id, property_id=prop.id, relationship_metadata=metadata or {}))
    return prop


def create_local_lead(db, data, original, batch_id=None, source_kind="import"):
    stage = stage_mapping(db, data.get("source_status"))
    # A CSV carries the same status titles as the CRM, so they belong in the same table.
    record_source_status(db, data.get("source_status"))
    keys = [
        "external_id",
        "first_name",
        "last_name",
        "full_name",
        "primary_phone",
        "primary_phone_type",
        "phone2",
        "phone2_type",
        "phone3",
        "phone3_type",
        "email",
        "lead_source",
        "source_status",
        "assigned_manager",
        "source_do_not_contact",
        "county",
        "lead_type",
        "score",
        "heat",
        "equity_pct",
        "priority_tier",
        "priority_rank",
        "dedupe_key",
        "needs_skip_trace",
    ]
    lead = Lead(
        **{k: (data.get(k) or "") if k == "full_name" else data.get(k) for k in keys},
        stage_code=stage,
        source_kind=source_kind,
        original_created_at=_dt(data.get("original_created_at")),
        last_contact_at=_dt(data.get("last_contact_at"))
        if source_date_is_connection(data.get("contact_outcome"))
        else None,
        contact_outcome=data.get("contact_outcome"),
        source_data={"original": original, "normalized": data, "batch_id": batch_id},
        recorded_date=_dt(data.get("recorded_date")),
        ds_flags=data.get("flags") or data.get("ds_flags") or {},
        ds_flags_raw=data.get("flags_raw"),
        ds_extra_flags=data.get("extra_flags") or [],
        ds_compatible_offers=data.get("compatible_offers") or [],
        outreach_mode=data.get("outreach_mode") or "relationship",
        import_batch_id=str(batch_id) if batch_id is not None else None,
    )
    try:
        from .compliance import is_in_license, _settings

        lead.in_license = is_in_license(lead, _settings(db).get("licensed_counties"))
    except Exception:
        lead.in_license = True
    if data.get("contact_outcome") in CONTACTED or (
        lead.last_contact_at and source_date_is_connection(data.get("contact_outcome"))
    ):
        lead.contact_status = "contacted"
    elif data.get("contact_outcome") in ATTEMPTED:
        lead.contact_status = "attempted"
    else:
        lead.contact_status = "unknown"
    if data.get("contact_outcome") == "Do Not Contact":
        lead.source_do_not_contact = True
    db.add(lead)
    db.flush()
    # Persist ALL detected phone numbers (not just primary/2/3).
    for pos, ph in enumerate(data.get("phones") or []):
        num = ph.get("number") if isinstance(ph, dict) else ph
        if not num:
            continue
        norm = None
        try:
            norm = normalize_phone(num)
        except Exception:
            norm = None
        db.add(
            LeadPhone(
                lead_id=lead.id,
                phone=str(num),
                phone_normalized=norm,
                phone_type=(ph.get("type") if isinstance(ph, dict) else None),
                is_primary=(pos == 0),
                position=pos,
                source_column=(ph.get("source_column") if isinstance(ph, dict) else None),
            )
        )
    db.add(StageHistory(lead_id=lead.id, to_stage=stage, source=source_kind))
    attach_property(db, lead, data, {"source": source_kind, "batch_id": batch_id})
    if data.get("notes"):
        db.add(
            Activity(
                lead_id=lead.id,
                activity_type="note",
                source=source_kind,
                summary=data["notes"],
                occurred_at=None,
                source_metadata={"batch_id": batch_id, "date_unknown": True},
            )
        )
    if data.get("contact_outcome") or data.get("last_contact_at"):
        db.add(
            Activity(
                lead_id=lead.id,
                activity_type="historical_contact",
                source=source_kind,
                outcome=data.get("contact_outcome"),
                occurred_at=_dt(data.get("last_contact_at")),
                summary="Imported historical contact metadata; no transcript is implied.",
                source_metadata={"batch_id": batch_id},
            )
        )
    if data.get("next_followup_at"):
        due = _dt(data["next_followup_at"])
        lead.next_followup_at = due
        db.add(
            Followup(
                lead_id=lead.id,
                due_at=due,
                reason="Explicit follow-up date from imported source",
                creation_source=source_kind,
                suggested_action="Review source context and company contact restrictions.",
            )
        )
    if data.get("appointment_at"):
        db.add(
            Appointment(
                lead_id=lead.id,
                starts_at=_dt(data["appointment_at"]),
                status="unknown",
                source=source_kind,
                notes="Historical appointment date from import; confirm current status.",
            )
        )
    return lead


def _dt(value):
    return datetime.fromisoformat(value) if value else None


IMPORT_LOCK = threading.Lock()


def approve_batch(db, batch, request):
    if not IMPORT_LOCK.acquire(blocking=False):
        raise ValueError("Another local import is running; retry after it completes")
    try:
        return _approve_batch(db, batch, request)
    finally:
        IMPORT_LOCK.release()


def _approve_batch(db, batch, request):
    if request.confirmation != "IMPORT LOCAL":
        raise ValueError("Type IMPORT LOCAL to explicitly approve local database writes")
    if batch.state not in {"previewed", "partial", "completed"}:
        raise ValueError("Preview and validate the file before importing")
    rows = db.scalars(
        select(ImportRow)
        .where(ImportRow.batch_id == batch.id, ImportRow.id.in_(request.row_ids))
        .order_by(ImportRow.id)
    ).all()
    if len(rows) != len(set(request.row_ids)):
        raise ValueError("Some selected rows do not belong to this batch")
    for row in rows:
        if row.state in {"imported", "linked", "skipped"}:
            continue
        if row.errors or row.state not in {"ready", "failed"}:
            raise ValueError(f"Row {row.row_number}: invalid or not previewed")
        resolution = request.resolutions.get(str(row.id), row.resolution)
        if row.duplicate_kind != "new_record" and resolution not in {"skip", "separate", "link", "update"}:
            raise ValueError(f"Row {row.row_number}: explicitly resolve duplicate candidate first")
        if row.duplicate_kind == "existing_resimpli_record" and resolution == "separate":
            raise ValueError("An existing REsimpli ID cannot be imported as a separate record")
        if row.duplicate_kind == "data_syndicate_refresh" and resolution == "separate":
            raise ValueError("This Data Syndicate address is already a lead; refresh it or skip the row")
    batch.state = "importing"
    db.add(
        AuditLog(action="import_approved", details={"batch_id": batch.id, "rows": len(rows), "destination": "local"})
    )
    db.commit()
    # Per-row atomic commits make interruption safely resumable. Never any external write.
    index = DuplicateIndex(db)
    for row in rows:
        if row.state in {"imported", "linked", "skipped"}:
            continue
        try:
            resolution = request.resolutions.get(str(row.id), row.resolution)
            row.resolution = resolution
            if resolution == "skip":
                row.state = "skipped"
            elif resolution == "update":
                targets = [
                    candidate.get("lead_id")
                    for candidate in row.candidates
                    if candidate.get("lead_id")
                ]
                if len(set(targets)) != 1:
                    raise ValueError("Refresh requires exactly one matched local lead")
                lead = db.get(Lead, targets[0])
                changed = update_data_syndicate_lead(db, lead, row.normalized, batch.id)
                row.lead_id, row.external_id, row.state = lead.id, lead.external_id, "linked"
                row.warnings = list(row.warnings or []) + (
                    ["Refreshed fields: " + ", ".join(changed)] if changed else ["No vendor field changed"]
                )
            elif resolution == "link":
                targets = []
                for candidate in row.candidates:
                    target_id = candidate.get("lead_id")
                    if not target_id and candidate.get("row_id"):
                        previous = db.get(ImportRow, candidate["row_id"])
                        target_id = previous.lead_id if previous else None
                    if target_id:
                        targets.append(target_id)
                if len(set(targets)) != 1:
                    raise ValueError("Link requires exactly one resolved local lead; import/review candidate first")
                lead = db.get(Lead, targets[0])
                if row.duplicate_kind == "same_seller_different_property":
                    attach_property(
                        db, lead, row.normalized, {"approved_import_batch": batch.id, "local_relationship": True}
                    )
                if request.fill_missing:
                    from .research import fill_empty_fields

                    filled = fill_empty_fields(db, lead, row.normalized, {"batch_id": batch.id, "row_id": row.id})
                    row.warnings = list(row.warnings) + (
                        ["Filled local missing fields: " + ", ".join(filled)] if filled else []
                    )
                row.lead_id, row.external_id, row.state = lead.id, lead.external_id, "linked"
                db.add(
                    AuditLog(
                        lead_id=lead.id,
                        action="duplicate_resolved",
                        details={"row_id": row.id, "resolution": "link", "no_crm_write": True},
                    )
                )
            else:
                # Recheck against concurrent/newly imported records, not only an old preview.
                kind, candidates = index.match(row.normalized)
                if kind != "new_record" and resolution != "separate":
                    row.duplicate_kind, row.candidates = kind, candidates
                    raise ValueError("Duplicate appeared since preview; review and explicitly resolve it")
                lead = create_local_lead(db, row.normalized, row.original, batch.id)
                row.lead_id, row.external_id, row.state = lead.id, lead.external_id, "imported"
                db.add(
                    AuditLog(lead_id=lead.id, action="lead_imported", details={"batch_id": batch.id, "row_id": row.id})
                )
                index.add(
                    {
                        "lead_id": lead.id,
                        "full_name": lead.full_name,
                        "external_id": lead.external_id,
                        "primary_phone": lead.primary_phone,
                        "email": lead.email,
                        "addresses": [row.normalized["normalized_address"]]
                        if row.normalized.get("normalized_address")
                        else [],
                    }
                )
            row.error = None
            db.commit()
        except Exception as exc:
            db.rollback()
            row = db.get(ImportRow, row.id)
            row.state = "failed"
            index = DuplicateIndex(db)
            kind, candidates = index.match(row.normalized)
            if kind != "new_record":
                row.duplicate_kind, row.candidates = kind, candidates
            row.error = str(exc) if isinstance(exc, ValueError) else "Local database operation failed; review and retry"
            db.commit()
    update_counts(db, batch)
    unresolved = db.scalar(
        select(ImportRow.id)
        .where(ImportRow.batch_id == batch.id, ImportRow.state.in_(["pending", "ready", "failed"]))
        .limit(1)
    )
    batch.state = "partial" if unresolved else "completed"
    batch.finished_at = utcnow()
    db.commit()
    return batch
