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


def initialize_defaults(db):
    for position, (code, label) in enumerate(STAGES):
        if not db.get(PipelineStage, code):
            db.add(PipelineStage(code=code, label=label, position=position))
    if not db.get(AppSetting, "stage_mapping"):
        mapping = {code: code for code, _ in STAGES}
        mapping.update({label.lower(): code for code, label in STAGES})
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
