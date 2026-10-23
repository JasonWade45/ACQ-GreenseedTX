"""AI endpoints: status, analysis, drafts, pre-call plans. Nothing is ever sent."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Lead, MessageDraft
from app.services.ai_service import (
    ai_status,
    analyze_all_changed,
    analyze_lead,
    batch_progress,
    build_call_plan,
    generate_draft,
    get_call_plan,
    start_batch_analysis,
    update_call_plan,
)
from app.services.audit import audit
from app.services.leads import serialize_call_plan, serialize_draft, serialize_insight

router = APIRouter(tags=["ai"])


class DraftRequest(BaseModel):
    channel: str = "text"
    force: bool = False


class DraftEdit(BaseModel):
    edited_body: str


class CallPlanUpdate(BaseModel):
    opener: Optional[str] = None
    talking_points: Optional[list[dict]] = None
    questions: Optional[list[dict]] = None


@router.get("/ai/status")
def status():
    data = ai_status()
    data["disclaimer"] = (
        "AI output is advisory only. Review every recommendation and draft before acting. "
        "This application never sends messages to sellers."
    )
    return data


@router.post("/ai/analyze/{lead_id}")
def analyze(lead_id: str, force: bool = False, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise ValueError("Lead not found")
    insight = analyze_lead(db, lead, force=force)
    audit(db, "ai.analyze", "lead", lead.id, {"engine": insight.engine})
    return serialize_insight(insight)


@router.post("/ai/analyze-batch")
def analyze_batch(limit: int = 100, background: bool = False, db: Session = Depends(get_db)):
    if background:
        # Long runs are paced under Groq's rate limit — run in a background
        # thread and let the UI poll /ai/analyze-progress.
        snapshot = start_batch_analysis(limit)
        audit(db, "ai.analyze_batch_start", "ai", None, {"limit": limit})
        return snapshot
    result = analyze_all_changed(db, limit=limit)
    audit(db, "ai.analyze_batch", "ai", None, result)
    return result


@router.get("/ai/analyze-progress")
def analyze_progress():
    return batch_progress()


@router.post("/ai/draft/{lead_id}")
def draft(lead_id: str, payload: DraftRequest, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise ValueError("Lead not found")
    result = generate_draft(db, lead, channel=payload.channel, force=payload.force)
    audit(db, "ai.draft", "lead", lead.id, {"draft_id": result.id, "refusal": bool(result.refusal_reason)})
    return serialize_draft(result)


@router.patch("/ai/drafts/{draft_id}")
def edit_draft(draft_id: str, payload: DraftEdit, db: Session = Depends(get_db)):
    draft_row = db.get(MessageDraft, draft_id)
    if not draft_row:
        raise ValueError("Draft not found")
    draft_row.edited_body = payload.edited_body
    db.commit()
    return serialize_draft(draft_row)


@router.get("/ai/drafts/{draft_id}")
def get_draft(draft_id: str, db: Session = Depends(get_db)):
    draft_row = db.get(MessageDraft, draft_id)
    if not draft_row:
        raise ValueError("Draft not found")
    return serialize_draft(draft_row)


@router.get("/ai/no-send-confirmation")
def no_send_confirmation():
    return {
        "sends_messages": False,
        "sends_sms": False,
        "sends_email": False,
        "places_calls": False,
        "statement": (
            "This application has no messaging, dialing or outreach capability. "
            "Drafts are stored locally for a human to review, edit and copy. "
            "Contact with sellers happens only through your company's approved workflow."
        ),
    }


@router.get("/ai/call-plan/{lead_id}")
def read_call_plan(lead_id: str, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise ValueError("Lead not found")
    return serialize_call_plan(get_call_plan(db, lead))


@router.post("/ai/call-plan/{lead_id}")
def create_call_plan(lead_id: str, force: bool = False, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise ValueError("Lead not found")
    plan = build_call_plan(db, lead, force=force)
    audit(
        db,
        "ai.call_plan",
        "lead",
        lead.id,
        {"engine": plan.engine, "refusal": bool(plan.refusal_reason), "force": force},
    )
    return serialize_call_plan(plan)


@router.patch("/ai/call-plan/{lead_id}")
def patch_call_plan(lead_id: str, payload: CallPlanUpdate, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise ValueError("Lead not found")
    plan = get_call_plan(db, lead)
    if not plan:
        raise ValueError("No call plan for this lead yet — generate one first.")
    plan = update_call_plan(
        db, plan, opener=payload.opener, talking_points=payload.talking_points, questions=payload.questions
    )
    audit(db, "ai.call_plan_update", "lead", lead.id, {})
    return serialize_call_plan(plan)
