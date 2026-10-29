from typing import Optional
from datetime import datetime
from sqlalchemy import String, Text, Integer, Float, Boolean, ForeignKey, JSON, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base, UTCDateTime, utcnow


class PipelineStage(Base):
    __tablename__ = "pipeline_stages"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(100), unique=True)
    position: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LeadProperty(Base):
    __tablename__ = "lead_properties"
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), primary_key=True)
    relationship_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(200), unique=True, index=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(150))
    last_name: Mapped[Optional[str]] = mapped_column(String(150))
    full_name: Mapped[str] = mapped_column(String(300), index=True)
    primary_phone: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    primary_phone_type: Mapped[Optional[str]] = mapped_column(String(40))
    phone2: Mapped[Optional[str]] = mapped_column(String(40))
    phone2_type: Mapped[Optional[str]] = mapped_column(String(40))
    phone3: Mapped[Optional[str]] = mapped_column(String(40))
    phone3_type: Mapped[Optional[str]] = mapped_column(String(40))
    phone4: Mapped[Optional[str]] = mapped_column(String(40))
    phone4_type: Mapped[Optional[str]] = mapped_column(String(40))
    phone5: Mapped[Optional[str]] = mapped_column(String(40))
    phone5_type: Mapped[Optional[str]] = mapped_column(String(40))
    email: Mapped[Optional[str]] = mapped_column(String(320), index=True)
    lead_source: Mapped[Optional[str]] = mapped_column(String(200), index=True)
    original_created_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), index=True)
    stage_code: Mapped[str] = mapped_column(ForeignKey("pipeline_stages.code"), default="new", index=True)
    local_stage_override: Mapped[bool] = mapped_column(Boolean, default=False)
    source_status: Mapped[Optional[str]] = mapped_column(String(200))
    contact_status: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    contact_outcome: Mapped[Optional[str]] = mapped_column(String(80))
    assigned_manager: Mapped[Optional[str]] = mapped_column(String(200), index=True)
    last_contact_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    next_followup_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), index=True)
    source_do_not_contact: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    local_do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    restriction_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    restriction_evidence: Mapped[Optional[str]] = mapped_column(Text)
    in_license: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # Phase 2 (Data Syndicate) fields
    recorded_date: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), index=True)
    score: Mapped[Optional[float]] = mapped_column(Float)
    heat: Mapped[Optional[str]] = mapped_column(String(20))
    equity_pct: Mapped[Optional[float]] = mapped_column(Float)
    county: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    lead_type: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    priority_tier: Mapped[Optional[str]] = mapped_column(String(4), index=True)
    priority_rank: Mapped[Optional[int]] = mapped_column(Integer)
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(700), index=True)
    needs_skip_trace: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    user_edited_fields: Mapped[list] = mapped_column(JSON, default=list)
    import_batch_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    # Data Syndicate context. Internal only: it must never appear in outgoing text.
    ds_flags: Mapped[dict] = mapped_column(JSON, default=dict)
    ds_flags_raw: Mapped[Optional[str]] = mapped_column(Text)
    ds_extra_flags: Mapped[list] = mapped_column(JSON, default=list)
    ds_compatible_offers: Mapped[list] = mapped_column(JSON, default=list)
    # relationship = documented context required (original behavior); cold = template library.
    outreach_mode: Mapped[str] = mapped_column(String(20), default="relationship", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    synced_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    detail_synced_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    source_hash: Mapped[Optional[str]] = mapped_column(String(64))
    source_kind: Mapped[str] = mapped_column(String(40), default="local")
    source_data: Mapped[dict] = mapped_column(JSON, default=dict)
    properties: Mapped[list["Property"]] = relationship(secondary="lead_properties", lazy="selectin")
    phones: Mapped[list["LeadPhone"]] = relationship("LeadPhone", cascade="all, delete-orphan", lazy="selectin")
    activities: Mapped[list["Activity"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    followups: Mapped[list["Followup"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    __table_args__ = (CheckConstraint("contact_status IN ('unknown','not_contacted','attempted','contacted')"),)

    @property
    def do_not_contact(self):
        return self.source_do_not_contact is True or self.local_do_not_contact

    @property
    def restriction_status(self):
        if self.do_not_contact:
            return "do_not_contact"
        if self.source_do_not_contact is False or self.restriction_reviewed:
            return "reviewed_clear"
        return "unknown"


class LeadPhone(Base):
    __tablename__ = "lead_phones"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    phone_normalized: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    phone_type: Mapped[Optional[str]] = mapped_column(String(40))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    source_column: Mapped[Optional[str]] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Property(Base):
    __tablename__ = "properties"
    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(200), unique=True)
    street_address: Mapped[Optional[str]] = mapped_column(String(400), index=True)
    city: Mapped[Optional[str]] = mapped_column(String(150))
    state: Mapped[Optional[str]] = mapped_column(String(2), index=True)
    zip_code: Mapped[Optional[str]] = mapped_column(String(12))
    normalized_address: Mapped[Optional[str]] = mapped_column(String(650), index=True)
    property_type: Mapped[Optional[str]] = mapped_column(String(100))
    bedrooms: Mapped[Optional[int]] = mapped_column(Integer)
    bathrooms: Mapped[Optional[float]] = mapped_column(Float)
    square_feet: Mapped[Optional[int]] = mapped_column(Integer)
    year_built: Mapped[Optional[int]] = mapped_column(Integer)
    asking_price: Mapped[Optional[float]] = mapped_column(Float)
    estimated_value: Mapped[Optional[float]] = mapped_column(Float)
    repair_estimate: Mapped[Optional[float]] = mapped_column(Float)
    property_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class Activity(Base):
    __tablename__ = "activities"
    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(200))
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[Optional[int]] = mapped_column(ForeignKey("properties.id"))
    activity_type: Mapped[str] = mapped_column(String(60))
    direction: Mapped[Optional[str]] = mapped_column(String(30))
    outcome: Mapped[Optional[str]] = mapped_column(String(80))
    occurred_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), index=True)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    source: Mapped[str] = mapped_column(String(40), default="local")
    summary: Mapped[str] = mapped_column(Text)
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    lead: Mapped[Lead] = relationship(back_populates="activities")
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_activity_source_id"),)


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(200), unique=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    status: Mapped[str] = mapped_column(String(40), default="scheduled")
    source_status: Mapped[Optional[str]] = mapped_column(String(80))
    local_result: Mapped[Optional[str]] = mapped_column(String(80))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(40), default="local")
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class Followup(Base):
    __tablename__ = "followups"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[Optional[int]] = mapped_column(ForeignKey("properties.id"))
    due_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    reason: Mapped[str] = mapped_column(Text)
    suggested_action: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    completion_outcome: Mapped[Optional[str]] = mapped_column(String(80))
    creation_source: Mapped[str] = mapped_column(String(40), default="manual")
    ai_suggested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    lead: Mapped[Lead] = relationship(back_populates="followups")
    __table_args__ = (
        CheckConstraint("status IN ('pending','completed','cancelled')"),
        CheckConstraint("priority >= 0 AND priority <= 100"),
    )


class AIInsight(Base):
    __tablename__ = "ai_insights"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    seller_motivation: Mapped[Optional[str]] = mapped_column(Text)
    urgency_indicators: Mapped[list] = mapped_column(JSON, default=list)
    price_information: Mapped[dict] = mapped_column(JSON, default=dict)
    objections: Mapped[list] = mapped_column(JSON, default=list)
    missing_information: Mapped[list] = mapped_column(JSON, default=list)
    recommended_action: Mapped[str] = mapped_column(Text)
    suggested_timing: Mapped[Optional[str]] = mapped_column(String(200))
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    conflicts: Mapped[list] = mapped_column(JSON, default=list)
    analysis_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    model_id: Mapped[str] = mapped_column(String(200))
    context_hash: Mapped[str] = mapped_column(String(64), index=True)
    confidence: Mapped[str] = mapped_column(String(40), default="limited")


class Draft(Base):
    __tablename__ = "drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    context: Mapped[list] = mapped_column(JSON, default=list)
    model_id: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(300))
    checksum: Mapped[str] = mapped_column(String(64), unique=True)
    sheets: Mapped[dict] = mapped_column(JSON, default=dict)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(40), default="uploaded")
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    mapping_config: Mapped[dict] = mapped_column(JSON, default=dict)
    # "standard" or "address_only" (Data Syndicate). The profile only changes
    # acceptance rules; it never weakens the standard profile.
    profile: Mapped[str] = mapped_column(String(40), default="standard")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())


class ImportRow(Base):
    __tablename__ = "import_rows"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), index=True)
    sheet: Mapped[str] = mapped_column(String(200))
    row_number: Mapped[int] = mapped_column(Integer)
    original: Mapped[dict] = mapped_column(JSON)
    normalized: Mapped[dict] = mapped_column(JSON, default=dict)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    duplicate_kind: Mapped[str] = mapped_column(String(80), default="unreviewed")
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    resolution: Mapped[Optional[str]] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    lead_id: Mapped[Optional[int]] = mapped_column(ForeignKey("leads.id"))
    external_id: Mapped[Optional[str]] = mapped_column(String(200))
    error: Mapped[Optional[str]] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("batch_id", "sheet", "row_number", name="uq_import_row"),)


class MappingTemplate(Base):
    __tablename__ = "mapping_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    mapping: Mapped[dict] = mapped_column(JSON)
    date_order: Mapped[str] = mapped_column(String(10), default="reject")


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    result: Mapped[str] = mapped_column(String(30), default="running", index=True)
    mode: Mapped[str] = mapped_column(String(30))
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    resources: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[Optional[int]] = mapped_column(ForeignKey("leads.id"), index=True)
    action: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    actor: Mapped[str] = mapped_column(String(80), default="local_user")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class Suppression(Base):
    __tablename__ = "suppression"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    phone_normalized: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    lead_id: Mapped[Optional[int]] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Template(Base):
    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(60), index=True)
    lead_type_match: Mapped[list] = mapped_column(JSON, default=list)
    flag_conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    body: Mapped[str] = mapped_column(Text)
    variant: Mapped[str] = mapped_column(String(4), default="A")
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(10), default="outbound")
    body: Mapped[str] = mapped_column(Text)
    template_id: Mapped[Optional[int]] = mapped_column(ForeignKey("templates.id", ondelete="SET NULL"), nullable=True)
    variant: Mapped[Optional[str]] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    validator_result: Mapped[dict] = mapped_column(JSON, default=dict)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    sent_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    classification: Mapped[Optional[str]] = mapped_column(String(30))
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    # Why this template was chosen (internal context, never printed in the message).
    reason_tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class Sequence(Base):
    __tablename__ = "sequences"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    lead_type: Mapped[Optional[str]] = mapped_column(String(120))
    cadence: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class SequenceStep(Base):
    __tablename__ = "sequence_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    sequence_id: Mapped[int] = mapped_column(ForeignKey("sequences.id", ondelete="CASCADE"), index=True)
    day_offset: Mapped[int] = mapped_column(Integer)
    template_category: Mapped[str] = mapped_column(String(60))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class LeadSequenceState(Base):
    __tablename__ = "lead_sequence_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    sequence_id: Mapped[int] = mapped_column(ForeignKey("sequences.id", ondelete="CASCADE"), index=True)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    next_due_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    stop_reason: Mapped[Optional[str]] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class SyncConflict(Base):
    __tablename__ = "sync_conflicts"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(80))
    local_value: Mapped[Optional[str]] = mapped_column(Text)
    crm_value: Mapped[Optional[str]] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution: Mapped[Optional[str]] = mapped_column(String(40))


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[Optional[int]] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    due_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    source: Mapped[str] = mapped_column(String(40), default="manual")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())


class StageHistory(Base):
    __tablename__ = "stage_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    from_stage: Mapped[Optional[str]] = mapped_column(String(64))
    to_stage: Mapped[str] = mapped_column(String(64))
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    source: Mapped[str] = mapped_column(String(40))


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


Index("ix_followup_state_due", Followup.status, Followup.due_at)
Index("ix_activity_lead_time", Activity.lead_id, Activity.occurred_at)


class CloudRequest(Base):
    """One explicitly reviewed cloud request; never a communication/outreach job."""

    __tablename__ = "cloud_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30), default="groq")
    purpose: Mapped[str] = mapped_column(String(20))
    model_id: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(30), default="pending_review", index=True)
    context_hash: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    records: Mapped[list] = mapped_column(JSON, default=list)
    source_map: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    __table_args__ = (
        CheckConstraint("purpose IN ('analyze','notes','draft')"),
        CheckConstraint(
            "state IN ('pending_review','running','completed','completed_stale','failed','outcome_unknown','expired')"
        ),
    )


class CallPlan(Base):
    __tablename__ = "call_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    context_hash: Mapped[str] = mapped_column(String(64))
    opener: Mapped[Optional[str]] = mapped_column(Text)
    talking_points: Mapped[list] = mapped_column(JSON, default=list)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    guardrails: Mapped[list] = mapped_column(JSON, default=list)
    internal_only: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100), default="grounded-local-prep-v1")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class WorkspaceMerge(Base):
    __tablename__ = "workspace_merges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(300))
    snapshot_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="prepared")
    plan: Mapped[list] = mapped_column(JSON, default=list)
    mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())


class SuggestedAction(Base):
    """A reply-derived suggestion that only Jason can confirm.

    The classifier never changes a stage or adds a suppression by itself; it writes
    one of these rows and the briefing shows it with a confirm button.
    """

    __tablename__ = "suggested_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[Optional[int]] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    classification: Mapped[Optional[str]] = mapped_column(String(30), index=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    evidence: Mapped[Optional[str]] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    __table_args__ = (CheckConstraint("status IN ('pending','confirmed','dismissed')"),)
