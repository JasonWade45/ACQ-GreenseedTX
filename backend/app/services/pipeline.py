"""Pipeline stages, contact outcomes, default business settings.

The pipeline stage (where the deal is) is deliberately kept separate from the
contact outcome (what happened on the last outreach) and from follow-up status.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

# --------------------------------------------------------------------------- #
# Stages
# --------------------------------------------------------------------------- #
STAGE_ORDER = [
    "new",
    "not_contacted",
    "attempting_contact",
    "contacted",
    "qualified",
    "follow_up",
    "appointment_set",
    "offer_made",
    "negotiation",
    "contract_sent",
    "under_contract",
    "closed",
    "nurture",
    "dead",
]

STAGES: dict[str, dict[str, Any]] = {
    "new": {"label": "New", "order": 1, "color": "slate", "implies_contact": False, "active_deal": True},
    "not_contacted": {"label": "Not Contacted", "order": 2, "color": "gray", "implies_contact": False, "active_deal": True},
    "attempting_contact": {"label": "Attempting Contact", "order": 3, "color": "amber", "implies_contact": False, "active_deal": True},
    "contacted": {"label": "Contacted", "order": 4, "color": "blue", "implies_contact": True, "active_deal": True},
    "qualified": {"label": "Qualified", "order": 5, "color": "cyan", "implies_contact": True, "active_deal": True},
    "follow_up": {"label": "Follow-up", "order": 6, "color": "indigo", "implies_contact": True, "active_deal": True},
    "appointment_set": {"label": "Appointment Set", "order": 7, "color": "violet", "implies_contact": True, "active_deal": True},
    "offer_made": {"label": "Offer Made", "order": 8, "color": "purple", "implies_contact": True, "active_deal": True},
    "negotiation": {"label": "Negotiation", "order": 9, "color": "fuchsia", "implies_contact": True, "active_deal": True},
    "contract_sent": {"label": "Contract Sent", "order": 10, "color": "pink", "implies_contact": True, "active_deal": True},
    "under_contract": {"label": "Under Contract", "order": 11, "color": "emerald", "implies_contact": True, "active_deal": True},
    "closed": {"label": "Closed", "order": 12, "color": "green", "implies_contact": True, "active_deal": False},
    "nurture": {"label": "Nurture", "order": 13, "color": "teal", "implies_contact": True, "active_deal": False},
    "dead": {"label": "Dead / Disqualified", "order": 14, "color": "red", "implies_contact": False, "active_deal": False},
}

# Default mapping from a raw REsimpli / import status name to a local stage key.
# Source values are always preserved on the lead as `source_status`.
DEFAULT_STAGE_MAPPING: dict[str, str] = {
    "new": "new",
    "new lead": "new",
    "new leads": "new",
    "lead": "new",
    "not contacted": "not_contacted",
    "uncontacted": "not_contacted",
    "attempting contact": "attempting_contact",
    "attempting to contact": "attempting_contact",
    "attempt": "attempting_contact",
    "in progress": "attempting_contact",
    "contacted": "contacted",
    "contact made": "contacted",
    "contacted - not qualified": "contacted",
    "reached": "contacted",
    "qualified": "qualified",
    "qualified lead": "qualified",
    "seller qualified": "qualified",
    "follow up": "follow_up",
    "follow-up": "follow_up",
    "followup": "follow_up",
    "needs follow up": "follow_up",
    "appointment set": "appointment_set",
    "appointment": "appointment_set",
    "appointment scheduled": "appointment_set",
    "appointment booked": "appointment_set",
    "showing": "appointment_set",
    "offer made": "offer_made",
    "offer": "offer_made",
    "offer sent": "offer_made",
    "offer pending": "offer_made",
    "negotiation": "negotiation",
    "negotiating": "negotiation",
    "counter offer": "negotiation",
    "contract sent": "contract_sent",
    "contract": "contract_sent",
    "pending contract": "contract_sent",
    "under contract": "under_contract",
    "pending": "under_contract",
    "in escrow": "under_contract",
    "closed": "closed",
    "closed won": "closed",
    "sold": "closed",
    "complete": "closed",
    "nurture": "nurture",
    "long term": "nurture",
    "dead": "dead",
    "dead lead": "dead",
    "dead leads": "dead",
    "disqualified": "dead",
    "not qualified": "dead",
    "lost": "dead",
}

# --------------------------------------------------------------------------- #
# Contact outcomes
# --------------------------------------------------------------------------- #
CONTACT_OUTCOMES: dict[str, dict[str, Any]] = {
    "never_contacted": {"label": "Never Contacted", "is_contact": False, "order": 0},
    "no_answer": {"label": "No Answer", "is_contact": False, "order": 2},
    "left_voicemail": {"label": "Left Voicemail", "is_contact": False, "order": 3},
    "connected": {"label": "Connected", "is_contact": True, "order": 5},
    "callback_requested": {"label": "Callback Requested", "is_contact": True, "order": 6},
    "wrong_number": {"label": "Wrong Number", "is_contact": False, "order": 1},
    "do_not_contact": {"label": "Do Not Contact", "is_contact": False, "order": 0},
    "seller_not_interested": {"label": "Seller Not Interested", "is_contact": True, "order": 4},
    "appointment_scheduled": {"label": "Appointment Scheduled", "is_contact": True, "order": 6},
    "other": {"label": "Other", "is_contact": True, "order": 1},
}

# Outcome value sets used when the user completes a follow-up / records a call.
COMPLETION_OUTCOMES = [
    "connected",
    "no_answer",
    "left_voicemail",
    "callback_requested",
    "seller_not_interested",
    "appointment_scheduled",
    "wrong_number",
    "do_not_contact",
    "other",
]

# Activity type -> (direction, outcome) hints when a REsimpli activity name is seen
ACTIVITY_TYPE_HINTS: dict[str, dict[str, Any]] = {
    "call": {"activity_type": "call"},
    "phone": {"activity_type": "call"},
    "inbound call": {"activity_type": "call", "direction": "inbound"},
    "outbound call": {"activity_type": "call", "direction": "outbound"},
    "text": {"activity_type": "text"},
    "sms": {"activity_type": "text"},
    "email": {"activity_type": "email"},
    "note": {"activity_type": "note", "direction": "internal"},
    "task": {"activity_type": "task", "direction": "internal"},
    "appointment": {"activity_type": "appointment"},
    "status change": {"activity_type": "status_change", "direction": "internal"},
}

OUTCOME_KEYWORDS: dict[str, str] = {
    "no answer": "no_answer",
    "no-answer": "no_answer",
    "noanswer": "no_answer",
    "vm": "left_voicemail",
    "voicemail": "left_voicemail",
    "left vm": "left_voicemail",
    "connected": "connected",
    "spoke": "connected",
    "talked": "connected",
    "callback": "callback_requested",
    "call back": "callback_requested",
    "wrong number": "wrong_number",
    "disconnected": "wrong_number",
    "do not call": "do_not_contact",
    "dnc": "do_not_contact",
    "not interested": "seller_not_interested",
    "appointment set": "appointment_scheduled",
    "appointment scheduled": "appointment_scheduled",
}


def map_stage(source_status: Optional[str], mapping: Optional[dict[str, str]] = None) -> str:
    """Map a source status name onto a local stage key, preserving the original."""
    if not source_status:
        return "new"
    key = source_status.strip().lower()
    table = {**DEFAULT_STAGE_MAPPING, **(mapping or {})}
    if key in table and table[key] in STAGES:
        return table[key]
    compact = key.replace("-", " ").replace("_", " ")
    compact = " ".join(compact.split())
    if compact in table and table[compact] in STAGES:
        return table[compact]
    for token, stage in table.items():
        if stage in STAGES and token and (token in key or key in token):
            return stage
    return "new"


def infer_outcome_from_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    low = text.lower()
    for keyword, outcome in OUTCOME_KEYWORDS.items():
        if keyword in low:
            return outcome
    return None


def contact_status_for_outcome(outcome: Optional[str]) -> Optional[str]:
    if outcome in CONTACT_OUTCOMES:
        return outcome
    return None


# --------------------------------------------------------------------------- #
# Default application settings (stored in app_settings table, editable)
# --------------------------------------------------------------------------- #
DEFAULT_FOLLOWUP_RULES: dict[str, Any] = {
    "callback_priority": 5,
    "overdue_priority": 4,
    "appointment_priority": 5,
    "negotiation_priority": 4,
    "offer_priority": 4,
    "new_lead_priority": 3,
    "default_priority": 3,
    # A brand-new lead that has never been contacted is surfaced for this many hours
    "new_lead_grace_hours": 4,
    # Days without movement before an open offer is flagged for attention
    "offer_response_attention_days": 3,
    # Days without movement before a negotiation is flagged
    "negotiation_attention_days": 2,
    # How far ahead the "upcoming" work-queue section looks
    "upcoming_lookahead_days": 14,
    # Stage keys that are expected to always have an open follow-up
    "unscheduled_stage_keys": [
        "contacted", "qualified", "follow_up", "appointment_set",
        "offer_made", "negotiation", "contract_sent",
    ],
    # Stage keys considered "active deals" for aging reports
    "aging_stage_keys": [s for s in STAGE_ORDER if STAGES[s]["active_deal"]],
    "require_confirm_on_complete": True,
    # Minimum data before a marketing draft may be generated
    "draft_min_context_fields": 1,
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "stage_mapping": {},
    "followup_rules": DEFAULT_FOLLOWUP_RULES,
    "ui": {
        "currency": "USD",
        "date_format": "MMM d, yyyy",
        "business_name": "Acquisitions Team",
    },
    "status_mapping_source": "built-in defaults (editable)",
    # Account ObjectIds used by /lead/add when an import also creates the lead
    # in REsimpli. Empty = fall back to import_service.KNOWN_LEAD_IDS.
    "resimpli_lead_ids": {},
}


def get_rule(rules: dict[str, Any], key: str) -> Any:
    return rules.get(key, DEFAULT_FOLLOWUP_RULES.get(key))


def now_in_tz(tz_name: str) -> datetime:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # pragma: no cover
        tz = ZoneInfo("UTC")
    return datetime.now(tz).replace(tzinfo=None)


def today_bounds(tz_name: str) -> tuple[datetime, datetime]:
    """Local day start/end for 'due today' comparisons (stored times are naive UTC)."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # pragma: no cover
        tz = ZoneInfo("UTC")
    local_now = datetime.now(tz)
    start_local = datetime.combine(local_now.date(), time.min)
    end_local = datetime.combine(local_now.date() + timedelta(days=1), time.min)
    return (
        start_local.astimezone(tz).astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
        end_local.astimezone(tz).astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
    )


def local_today(tz_name: str) -> date:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # pragma: no cover
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def clone_default_settings() -> dict[str, Any]:
    return deepcopy(DEFAULT_SETTINGS)
