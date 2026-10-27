import asyncio
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Annotated
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, BackgroundTasks, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .config import get_settings, ROOT
from .version import APP_VERSION
from .db import get_db, SessionLocal, utcnow
from .models import (
    Lead,
    PipelineStage,
    Activity,
    Followup,
    Appointment,
    AIInsight,
    Draft,
    ImportBatch,
    ImportRow,
    MappingTemplate,
    SyncRun,
    AuditLog,
    AppSetting,
    StageHistory,
    CloudRequest,
)
from .schemas import (
    NoteIn,
    FollowupIn,
    FollowupAction,
    StageIn,
    RestrictionIn,
    AppointmentIn,
    AppointmentResult,
    MappingIn,
    ImportApproval,
    DraftIn,
    DraftEdit,
    BulkIn,
    SettingsIn,
    SchedulerIn,
    LoginIn,
    OUTCOMES,
    PipelineCreate,
    PipelineRename,
)
from .seed import initialize_defaults
from .security import (
    AccessMiddleware,
    check_login,
    revoke_before,
    revoke_token,
    restore_revocation,
)
from .services import backups as backup_service
from .scheduler import scheduler, configure_scheduler
from .services.leads import (
    lead_query,
    lead_dict,
    activity_dict,
    followup_dict,
    appointment_dict,
    set_stage,
    apply_contact_outcome,
    update_next_followup,
)
from .services.operations import daily_queue, complete_followup
from .services.reporting import dashboard, reports, count_query
from .services.normalization import FIELDS, csv_bytes
from .services.imports import upload_batch, preview_batch, approve_batch
from .services.sync import begin_sync, sync_run
from .routes_intelligence import router as intelligence_router
from .routes_unified import router as unified_router
from .services.cloud_ai import cloud_status
from .services.ai import analyze_lead, insight_dict, generate_draft, ollama_status, context_hash, context_for

logger = logging.getLogger("acquisitions.startup")

# Binding outside loopback, or reaching the app through a tunnel/proxy/LAN address, sends a
# non-loopback Host header. In loopback mode every /api call then fails with 403 while the
# static interface still loads, which looks like a broken app instead of a missing password.
REMOTE_ACCESS_HINT = (
    "APP_ACCESS_PASSWORD is empty, so the app runs in loopback mode. In this mode every /api "
    "request whose Host header is not 127.0.0.1, localhost or ::1 is refused with 403. Opening "
    "the interface through a tunnel, reverse proxy or LAN address therefore shows the page but "
    "fails all data calls. Set APP_ACCESS_PASSWORD to at least 12 characters before exposing it "
    "anywhere beyond this computer, then restart. See docs/DEPLOY_SERVER_AR.md."
)


def warn_if_unreachable(settings):
    """Surface the loopback/tunnel mismatch at startup instead of only in a 403 body."""
    if settings.app_access_password:
        return
    logger.warning(REMOTE_ACCESS_HINT)
    print(f"WARNING: {REMOTE_ACCESS_HINT}", flush=True)


def migrate():
    from .services.database_safety import protect_before_upgrade

    protect_before_upgrade(get_settings().database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/migrations"))
    config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
    command.upgrade(config, "head")


@asynccontextmanager
async def lifespan(app):
    settings = get_settings()
    if settings.app_host not in {"127.0.0.1", "localhost", "::1"} and len(settings.app_access_password) < 12:
        raise RuntimeError("Remote binding requires APP_ACCESS_PASSWORD of at least 12 characters")
    warn_if_unreachable(settings)
    migrate()
    with SessionLocal() as db:
        initialize_defaults(db)
        restore_revocation(db)
        for run in db.scalars(select(SyncRun).where(SyncRun.result == "running")):
            run.result, run.finished_at, run.errors = (
                "failed",
                utcnow(),
                ["Application stopped during sync; prior committed records retained. Run a reconciliation."],
            )
        for batch in db.scalars(select(ImportBatch).where(ImportBatch.state == "importing")):
            batch.state = "partial"
            batch.errors = [
                "Interrupted local import; committed rows are idempotent. Select remaining/failed rows to resume."
            ]
        for pending in db.scalars(select(CloudRequest).where(CloudRequest.state == "running")):
            pending.state = "outcome_unknown"
            pending.error = (
                "Application stopped during a provider request. It may have completed; no automatic retry was made."
            )
            pending.completed_at = utcnow()
        db.commit()
        configure_scheduler(db)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Acquisitions Assistant AI",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.add_middleware(AccessMiddleware)
DB = Annotated[Session, Depends(get_db)]


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Do not reflect passwords, secrets or uploaded seller payloads in validation errors.
    return JSONResponse(
        {"detail": "; ".join(".".join(str(p) for p in e["loc"]) + ": " + e["msg"] for e in exc.errors())},
        status_code=422,
    )


def found(db, model, id):
    record = db.get(model, id)
    if not record:
        raise HTTPException(404, "Record not found")
    return record


def filter_params(request):
    allowed = {
        "search",
        "stage",
        "source",
        "manager",
        "state",
        "contact_status",
        "metric",
        "followup",
        "from_date",
        "to_date",
    }
    return {k: v for k, v in request.query_params.items() if k in allowed and v}


def aware(dt):
    if dt and not dt.tzinfo:
        raise ValueError("Include a timezone offset in timestamps")
    return dt


def download(content, filename):
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/health")
def health():
    return {"status": "ok", "application": "Acquisitions Assistant AI"}


def record_audit(db, action: str, details: dict):
    """Authentication must never fail because the audit row could not be written."""
    try:
        db.add(AuditLog(action=action, details=details))
        db.commit()
    except Exception:
        db.rollback()


@app.get("/api/auth/status")
def auth_status():
    return {"required": bool(get_settings().app_access_password)}


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, db: DB):
    client = request.client.host if request.client else "local"
    token, status = check_login(client, body.password, get_settings())
    if status != 200:
        record_audit(db, "auth_login_failed", {"client": client, "status": status})
        raise HTTPException(
            status, "Too many attempts; wait a minute" if status == 429 else "Incorrect workspace password"
        )
    record_audit(db, "auth_login", {"client": client})
    return {"token": token, "expires_in_seconds": 43200}


@app.post("/api/auth/logout")
def logout(request: Request, db: DB):
    """Cancel this browser's session immediately; the token stops working at once."""
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    revoke_token(token)
    record_audit(db, "auth_logout", {"scope": "this_session"})
    return {"signed_out": True}


@app.post("/api/auth/logout-all")
def logout_all(db: DB):
    """Cancel every session issued so far, on every device, and remember it."""

    def persist(cutoff):
        stored = db.get(AppSetting, "auth")
        value = dict(stored.value) if stored else {}
        value["revoked_before"] = cutoff
        if stored:
            stored.value = value
        else:
            db.add(AppSetting(key="auth", value=value))
        db.commit()

    from .security import now_ms

    revoke_before(now_ms(), persist=persist)
    record_audit(db, "auth_logout", {"scope": "all_sessions"})
    return {"signed_out": True, "scope": "all_sessions"}


@app.get("/api/meta")
def meta(db: DB):
    return {
        "stages": [
            {"code": s.code, "label": s.label, "position": s.position, "active": s.active}
            for s in db.scalars(select(PipelineStage).order_by(PipelineStage.position))
        ],
        "outcomes": OUTCOMES,
        "import_fields": FIELDS,
        "timezone": get_settings().app_timezone,
        "communication": "Draft only — this app cannot send messages, emails or calls.",
        "mode": get_settings().resimpli_mode,
        "sources": list(db.scalars(select(Lead.lead_source).where(Lead.lead_source.is_not(None)).distinct())),
        "managers": list(
            db.scalars(select(Lead.assigned_manager).where(Lead.assigned_manager.is_not(None)).distinct())
        ),
    }


@app.post("/api/pipeline/stages")
def pipeline_add(body: PipelineCreate, db: DB):
    if db.get(PipelineStage, body.code) or db.scalar(select(PipelineStage).where(PipelineStage.label == body.label)):
        raise ValueError("Stage code and label must be unique")
    position = (db.scalar(select(func.max(PipelineStage.position))) or 0) + 1
    stage = PipelineStage(code=body.code, label=body.label, position=position)
    db.add(stage)
    db.add(AuditLog(action="pipeline_stage_added", details=body.model_dump()))
    db.commit()
    return {"code": stage.code, "label": stage.label}


@app.patch("/api/pipeline/stages/{code}")
def pipeline_rename(code: str, body: PipelineRename, db: DB):
    stage = found(db, PipelineStage, code)
    duplicate = db.scalar(select(PipelineStage).where(PipelineStage.label == body.label, PipelineStage.code != code))
    if duplicate:
        raise ValueError("Stage label must be unique")
    stage.label = body.label
    db.add(AuditLog(action="pipeline_stage_renamed", details={"code": code, "label": body.label}))
    db.commit()
    return {"code": code, "label": stage.label}


@app.get("/api/dashboard")
def get_dashboard(request: Request, db: DB):
    return dashboard(db, filter_params(request), get_settings().app_timezone)


@app.get("/api/leads")
def list_leads(
    request: Request,
    db: DB,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    sort: str = "updated_at",
    direction: str = "desc",
):
    query = lead_query(filter_params(request), get_settings().app_timezone)
    fields = {
        "full_name",
        "original_created_at",
        "updated_at",
        "next_followup_at",
        "stage_code",
        "lead_source",
        "last_contact_at",
    }
    if sort not in fields or direction not in {"asc", "desc"}:
        raise ValueError("Invalid sort field or direction")
    field = getattr(Lead, sort)
    order = field.asc() if direction == "asc" else field.desc()
    total = count_query(db, query)
    records = db.scalars(
        query.order_by(order.nullslast(), Lead.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [lead_dict(lead_record) for lead_record in records],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/leads/export")
def export_leads(request: Request, db: DB):
    records = db.scalars(lead_query(filter_params(request), get_settings().app_timezone)).all()
    headers = [
        "external_id",
        "full_name",
        "primary_phone",
        "email",
        "street_address",
        "city",
        "state",
        "zip_code",
        "lead_source",
        "original_created_at",
        "stage_code",
        "source_status",
        "contact_status",
        "last_contact_at",
        "next_followup_at",
        "assigned_manager",
        "restriction_status",
    ]
    rows = []
    for lead_record in records:
        row = lead_dict(lead_record)
        row.update(
            {
                k: getattr(lead_record.properties[0], k) if lead_record.properties else None
                for k in ["street_address", "city", "state", "zip_code"]
            }
        )
        rows.append(row)
    db.add(AuditLog(action="leads_exported", details={"count": len(rows), "filters": filter_params(request)}))
    db.commit()
    return download(csv_bytes(rows, headers), "seller-leads.csv")


@app.post("/api/leads/bulk-stage")
def bulk_stage(body: BulkIn, db: DB):
    if not body.confirm:
        raise ValueError("Confirm this local-only bulk status change")
    found(db, PipelineStage, body.stage_code)
    leads = db.scalars(select(Lead).where(Lead.id.in_(body.lead_ids))).all()
    if len(leads) != len(set(body.lead_ids)):
        raise ValueError("Some selected leads no longer exist")
    for lead in leads:
        set_stage(db, lead, body.stage_code)
    db.commit()
    return {"updated": len(leads), "external_writes": 0}


@app.get("/api/leads/{lead_id}")
def lead_profile(lead_id: int, db: DB):
    lead_record = found(db, Lead, lead_id)
    insight = db.scalar(select(AIInsight).where(AIInsight.lead_id == lead_record.id).order_by(AIInsight.id.desc()))
    draft = db.scalar(select(Draft).where(Draft.lead_id == lead_record.id).order_by(Draft.id.desc()))
    return {
        **lead_dict(lead_record),
        "source_data": lead_record.source_data,
        "activities": [
            activity_dict(a)
            for a in db.scalars(
                select(Activity)
                .where(Activity.lead_id == lead_record.id)
                .order_by(Activity.occurred_at.desc().nullslast(), Activity.id.desc())
            )
        ],
        "followups": [
            followup_dict(f)
            for f in db.scalars(
                select(Followup).where(Followup.lead_id == lead_record.id).order_by(Followup.due_at.asc().nullslast())
            )
        ],
        "appointments": [
            appointment_dict(a)
            for a in db.scalars(
                select(Appointment).where(Appointment.lead_id == lead_record.id).order_by(Appointment.starts_at)
            )
        ],
        "audit": [
            {"id": a.id, "action": a.action, "details": a.details, "created_at": a.created_at, "actor": a.actor}
            for a in db.scalars(
                select(AuditLog).where(AuditLog.lead_id == lead_record.id).order_by(AuditLog.id.desc()).limit(100)
            )
        ],
        "stage_history": [
            {"from_stage": h.from_stage, "to_stage": h.to_stage, "changed_at": h.changed_at, "source": h.source}
            for h in db.scalars(
                select(StageHistory).where(StageHistory.lead_id == lead_record.id).order_by(StageHistory.changed_at)
            )
        ],
        "insight": insight_dict(insight) if insight else None,
        "insight_stale": bool(
            insight and insight.context_hash != context_hash(lead_record, context_for(db, lead_record))
        ),
        "draft": draft_dict(draft) if draft and lead_record.restriction_status == "reviewed_clear" else None,
        "draft_stale": bool(draft and draft.context != context_for(db, lead_record)),
        "external_url": None,
        "source_notice": "Activity summaries are not full conversation transcripts. Local changes are not written back to REsimpli.",
    }


@app.patch("/api/leads/{lead_id}/stage")
def change_stage(lead_id: int, body: StageIn, db: DB):
    if not body.confirm:
        raise ValueError("Confirm the local-only stage change")
    lead_record = found(db, Lead, lead_id)
    found(db, PipelineStage, body.stage_code)
    set_stage(db, lead_record, body.stage_code)
    db.commit()
    return lead_dict(lead_record)


@app.post("/api/leads/{lead_id}/restriction")
def change_restriction(lead_id: int, body: RestrictionIn, db: DB):
    lead_record = found(db, Lead, lead_id)
    if not body.confirm:
        raise ValueError("Confirm the evidence-based restriction review")
    if lead_record.source_do_not_contact is True and not body.restricted:
        raise ValueError("A verified source Do Not Contact restriction cannot be cleared locally")
    lead_record.local_do_not_contact = body.restricted
    lead_record.restriction_reviewed = True
    lead_record.restriction_evidence = body.evidence
    db.add(
        AuditLog(
            lead_id=lead_record.id,
            action="restriction_reviewed",
            details={"restricted": body.restricted, "evidence": body.evidence},
        )
    )
    db.commit()
    return lead_dict(lead_record)


@app.post("/api/leads/{lead_id}/activities")
def add_activity(lead_id: int, body: NoteIn, db: DB):
    lead_record = found(db, Lead, lead_id)
    if body.activity_type != "note" and (not body.confirm or not body.outcome):
        raise ValueError("Confirm the actual outcome for calls, offers and appointment results")
    occurred = aware(body.occurred_at) or utcnow()
    a = Activity(
        lead_id=lead_record.id,
        summary=body.summary,
        activity_type=body.activity_type,
        outcome=body.outcome if body.activity_type != "note" else None,
        occurred_at=occurred,
        source="local",
        source_metadata={"recorded_by_user": True, "not_sent_by_app": True},
    )
    db.add(a)
    if body.activity_type != "note":
        apply_contact_outcome(lead_record, body.outcome, occurred)
    db.add(
        AuditLog(
            lead_id=lead_record.id,
            action="activity_recorded",
            details={"type": body.activity_type, "outcome": body.outcome},
        )
    )
    db.commit()
    return activity_dict(a)


@app.get("/api/queue")
def queue(db: DB, section: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100)):
    return daily_queue(db, get_settings().app_timezone, section, page, page_size)


@app.post("/api/followups")
def create_followup(body: FollowupIn, db: DB):
    lead_record = found(db, Lead, body.lead_id)
    aware(body.due_at)
    if body.property_id and body.property_id not in [p.id for p in lead_record.properties]:
        raise ValueError("Property must be associated with this lead")
    f = Followup(**body.model_dump())
    db.add(f)
    db.add(AuditLog(lead_id=lead_record.id, action="followup_created", details={"reason": body.reason}))
    update_next_followup(db, lead_record)
    db.commit()
    return followup_dict(f)


@app.post("/api/followups/{followup_id}/action")
def act_followup(followup_id: int, body: FollowupAction, db: DB):
    return followup_dict(complete_followup(db, found(db, Followup, followup_id), body))


@app.get("/api/appointments")
def list_appointments(db: DB):
    return [
        {
            **appointment_dict(a),
            "seller": db.get(Lead, a.lead_id).full_name,
            "restriction_status": db.get(Lead, a.lead_id).restriction_status,
        }
        for a in db.scalars(select(Appointment).order_by(Appointment.starts_at))
    ]


@app.post("/api/appointments")
def create_appointment(body: AppointmentIn, db: DB):
    found(db, Lead, body.lead_id)
    aware(body.starts_at)
    a = Appointment(**body.model_dump(), source="local")
    db.add(a)
    db.add(
        AuditLog(lead_id=body.lead_id, action="appointment_recorded", details={"starts_at": body.starts_at.isoformat()})
    )
    db.commit()
    return appointment_dict(a)


@app.post("/api/appointments/{appointment_id}/result")
def record_appointment_result(appointment_id: int, body: AppointmentResult, db: DB):
    if not body.confirm:
        raise ValueError("Confirm the appointment result")
    a = found(db, Appointment, appointment_id)
    a.local_result = body.result
    db.add(
        Activity(
            lead_id=a.lead_id,
            activity_type="appointment_result",
            outcome=body.result,
            occurred_at=utcnow(),
            source="local",
            summary=body.note or f"Appointment result recorded: {body.result}",
            source_metadata={"appointment_id": a.id, "source_status_preserved": a.status},
        )
    )
    db.add(
        AuditLog(
            lead_id=a.lead_id,
            action="appointment_result_recorded",
            details={"appointment_id": a.id, "result": body.result},
        )
    )
    db.commit()
    return appointment_dict(a)


def batch_dict(b):
    return {
        k: getattr(b, k)
        for k in [
            "id",
            "filename",
            "checksum",
            "sheets",
            "row_count",
            "state",
            "counts",
            "errors",
            "mapping_config",
            "created_at",
            "finished_at",
        ]
    }


@app.get("/api/imports")
def list_imports(db: DB):
    return [batch_dict(b) for b in db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc()))]


@app.post("/api/imports/upload")
async def upload_import(db: DB, file: UploadFile = File(...)):
    settings = get_settings()
    content = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    await file.close()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "File exceeds the configured upload limit")
    batch, repeated = await asyncio.to_thread(upload_batch, db, content, file.filename or "upload", settings)
    return {**batch_dict(batch), "repeated_file": repeated}


@app.get("/api/imports/templates")
def list_templates(db: DB):
    return [
        {"id": t.id, "name": t.name, "mapping": t.mapping, "date_order": t.date_order}
        for t in db.scalars(select(MappingTemplate).order_by(MappingTemplate.name))
    ]


@app.get("/api/imports/{batch_id}")
def get_batch(
    batch_id: int,
    db: DB,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    state: str | None = None,
):
    b = found(db, ImportBatch, batch_id)
    query = select(ImportRow).where(ImportRow.batch_id == b.id)
    if state:
        query = query.where(ImportRow.state == state)
    rows = db.scalars(query.order_by(ImportRow.id).offset((page - 1) * page_size).limit(page_size))
    return {
        **batch_dict(b),
        "total_rows": count_query(db, query),
        "page": page,
        "rows": [
            {
                k: getattr(r, k)
                for k in [
                    "id",
                    "sheet",
                    "row_number",
                    "original",
                    "normalized",
                    "errors",
                    "warnings",
                    "duplicate_kind",
                    "candidates",
                    "resolution",
                    "state",
                    "lead_id",
                    "external_id",
                    "error",
                ]
            }
            for r in rows
        ],
    }


@app.get("/api/imports/{batch_id}/eligible-ids")
def eligible_import_ids(batch_id: int, db: DB):
    found(db, ImportBatch, batch_id)
    ids = db.scalars(
        select(ImportRow.id).where(
            ImportRow.batch_id == batch_id,
            ImportRow.state.in_(["ready", "failed"]),
            ImportRow.duplicate_kind == "new_record",
        )
    )
    return {"row_ids": list(ids)}


@app.post("/api/imports/{batch_id}/preview")
def preview_import(batch_id: int, body: MappingIn, db: DB):
    return batch_dict(preview_batch(db, found(db, ImportBatch, batch_id), body, get_settings()))


@app.post("/api/imports/{batch_id}/approve")
def approve_import(batch_id: int, body: ImportApproval, db: DB):
    return batch_dict(approve_batch(db, found(db, ImportBatch, batch_id), body))


@app.post("/api/imports/{batch_id}/external")
def external_import_disabled(batch_id: int, db: DB):
    found(db, ImportBatch, batch_id)
    raise HTTPException(
        409,
        "External creation is disabled. No supported account response adapter or automation safety has been verified. Use the reviewed CSV handoff.",
    )


@app.get("/api/imports/{batch_id}/export")
def export_import(batch_id: int, db: DB, kind: str = "report"):
    b = found(db, ImportBatch, batch_id)
    records = db.scalars(select(ImportRow).where(ImportRow.batch_id == b.id).order_by(ImportRow.id)).all()
    if kind == "rejected":
        records = [r for r in records if r.state in {"invalid", "failed"}]
        headers = sorted({key for r in records for key in r.original}) + ["_sheet", "_row", "_errors"]
        rows = [
            {
                **r.original,
                "_sheet": r.sheet,
                "_row": r.row_number,
                "_errors": "; ".join(r.errors + ([r.error] if r.error else [])),
            }
            for r in records
        ]
    elif kind == "resimpli":
        # Mapping-oriented CSV; not a claim of a hidden proprietary bulk API schema.
        headers = [
            "First Name",
            "Last Name",
            "Full Name",
            "Phone Number",
            "Email Address",
            "Property Address",
            "City",
            "State",
            "ZIP Code",
            "Lead Source",
            "Original Creation Date",
            "Last Contact Date",
            "Status",
            "Assigned Manager",
            "Seller Motivation",
            "Asking Price",
            "Estimated Value",
            "Repair Estimate",
            "Appointment Date",
            "Follow-up Date",
            "Notes",
            "REsimpli Lead ID",
            "Do Not Contact",
        ]
        keys = [
            "first_name",
            "last_name",
            "full_name",
            "primary_phone",
            "email",
            "street_address",
            "city",
            "state",
            "zip_code",
            "lead_source",
            "original_created_at",
            "last_contact_at",
            "source_status",
            "assigned_manager",
            "seller_motivation",
            "asking_price",
            "estimated_value",
            "repair_estimate",
            "appointment_at",
            "next_followup_at",
            "notes",
            "external_id",
            "source_do_not_contact",
        ]
        rows = [
            dict(zip(headers, [r.normalized.get(key) for key in keys]))
            for r in records
            if r.state in {"imported", "linked"} and r.resolution != "skip"
        ]
        if not rows:
            raise ValueError("Approve a local import first; CSV handoff contains only reviewed imported/linked records")
    elif kind == "report":
        headers = ["sheet", "row_number", "state", "duplicate_kind", "resolution", "lead_id", "external_id", "errors"]
        rows = [
            {
                **{k: getattr(r, k) for k in headers if k != "errors"},
                "errors": "; ".join(r.errors + ([r.error] if r.error else [])),
            }
            for r in records
        ]
    else:
        raise ValueError("Choose report, rejected or resimpli export")
    db.add(AuditLog(action="import_exported", details={"batch_id": b.id, "kind": kind, "records": len(rows)}))
    db.commit()
    return download(csv_bytes(rows, headers), f"import-{batch_id}-{kind}.csv")


def sync_dict(r):
    return {
        k: getattr(r, k)
        for k in [
            "id",
            "started_at",
            "finished_at",
            "result",
            "mode",
            "fetched",
            "created",
            "updated",
            "skipped",
            "failed",
            "errors",
            "resources",
        ]
    }


@app.get("/api/sync")
def sync_status(db: DB):
    runs = db.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(50)).all()
    last_success = db.scalar(select(SyncRun).where(SyncRun.result == "success").order_by(SyncRun.id.desc()))
    last_live_success = db.scalar(
        select(SyncRun).where(SyncRun.result == "success", SyncRun.mode == "live").order_by(SyncRun.id.desc())
    )
    settings = get_settings()
    return {
        "runs": [sync_dict(r) for r in runs],
        "health": runs[0].result if runs else "never",
        "last_success": last_success.finished_at if last_success else None,
        "last_live_success": last_live_success.finished_at if last_live_success else None,
        "mode": settings.resimpli_mode,
        "credentials_configured": bool(settings.resimpli_api_key),
        "adapter_verified": settings.resimpli_adapter_verified,
        "external_creation_enabled": False,
        "scheduler": db.get(AppSetting, "scheduler").value
        if db.get(AppSetting, "scheduler")
        else {"enabled": False, "interval_minutes": 30},
        "live_verified": bool(last_live_success),
        "notice": "Fixture success does not verify your REsimpli account. Missing records are never deleted locally.",
    }


@app.post("/api/sync/run")
def run_sync(db: DB, background: BackgroundTasks):
    run = begin_sync(db, get_settings())
    background.add_task(sync_run, run.id)
    return {"run_id": run.id, "result": "running"}


@app.patch("/api/sync/scheduler")
def scheduler_settings(body: SchedulerIn, db: DB):
    if body.enabled and get_settings().resimpli_mode == "disabled":
        raise ValueError("Configure fixture or verified live sync before enabling the scheduler")
    value = configure_scheduler(db, body.enabled, body.interval_minutes)
    db.add(AuditLog(action="scheduler_changed", details=value))
    db.commit()
    return value


@app.get("/api/ai/status")
def ai_status(db: DB):
    settings = get_settings()
    return {**ollama_status(settings), "groq": cloud_status(db, settings)}


@app.post("/api/leads/{lead_id}/analyze")
def analyze(lead_id: int, db: DB, force: bool = False):
    insight, cached, warning = analyze_lead(db, found(db, Lead, lead_id), get_settings(), force)
    return {**insight_dict(insight), "cached": cached, "warning": warning}


@app.get("/api/insights")
def list_insights(db: DB):
    records = db.scalars(select(AIInsight).order_by(AIInsight.id.desc()).limit(200)).all()
    seen, result = set(), []
    for insight in records:
        if insight.lead_id not in seen:
            seen.add(insight.lead_id)
            lead = db.get(Lead, insight.lead_id)
            result.append(
                {
                    **insight_dict(insight),
                    "seller": lead.full_name,
                    "stale": insight.context_hash != context_hash(lead, context_for(db, lead)),
                }
            )
    return result


def draft_dict(d):
    return {k: getattr(d, k) for k in ["id", "lead_id", "body", "context", "model_id", "created_at", "updated_at"]}


@app.post("/api/leads/{lead_id}/draft")
def draft(lead_id: int, body: DraftIn, db: DB):
    return draft_dict(generate_draft(db, found(db, Lead, lead_id), body.regenerate))


@app.patch("/api/drafts/{draft_id}")
def edit_draft(draft_id: int, body: DraftEdit, db: DB):
    d = found(db, Draft, draft_id)
    lead_record = found(db, Lead, d.lead_id)
    if lead_record.do_not_contact or lead_record.restriction_status != "reviewed_clear":
        raise ValueError("Draft editing is blocked by the lead’s current contact restriction")
    d.body = body.body
    db.add(AuditLog(lead_id=lead_record.id, action="draft_edited", details={"draft_id": d.id, "never_sent": True}))
    db.commit()
    return draft_dict(d)


@app.get("/api/reports")
def get_reports(request: Request, db: DB):
    return reports(db, filter_params(request), get_settings().app_timezone)


@app.get("/api/reports/export")
def export_reports(request: Request, db: DB):
    report = reports(db, filter_params(request), get_settings().app_timezone)
    return download(
        csv_bytes(report["rates"], ["label", "numerator", "denominator", "percent", "definition"]),
        "acquisitions-report.csv",
    )


@app.get("/api/settings")
def settings_view(db: DB):
    settings = get_settings()
    return {
        "timezone": settings.app_timezone,
        "mode": settings.resimpli_mode,
        "stage_mapping": db.get(AppSetting, "stage_mapping").value,
        "priority_rules": db.get(AppSetting, "priority_rules").value,
        "local_only": settings.app_host in {"127.0.0.1", "localhost", "::1"},
        "authentication_enabled": bool(settings.app_access_password),
        "max_upload_mb": settings.max_upload_mb,
        "max_import_rows": settings.max_import_rows,
        "ollama_enabled": settings.ollama_enabled,
        "ollama_model": settings.ollama_model,
        "api_key_configured": bool(settings.resimpli_api_key),
        "adapter_verified": settings.resimpli_adapter_verified,
        "external_writes": False,
        "automatic_communication": False,
    }


@app.patch("/api/settings")
def settings_update(body: SettingsIn, db: DB):
    if body.stage_mapping is not None:
        stages = set(db.scalars(select(PipelineStage.code)))
        if any(v not in stages for v in body.stage_mapping.values()):
            raise ValueError("Every mapped stage must exist")
        db.get(AppSetting, "stage_mapping").value = {k.strip().lower(): v for k, v in body.stage_mapping.items()}
    if body.priority_rules is not None:
        current = db.get(AppSetting, "priority_rules")
        if set(body.priority_rules) != set(current.value) or any(
            not 0 <= v <= 365 for v in body.priority_rules.values()
        ):
            raise ValueError("Use the existing priority-rule keys and values between 0 and 365")
        current.value = body.priority_rules
    db.add(AuditLog(action="settings_changed", details={"keys": list(body.model_fields_set)}))
    db.commit()
    return settings_view(db)


def backup_view(item: dict) -> dict:
    return {**item, "created_at": item["created_at"].isoformat()}


def backup_overview():
    settings = get_settings()
    source = backup_service.database_path(settings.database_url)
    return {
        "enabled": settings.backup_enabled,
        "keep": settings.backup_keep,
        "hour_utc": settings.backup_hour_utc,
        "folder": str(backup_service.backup_directory(source)),
    }


@app.get("/api/backups")
def list_backups():
    settings = get_settings()
    return {**backup_overview(), "backups": [backup_view(b) for b in backup_service.list_backups(settings.database_url)]}


@app.post("/api/backups")
def create_backup_now(db: DB):
    settings = get_settings()
    try:
        created = backup_service.create_backup(settings.database_url, reason="manual")
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    backup_service.prune(settings.database_url, settings.backup_keep)
    db.add(
        AuditLog(
            action="backup_created",
            details={"file": created.name, "reason": "manual", "bytes": created.stat().st_size},
        )
    )
    db.commit()
    # Describe the file we just wrote instead of searching a listing: a naming mismatch
    # must not turn a successful backup into a 500.
    return backup_view(
        {
            "name": created.name,
            "size_bytes": created.stat().st_size,
            "created_at": datetime.fromtimestamp(created.stat().st_mtime, timezone.utc),
            "reason": "manual",
        }
    )


@app.get("/api/backups/{name}")
def download_backup(name: str):
    settings = get_settings()
    try:
        path = backup_service.resolve_backup(settings.database_url, name)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    return FileResponse(path, filename=path.name, media_type="application/vnd.sqlite3")


@app.delete("/api/backups/{name}")
def delete_backup(name: str, db: DB, confirm: str = Query(default="")):
    if confirm != "DELETE BACKUP":
        raise HTTPException(400, "Deleting a backup requires confirm=DELETE BACKUP")
    settings = get_settings()
    try:
        path = backup_service.resolve_backup(settings.database_url, name)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    path.unlink(missing_ok=True)
    db.add(AuditLog(action="backup_deleted", details={"file": name}))
    db.commit()
    return {"deleted": name}


@app.get("/api/examples/{filename}")
def example_file(filename: str):
    if filename not in {"sample-seller-leads.csv", "sample-seller-leads.xlsx"}:
        raise HTTPException(404, "Example not found")
    return FileResponse(ROOT / "examples" / filename, filename=filename)


app.include_router(intelligence_router)
app.include_router(unified_router)

# Frontend is bundled once and served by the same local process. No CDN or cloud dependency.
frontend = ROOT / "frontend" / "dist"
if (frontend / "assets").exists():
    app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "API endpoint not found")
    index = frontend / "index.html"
    if not index.exists():
        return JSONResponse(
            {"detail": "Frontend not built. Run npm ci && npm run build inside frontend/."}, status_code=503
        )
    return FileResponse(index)
