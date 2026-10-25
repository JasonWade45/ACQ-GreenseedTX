from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator

OUTCOMES = [
    "Connected",
    "No Answer",
    "Left Voicemail",
    "Callback Requested",
    "Wrong Number",
    "Do Not Contact",
    "Seller Not Interested",
    "Appointment Scheduled",
    "Offer Accepted",
    "Offer Rejected",
    "Administrative / No Contact",
    "Other",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoteIn(StrictModel):
    summary: str = Field(min_length=1, max_length=20000)
    activity_type: Literal["note", "call", "offer", "appointment_result"] = "note"
    outcome: str | None = None
    occurred_at: datetime | None = None
    confirm: bool = False

    @field_validator("outcome")
    @classmethod
    def valid_outcome(cls, v):
        if v and v not in OUTCOMES:
            raise ValueError("Choose an actual outcome")
        return v


class FollowupIn(StrictModel):
    lead_id: int
    due_at: datetime | None = None
    priority: int = Field(default=50, ge=0, le=100)
    reason: str = Field(min_length=1, max_length=3000)
    suggested_action: str | None = Field(default=None, max_length=3000)
    property_id: int | None = None


class FollowupAction(StrictModel):
    action: Literal["complete", "reschedule", "cancel"]
    outcome: str | None = None
    due_at: datetime | None = None
    note: str = Field(default="", max_length=10000)
    confirm: bool = False

    @field_validator("outcome")
    @classmethod
    def valid_outcome(cls, v):
        if v and v not in OUTCOMES:
            raise ValueError("Choose an actual outcome")
        return v


class StageIn(StrictModel):
    stage_code: str
    confirm: bool


class RestrictionIn(StrictModel):
    restricted: bool
    evidence: str = Field(min_length=5, max_length=3000)
    confirm: bool


class AppointmentIn(StrictModel):
    lead_id: int
    starts_at: datetime
    notes: str = Field(default="", max_length=5000)


class AppointmentResult(StrictModel):
    result: Literal["kept", "not_kept", "no_answer", "dismissed", "cancelled"]
    note: str = Field(default="", max_length=5000)
    confirm: bool


class MappingIn(StrictModel):
    sheets: list[str]
    mapping: dict[str, str]
    date_order: Literal["reject", "MDY", "DMY"] = "reject"
    template_name: str | None = Field(default=None, max_length=150)


class ImportApproval(StrictModel):
    fill_missing: bool = False
    row_ids: list[int] = Field(max_length=50000)
    resolutions: dict[str, Literal["skip", "separate", "link"]] = Field(default_factory=dict)
    confirmation: str
    destination: Literal["local"] = "local"


class DraftIn(StrictModel):
    regenerate: bool = False


class DraftEdit(StrictModel):
    body: str = Field(min_length=1, max_length=8000)


class BulkIn(StrictModel):
    lead_ids: list[int] = Field(max_length=1000)
    stage_code: str
    confirm: bool


class SettingsIn(StrictModel):
    stage_mapping: dict[str, str] | None = None
    priority_rules: dict[str, int] | None = None


class SchedulerIn(StrictModel):
    enabled: bool
    interval_minutes: int = Field(default=30, ge=1, le=10080)


class LoginIn(StrictModel):
    password: str = Field(max_length=1000)


class PipelineCreate(StrictModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    label: str = Field(min_length=1, max_length=100)


class PipelineRename(StrictModel):
    label: str = Field(min_length=1, max_length=100)
