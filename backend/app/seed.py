from .models import PipelineStage, AppSetting

STAGES = [
    ("new", "New"),
    ("not_contacted", "Not Contacted"),
    ("attempting_contact", "Attempting Contact"),
    ("contacted", "Contacted"),
    ("qualified", "Qualified"),
    ("follow_up", "Follow-up"),
    ("appointment_set", "Appointment Set"),
    ("offer_made", "Offer Made"),
    ("negotiation", "Negotiation"),
    ("contract_sent", "Contract Sent"),
    ("under_contract", "Under Contract"),
    ("closed", "Closed"),
    ("nurture", "Nurture"),
    ("dead", "Dead / Disqualified"),
    ("unmapped", "Unmapped source status"),
]


# Default readings of the status titles REsimpli accounts use. Only a starting point:
# any title not listed here stays "unmapped" and is shown for the user to decide.
SOURCE_STATUS_DEFAULTS = {
    "new lead": "new",
    "lead": "new",
    "new": "new",
    "not contacted": "not_contacted",
    "attempted contact": "attempting_contact",
    "attempting contact": "attempting_contact",
    "contacted": "contacted",
    "follow up": "follow_up",
    "follow-up": "follow_up",
    "qualified": "qualified",
    "appointment set": "appointment_set",
    "offer made": "offer_made",
    "negotiation": "negotiation",
    "contract sent": "contract_sent",
    "under contract": "under_contract",
    "closed": "closed",
    "sold": "closed",
    "nurture": "nurture",
    "dead lead": "dead",
    "dead": "dead",
    "not interested": "dead",
    "bad number": "dead",
    "do not call": "dead",
}


def initialize_defaults(db):
    for position, (code, label) in enumerate(STAGES):
        if not db.get(PipelineStage, code):
            db.add(PipelineStage(code=code, label=label, position=position))
    # A choice the user already made is never overwritten; missing defaults are added.
    setting = db.get(AppSetting, "stage_mapping")
    mapping = dict(setting.value) if setting else {}
    mapping.update({code: code for code, _ in STAGES if code not in mapping})
    mapping.update({label.lower(): code for code, label in STAGES if label.lower() not in mapping})
    mapping.update(
        {title: stage for title, stage in SOURCE_STATUS_DEFAULTS.items() if title not in mapping}
    )
    if setting:
        setting.value = mapping
    else:
        db.add(AppSetting(key="stage_mapping", value=mapping))
    if not db.get(AppSetting, "priority_rules"):
        db.add(
            AppSetting(
                key="priority_rules",
                value={
                    "callback_bonus": 30,
                    "negotiation_bonus": 20,
                    "appointment_bonus": 25,
                    "overdue_per_day": 2,
                    "new_lead_priority": 40,
                    "stale_after_days": 30,
                },
            )
        )
    db.commit()


def stage_mapping(db, source_status):
    setting = db.get(AppSetting, "stage_mapping")
    return setting.value.get(str(source_status).strip().lower(), "unmapped") if source_status else "new"


def record_source_status(db, source_status):
    """Remember the exact source titles so the mapping screen can show real ones."""
    title = (str(source_status).strip() if source_status not in (None, "") else "") or "(blank)"
    setting = db.get(AppSetting, "source_status_counts")
    counts = dict(setting.value) if setting else {}
    counts[title] = counts.get(title, 0) + 1
    if setting:
        setting.value = counts
    else:
        db.add(AppSetting(key="source_status_counts", value=counts))
