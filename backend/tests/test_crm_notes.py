"""The note that travels with a new lead: stable prefix, opt-in fields, one copy per fact set."""

import pytest
from sqlalchemy import select

from app.models import CrmNoteOutbox
from app.services.crm_notes import (
    ensure_note,
    flag_names,
    note_for_existing_lead,
    note_for_new_lead,
    note_hash,
    notes_for_lead,
    priority_reasons,
    structured_note,
)
from app.services.crm_push import PushSettings


@pytest.fixture
def note_settings():
    return PushSettings()


@pytest.fixture
def lead_with_facts(make_lead, db):
    lead = make_lead("Dana Reyes")
    lead.lead_type = "Tax Deed Sale"
    lead.equity_pct = 12.5
    lead.score = 87.1
    lead.heat = "HOT"
    lead.priority_tier = "P2"
    lead.ds_flags = {"free_and_clear": True, "high_equity": True, "sleeper": False}
    lead.ds_extra_flags = ["Vendor Specific Flag"]
    lead.assigned_manager = "Demo Manager"
    lead.lead_source = "Fictional website lead"
    db.commit()
    return lead


def test_the_note_starts_with_the_stable_prefix(lead_with_facts, note_settings):
    text = structured_note(lead_with_facts, note_settings)
    assert text.startswith("[GreenSeed]")
    assert "No message was sent to the seller" in text


def test_property_facts_are_included_by_default(lead_with_facts, note_settings):
    text = structured_note(lead_with_facts, note_settings)
    assert "Lead type: Tax Deed Sale" in text
    assert "Estimated equity: 12.5%" in text
    assert "Flags: free and clear, high equity, Vendor Specific Flag" in text
    assert "sleeper" not in text, "a false flag is not reported as present"
    assert "Priority:" in text


def test_owner_contact_is_excluded_until_it_is_turned_on(lead_with_facts, note_settings):
    default = structured_note(lead_with_facts, note_settings)
    assert "Dana Reyes" not in default and "2025550199" not in default
    opted_in = note_settings.model_copy(update={"note_fields": {**note_settings.note_fields, "owner_contact": True}})
    text = structured_note(lead_with_facts, opted_in)
    assert "Owner contact: Dana Reyes | +12025550199" in text


def test_internal_fields_are_excluded_until_they_are_turned_on(lead_with_facts, note_settings):
    assert "Demo Manager" not in structured_note(lead_with_facts, note_settings)
    opted_in = note_settings.model_copy(update={"note_fields": {**note_settings.note_fields, "internal": True}})
    assert "Internal: Demo Manager" in structured_note(lead_with_facts, opted_in)


def test_each_group_can_be_switched_off(lead_with_facts, note_settings):
    quiet = note_settings.model_copy(
        update={
            "note_fields": {
                "equity": False,
                "flags": False,
                "lead_type": False,
                "priority": False,
                "owner_contact": False,
                "internal": False,
            }
        }
    )
    text = structured_note(lead_with_facts, quiet)
    for absent in ("Tax Deed Sale", "Estimated equity", "Flags:", "Priority:"):
        assert absent not in text


def test_priority_reasons_name_the_thresholds_that_were_met(lead_with_facts):
    reasons = priority_reasons(lead_with_facts)
    assert "P2 tier" in reasons
    assert "equity 12.5% is below the 20% threshold" in reasons
    assert "lead type Tax Deed Sale" in reasons


def test_unknown_flags_are_kept_verbatim(lead_with_facts):
    assert "Vendor Specific Flag" in flag_names(lead_with_facts)


def test_an_address_only_lead_says_it_still_needs_a_skip_trace(make_lead, db, note_settings):
    lead = make_lead("No Phone Seller", phone=None)
    lead.needs_skip_trace = True
    db.commit()
    text = structured_note(lead, note_settings)
    assert "Address-only lead" in text


def test_the_same_facts_produce_the_same_note_and_one_row(db, lead_with_facts, note_settings):
    first = ensure_note(db, lead_with_facts, note_settings)
    db.commit()
    second = ensure_note(db, lead_with_facts, note_settings)
    db.commit()
    assert first.id == second.id
    assert first.note_hash == note_hash(first.body)
    assert len(db.scalars(select(CrmNoteOutbox)).all()) == 1


def test_a_changed_fact_produces_a_new_note(db, lead_with_facts, note_settings):
    ensure_note(db, lead_with_facts, note_settings)
    db.commit()
    lead_with_facts.equity_pct = 64.0
    db.commit()
    ensure_note(db, lead_with_facts, note_settings)
    db.commit()
    rows = db.scalars(select(CrmNoteOutbox)).all()
    assert len(rows) == 2, "a note that says something different is a different note"


def test_an_ai_summary_is_labelled_as_a_draft(lead_with_facts, note_settings):
    text = structured_note(lead_with_facts, note_settings, ai_summary="Owner may be motivated by tax arrears.")
    assert "AI summary (draft, reviewed by a person): Owner may be motivated" in text


def test_the_note_is_capped_at_the_stored_limit(lead_with_facts, note_settings):
    text = structured_note(lead_with_facts, note_settings, ai_summary="x" * 5000)
    assert len(text) <= 2000


def test_a_note_for_an_existing_lead_is_kept_and_explained(db, lead_with_facts, note_settings):
    result = note_for_existing_lead(db, lead_with_facts, note_settings)
    assert result["state"] == "blocked"
    assert "no note endpoint" in result["reason"]
    rows = notes_for_lead(db, lead_with_facts.id)
    assert len(rows) == 1 and rows[0]["state"] == "blocked"


def test_the_note_for_a_new_lead_is_the_text_that_is_sent(db, lead_with_facts, note_settings):
    text = note_for_new_lead(db, lead_with_facts, note_settings)
    rows = notes_for_lead(db, lead_with_facts.id)
    assert rows[0]["body"] == text
    assert rows[0]["state"] == "pending", "delivery is recorded by the push, not by the note builder"
