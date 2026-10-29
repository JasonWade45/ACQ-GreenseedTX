"""Merged preparation, property research and local-only workspace operations."""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import get_db
from .models import Lead, CallPlan, WorkspaceMerge, AuditLog
from .schemas import StrictModel
from .config import get_settings
from .services.research import prepare_plan, get_plan, plan_dict, update_plan, comps_brief, add_comp, remove_comp
from .services.ai import analyze_lead

router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_db)]


class PlanIn(StrictModel):
    regenerate: bool = False


class PlanEdit(StrictModel):
    checks: dict[str, bool] = Field(default_factory=dict)
    answers: dict[str, str] = Field(default_factory=dict)
    opener: str | None = Field(default=None, max_length=1200)


class CompIn(StrictModel):
    property_id: int
    address: str = Field(min_length=4, max_length=300)
    sold_price: float = Field(gt=0, le=100_000_000)
    square_feet: int | None = Field(default=None, ge=100, le=100_000)
    sold_date: str | None = Field(default=None, max_length=40)
    bedrooms: int | None = Field(default=None, ge=0, le=30)
    bathrooms: float | None = Field(default=None, ge=0, le=30)
    distance_miles: float | None = Field(default=None, ge=0, le=200)
    source: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=600)


class SubjectFacts(StrictModel):
    """Facts the reviewer knows about the subject property.

    Only ever fills an empty field: a value that came from the source is never
    replaced here, so the CRM stays the record of what the CRM said.
    """

    square_feet: int | None = Field(default=None, ge=100, le=100_000)
    bedrooms: int | None = Field(default=None, ge=0, le=30)
    bathrooms: float | None = Field(default=None, ge=0, le=30)


class LocalRefresh(StrictModel):
    confirm: bool = False
    limit: int = Field(default=100, ge=1, le=200)


def found(db, id):
    lead = db.get(Lead, id)
    if not lead:
        raise HTTPException(404, "Seller record not found")
    return lead


@router.get("/leads/{lead_id}/call-plan")
def read_plan(lead_id: int, db: DB):
    lead = found(db, lead_id)
    plan = get_plan(db, lead)
    return plan_dict(plan, lead) if plan else None


@router.post("/leads/{lead_id}/call-plan")
def create_plan(lead_id: int, body: PlanIn, db: DB):
    lead = found(db, lead_id)
    return plan_dict(prepare_plan(db, lead, body.regenerate), lead)


@router.patch("/call-plans/{plan_id}")
def edit_plan(plan_id: int, body: PlanEdit, db: DB):
    plan = db.get(CallPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Preparation not found")
    if len(body.checks) > 50 or len(body.answers) > 30 or any(len(value) > 3000 for value in body.answers.values()):
        raise ValueError("Preparation update exceeds the limit")
    lead = found(db, plan.lead_id)
    return plan_dict(update_plan(db, lead, plan, body.checks, body.answers, body.opener), lead)


@router.get("/leads/{lead_id}/comps-brief")
def read_comps(lead_id: int, db: DB, property_id: int | None = None):
    return comps_brief(found(db, lead_id), property_id)


@router.patch("/leads/{lead_id}/properties/{property_id}")
def fill_subject_facts(lead_id: int, property_id: int, body: SubjectFacts, db: DB):
    lead = found(db, lead_id)
    prop = next((item for item in lead.properties if item.id == property_id), None)
    if not prop:
        raise HTTPException(404, "That property is not attached to this seller")
    incoming = {key: value for key, value in body.model_dump().items() if value is not None}
    if not incoming:
        raise ValueError("Enter at least one fact")
    filled, kept = {}, {}
    for field, value in incoming.items():
        if getattr(prop, field) is not None:
            kept[field] = getattr(prop, field)
        else:
            setattr(prop, field, value)
            filled[field] = value
    if filled:
        db.add(
            AuditLog(
                lead_id=lead.id,
                action="property_facts_entered",
                details={"property_id": prop.id, "filled": filled, "verified_by_user": True},
            )
        )
        db.commit()
    return {
        "property_id": prop.id,
        "filled": filled,
        "kept_from_source": kept,
        "message": (
            "Saved."
            if filled and not kept
            else "Saved the empty fields; values already present from the source were kept."
        ),
        "comps_brief": comps_brief(lead, prop.id),
    }


@router.post("/leads/{lead_id}/comps")
def create_comp(lead_id: int, body: CompIn, db: DB):
    lead = found(db, lead_id)
    comp = add_comp(db, lead, body.property_id, body.model_dump())
    return {"comps": comps_brief(lead, body.property_id)["comps"], "added": comp}


@router.delete("/leads/{lead_id}/comps/{comp_id}")
def delete_comp(lead_id: int, comp_id: str, db: DB):
    lead = found(db, lead_id)
    return remove_comp(db, lead, comp_id)


@router.post("/insights/refresh-local")
def local_refresh(body: LocalRefresh, db: DB):
    if not body.confirm:
        raise ValueError("Confirm local rule refresh; no cloud model will be called")
    settings = get_settings().model_copy(update={"ollama_enabled": False, "groq_enabled": False})
    counts = {"processed": 0, "cached": 0, "updated": 0, "cloud_requests": 0}
    for lead in db.scalars(select(Lead).order_by(Lead.updated_at.desc()).limit(body.limit)).all():
        _, cached, _ = analyze_lead(db, lead, settings)
        counts["processed"] += 1
        counts["cached" if cached else "updated"] += 1
    db.add(AuditLog(action="local_analyses_refreshed", details=counts))
    db.commit()
    return counts


class MergeSource(StrictModel):
    source_path: str = Field(min_length=1, max_length=1200)
    confirmation: str


def require_file_database(what: str):
    """Legacy workspace features read and write a SQLite file; a hosted database has none.

    Refusing here is deliberate: these paths would otherwise be handed a database URL
    they treat as a file path, and fail in a way nobody can act on.
    """
    if get_settings().is_postgres:
        raise HTTPException(
            400,
            f"{what} works with a local SQLite database file. This deployment uses PostgreSQL, "
            "where the equivalent is scripts/migrate_sqlite_to_postgres.py (read-only source, "
            "per-table counts, safe to re-run).",
        )


@router.get("/workspace-merges/capabilities")
def merge_capabilities():
    postgres = get_settings().is_postgres
    return {
        "local_selection_available": not postgres
        and get_settings().app_host in {"127.0.0.1", "localhost", "::1"},
        "uploads_supported": False,
        "unavailable_reason": (
            "PostgreSQL deployments migrate with scripts/migrate_sqlite_to_postgres.py" if postgres else None
        ),
    }


@router.post("/workspace-merges/prepare")
def merge_prepare(body: MergeSource, db: DB):
    require_file_database("Preparing a workspace merge")
    if get_settings().app_host not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(
            403,
            "Database selection is local-only. Run legacy/windows/MERGE-WORKSPACES.cmd on your PC; do not upload company databases.",
        )
    if body.confirmation != "PREPARE READ ONLY SNAPSHOT":
        raise ValueError("Explicitly approve a local read-only source snapshot first")
    from .services.workspace_merge import prepare_merge, merge_dict

    return merge_dict(prepare_merge(db, body.source_path), True)


@router.get("/workspace-merges")
def merge_list(db: DB):
    from .services.workspace_merge import merge_dict

    return [
        merge_dict(row)
        for row in db.scalars(select(WorkspaceMerge).order_by(WorkspaceMerge.created_at.desc()).limit(20))
    ]


@router.get("/workspace-merges/{merge_id}")
def merge_detail(merge_id: str, db: DB):
    from .services.workspace_merge import merge_dict

    row = db.get(WorkspaceMerge, merge_id)
    if not row:
        raise HTTPException(404, "Workspace migration not found")
    return merge_dict(row, detail=True)


@router.post("/workspace-merges/{merge_id}/refresh")
def merge_refresh(merge_id: str, db: DB):
    from .services.workspace_merge import refresh_review, merge_dict

    require_file_database("Refreshing a workspace merge")
    row = db.get(WorkspaceMerge, merge_id)
    if not row:
        raise HTTPException(404, "Workspace migration not found")
    return merge_dict(refresh_review(db, row), True)


class MergeDecision(StrictModel):
    source_id: str = Field(max_length=100)
    action: str = Field(pattern="^(separate|link|skip)$")
    target_id: int | None = None
    fill_missing: bool = False


class MergeApproval(StrictModel):
    confirmation: str
    decisions: list[MergeDecision] = Field(max_length=5000)


@router.post("/workspace-merges/{merge_id}/commit")
def merge_commit(merge_id: str, body: MergeApproval, db: DB):
    from .services.workspace_merge import commit_merge, merge_dict

    require_file_database("Committing a workspace merge")
    row = db.get(WorkspaceMerge, merge_id)
    if not row:
        raise HTTPException(404, "Workspace migration not found")
    return merge_dict(commit_merge(db, row, body.confirmation, [item.model_dump() for item in body.decisions]), True)
