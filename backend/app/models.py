"""Database schema.

Normalized seller-lead model for the acquisitions assistant. REsimpli remains
the external source of truth; this database is a local read-model plus local
work-queue / AI layer. `external_id` values preserve REsimpli ObjectIds.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


# --------------------------------------------------------------------------- #
# Core CRM records
# --------------------------------------------------------------------------- #
class Lead(Base, TimestampMixin):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_stage", "pipeline_stage"),
        Index("ix_leads_contact_status", "contact_status"),
        Index("ix_leads_source", "lead_source"),
        Index("ix_leads_manager", "assigned_manager"),
        Index("ix_leads_next_followup", "next_followup_at"),
        Index("ix_leads_phone_norm", "phone_normalized"),
        Index("ix_leads_email_norm", "email_normalized"),
        Index("ix_leads_origin", "origin"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    external_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(120))
    last_name: Mapped[Optional[str]] = mapped_column(String(120))
    full_name: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    primary_phone: Mapped[Optional[str]] = mapped_column(String(40))
    phone_normalized: Mapped[Optional[str]] = mapped_column(String(20))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    email_normalized: Mapped[Optional[str]] = mapped_column(String(255))
    lead_source: Mapped[Optional[str]] = mapped_column(String(120))
    original_creation_date: Mapped[Optional[date]] = mapped_column(Date)
    pipeline_stage: Mapped[str] = mapped_column(String(40), default="new", nullable=False)
    source_status: Mapped[Optional[str]] = mapped_column(String(120))
    contact_status: Mapped[str] = mapped_column(String(40), default="never_contacted", nullable=False)
    assigned_manager: Mapped[Optional[str]] = mapped_column(String(160))
    last_contact_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    next_followup_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_hot_lead: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tags: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    # provenance
    origin: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)  # resimpli|import|manual|seed
    import_batch_id: Mapped[Optional[str]] = mapped_column(String(32), ForeignKey("import_batches.id"), nullable=True)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    analysis_input_hash: Mapped[Optional[str]] = mapped_column(String(64))

    properties: Mapped[list["LeadProperty"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", lazy="selectin"
    )
    activities: Mapped[list["Activity"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", order_by="Activity.occurred_at.desc()"
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", order_by="Appointment.scheduled_at.desc()"
    )
    followups: Mapped[list["Followup"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", order_by="Followup.due_at.asc()"
    )
    insights: Mapped[list["AiInsight"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", order_by="AiInsight.created_at.desc()"
    )
    drafts: Mapped[list["MessageDraft"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", order_by="MessageDraft.created_at.desc()"
    )
    call_plans: Mapped[list["CallPlan"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", order_by="CallPlan.created_at.desc()"
    )

    @property
    def display_name(self) -> str:
        if self.full_name:
            return self.full_name
        return " ".join(p for p in (self.first_name, self.last_name) if p) or "(no name)"


class Property(Base, TimestampMixin):
    __tablename__ = "properties"
    __table_args__ = (Index("ix_properties_address_norm", "address_normalized"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    external_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    address_line1: Mapped[Optional[str]] = mapped_column(String(255))
    address_line2: Mapped[Optional[str]] = mapped_column(String(255))
    city: Mapped[Optional[str]] = mapped_column(String(120))
    state: Mapped[Optional[str]] = mapped_column(String(40))
    zip_code: Mapped[Optional[str]] = mapped_column(String(20))
    address_normalized: Mapped[Optional[str]] = mapped_column(String(400))
    property_type: Mapped[Optional[str]] = mapped_column(String(60))
    bedrooms: Mapped[Optional[float]] = mapped_column(Float)
    bathrooms: Mapped[Optional[float]] = mapped_column(Float)
    square_footage: Mapped[Optional[float]] = mapped_column(Float)
    year_built: Mapped[Optional[int]] = mapped_column(Integer)
    county: Mapped[Optional[str]] = mapped_column(String(120))
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    lot_acres: Mapped[Optional[float]] = mapped_column(Float)
    asking_price: Mapped[Optional[float]] = mapped_column(Float)
    estimated_value: Mapped[Optional[float]] = mapped_column(Float)
    repair_estimate: Mapped[Optional[float]] = mapped_column(Float)
    extra: Mapped[Optional[dict]] = mapped_column(JSON)

    leads: Mapped[list["LeadProperty"]] = relationship(
        back_populates="property", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def formatted_address(self) -> str:
        parts = [self.address_line1, self.address_line2]
        city_state = ", ".join(p for p in (self.city, self.state) if p)
        if city_state:
            parts.append(city_state)
        if self.zip_code:
            parts.append(self.zip_code)
        return ", ".join(p.strip() for p in parts if p and p.strip())


class LeadProperty(Base):
    __tablename__ = "lead_properties"
    __table_args__ = (UniqueConstraint("lead_id", "property_id", name="uq_lead_property"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[Optional[str]] = mapped_column(String(40))  # owner | seller | co_seller
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    lead: Mapped["Lead"] = relationship(back_populates="properties")
    property: Mapped["Property"] = relationship(back_populates="leads")


# --------------------------------------------------------------------------- #
# Activities / appointments / follow-ups
# --------------------------------------------------------------------------- #
class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        Index("ix_activities_lead", "lead_id"),
        Index("ix_activities_occurred", "occurred_at"),
        Index("ix_activities_outcome", "outcome"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    external_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    lead_id: Mapped[Optional[str]] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[Optional[str]] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"))
    activity_type: Mapped[Optional[str]] = mapped_column(String(60))  # call|text|email|note|task|status_change|other
    direction: Mapped[Optional[str]] = mapped_column(String(20))  # inbound|outbound|internal
    outcome: Mapped[Optional[str]] = mapped_column(String(60))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    recorded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(20), default="local", nullable=False)  # resimpli|local|import
    summary: Mapped[Optional[str]] = mapped_column(Text)
    detail: Mapped[Optional[str]] = mapped_column(Text)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    lead: Mapped[Optional["Lead"]] = relationship(back_populates="activities")


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        Index("ix_appointments_lead", "lead_id"),
        Index("ix_appointments_scheduled", "scheduled_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    external_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    lead_id: Mapped[Optional[str]] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[Optional[str]] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(40), default="scheduled", nullable=False)
    appointment_type: Mapped[Optional[str]] = mapped_column(String(60))
    appointment_subtype: Mapped[Optional[str]] = mapped_column(String(60))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="local", nullable=False)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    lead: Mapped[Optional["Lead"]] = relationship(back_populates="appointments")


class Followup(Base):
    __tablename__ = "followups"
    __table_args__ = (
        Index("ix_followups_status_due", "status", "due_at"),
        Index("ix_followups_lead", "lead_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    property_id: Mapped[Optional[str]] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"))
    due_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)  # 1 low .. 5 urgent
    reason: Mapped[Optional[str]] = mapped_column(String(255))
    suggested_next_action: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)  # open|completed|cancelled
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completion_outcome: Mapped[Optional[str]] = mapped_column(String(60))
    completion_notes: Mapped[Optional[str]] = mapped_column(Text)
    creation_source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)  # manual|ai|rule|import|sync
    ai_suggested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    lead: Mapped["Lead"] = relationship(back_populates="followups")


# --------------------------------------------------------------------------- #
# AI layer
# --------------------------------------------------------------------------- #
class AiInsight(Base):
    __tablename__ = "ai_insights"
    __table_args__ = (Index("ix_ai_insights_lead", "lead_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    seller_motivation: Mapped[Optional[str]] = mapped_column(Text)
    urgency_indicators: Mapped[Optional[list]] = mapped_column(JSON)
    price_information: Mapped[Optional[dict]] = mapped_column(JSON)
    objections: Mapped[Optional[list]] = mapped_column(JSON)
    missing_information: Mapped[Optional[list]] = mapped_column(JSON)
    recommended_next_action: Mapped[Optional[str]] = mapped_column(Text)
    suggested_followup_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    evidence: Mapped[Optional[list]] = mapped_column(JSON)
    confidence: Mapped[Optional[str]] = mapped_column(String(20))  # low|medium|high
    engine: Mapped[str] = mapped_column(String(20), default="rules", nullable=False)  # rules|ollama
    model: Mapped[Optional[str]] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    lead: Mapped["Lead"] = relationship(back_populates="insights")


class MessageDraft(Base):
    __tablename__ = "message_drafts"
    __table_args__ = (Index("ix_message_drafts_lead", "lead_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    channel_hint: Mapped[str] = mapped_column(String(20), default="text", nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    context_used: Mapped[Optional[list]] = mapped_column(JSON)
    refusal_reason: Mapped[Optional[str]] = mapped_column(Text)
    engine: Mapped[str] = mapped_column(String(20), default="rules", nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(120))
    edited_body: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    lead: Mapped["Lead"] = relationship(back_populates="drafts")


class CallPlan(Base):
    """Pre-call script + question checklist for a lead. Advisory only; never sent."""

    __tablename__ = "call_plans"
    __table_args__ = (Index("ix_call_plans_lead", "lead_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    opener: Mapped[Optional[str]] = mapped_column(Text)
    talking_points: Mapped[Optional[list]] = mapped_column(JSON)  # [{"text": str, "used": bool}]
    questions: Mapped[Optional[list]] = mapped_column(JSON)  # [{"text": str, "asked": bool, "required": bool}]
    do_not_say: Mapped[Optional[list]] = mapped_column(JSON)  # [str]
    context_used: Mapped[Optional[list]] = mapped_column(JSON)
    refusal_reason: Mapped[Optional[str]] = mapped_column(Text)
    engine: Mapped[str] = mapped_column(String(20), default="rules", nullable=False)  # rules|ollama|groq
    model: Mapped[Optional[str]] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    lead: Mapped["Lead"] = relationship(back_populates="call_plans")


# --------------------------------------------------------------------------- #
# Import / sync / audit / settings
# --------------------------------------------------------------------------- #
class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    checksum: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    sheet_name: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="preview", nullable=False)
    # preview | committed | failed | skipped_duplicate_file | partially_committed
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    records: Mapped[list["ImportRecord"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="ImportRecord.row_number"
    )


class ImportRecord(Base):
    __tablename__ = "import_records"
    __table_args__ = (
        Index("ix_import_records_batch_status", "batch_id", "status"),
        UniqueConstraint("batch_id", "row_number", name="uq_batch_row"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    # new|likely_duplicate|exact_duplicate|same_seller_diff_property|
    # same_property_diff_seller|existing_resimpli|rejected|imported|failed|skipped
    reason: Mapped[Optional[str]] = mapped_column(String(400))
    payload: Mapped[Optional[dict]] = mapped_column(JSON)
    warnings: Mapped[Optional[list]] = mapped_column(JSON)
    lead_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    external_ref: Mapped[Optional[str]] = mapped_column(String(120))
    error: Mapped[Optional[str]] = mapped_column(Text)

    batch: Mapped["ImportBatch"] = relationship(back_populates="records")


class MappingTemplate(Base):
    __tablename__ = "mapping_templates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    columns: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (Index("ix_sync_runs_started", "started_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    result: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    # running|success|partial|failed
    trigger: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    records_fetched: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text)
    detail: Mapped[Optional[dict]] = mapped_column(JSON)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_created", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(40))
    entity_id: Mapped[Optional[str]] = mapped_column(String(64))
    detail: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
