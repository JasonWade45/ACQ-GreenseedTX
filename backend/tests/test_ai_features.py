"""The three AI jobs, against a stub client: drafts, suggestions and advice.

No network is involved and no real key exists here. The stub records the prompt so the
tests can assert what the model was told -- and, just as importantly, what it was not.
"""

import json

import pytest
from sqlalchemy import select

from app.config import Settings
from app.models import AiChecklistSuggestion, AuditLog, GrokRun, LeadChecklistItem, Message
from app.services.ai_features import (
    ADVISOR_DISCLAIMER,
    ADVISOR_SCHEMA,
    COMPLIANCE_REMINDER,
    advise,
    decide_suggestion,
    draft_followup,
    enabled_fields,
    latest_advice,
    lead_facts,
    suggest_checklist,
    suggestions_for,
)
from app.services.ai_grok import GrokError, GrokResult
from app.services.templates import OPT_OUT_LINE


def ai_settings(**extra):
    values = {
        "groq_enabled": False,
        "grok_enabled": True,
        "grok_api_key": "xai-not-a-real-key-000000000000",
        "grok_daily_request_limit": 5,
        "grok_advisor_model": "grok-4.7",
        "grok_followup_model": "grok-4.3",
        "draft_manager_name": "Jason Wade",
        "draft_company": "GreenSeedTX LLC",
        "sender_name": "Jason Wade",
        "company_name": "GreenSeedTX LLC",
        **extra,
    }
    return Settings(_env_file=None, **values)


class Stub:
    """A stand-in for GrokClient that answers with prepared JSON and records the prompt."""

    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.prompts = []
        self.closed = False

    def complete(self, *, purpose, prompt, schema=None, name=None, model=None):
        self.prompts.append({"purpose": purpose, "prompt": prompt, "name": name})
        payload = self.payloads.pop(0) if self.payloads else {}
        return GrokResult(
            text=json.dumps(payload),
            data=payload,
            api="responses",
            model="grok-4.7" if purpose == "advisor" else "grok-4.3",
            input_tokens=400,
            output_tokens=120,
            duration_ms=12,
            request_preview={"api": "responses", "model": "grok-4.3", "body": {"input": "…"}},
        )

    def close(self):
        self.closed = True


def followup_body(**extra):
    body = (
        f"Hi Dana, thanks for the call about the arrears. Would Thursday work for a short walkthrough? "
        f"Jason Wade with GreenSeedTX LLC. {OPT_OUT_LINE}"
    )
    return {"body": body, "reasoning": "The last call ended with a question about the timeline.", "used": ["contact_history"], **extra}


def checklist_body(count=3):
    return {"items": [{"title": f"Check item {index}", "detail": f"Detail {index}"} for index in range(count)]}


def advisor_body(**extra):
    return {
        "situation_summary": "Owner has tax arrears and has spoken with us once.",
        "next_steps": ["Confirm the payoff amount", "Ask about the timeline", "Verify occupancy"],
        "do_not": ["Do not quote a price", "Do not promise a closing date"],
        "risks": ["Arrears may exceed equity", "Owner may be speaking with other buyers"],
        "exit_strategy": {
            "name": "Subject-to",
            "reasoning": "The existing loan is assumable and the arrears are small.",
            "missing_information": ["Loan balance", "Interest rate"],
        },
        "confidence": "medium",
        **extra,
    }


# --- facts ------------------------------------------------------------------------


def test_only_the_allowed_fields_are_assembled(db, make_lead):
    lead = make_lead("Dana Reyes")
    lead.lead_type = "Tax Deed Sale"
    lead.equity_pct = 55.0
    db.commit()
    narrow = ai_settings(grok_ai_fields="lead_type")
    facts = lead_facts(db, lead, narrow)
    assert set(facts) == {"lead_type"}, "a field that is switched off is never even read"
    broad = lead_facts(db, lead, ai_settings())
    assert "property_address" in broad and "priority" in broad
    assert "conversation" not in broad, "conversation text is opt-in"


def test_enabled_fields_fall_back_to_the_documented_defaults():
    assert "property_address" in enabled_fields(ai_settings(grok_ai_fields=""))
    assert enabled_fields(ai_settings(grok_ai_fields="nonsense")) == enabled_fields(ai_settings(grok_ai_fields=""))


# --- Feature 1: follow-up draft ---------------------------------------------------


def test_a_followup_draft_is_validated_and_queued_for_copy(db, make_lead):
    lead = make_lead("Dana Reyes")
    stub = Stub(followup_body())
    result = draft_followup(db, ai_settings(), lead, client=stub)
    assert result["copy_only"] is True
    assert result["validator_result"]["ok"] is True
    assert result["model"] == "grok-4.3"
    record = db.get(Message, result["id"])
    assert record.status == "DRAFT" and record.direction == "outbound"
    run = db.scalar(select(GrokRun).where(GrokRun.purpose == "followup_draft"))
    assert run is not None and run.state == "succeeded"
    assert run.input_hash == result["input_hash"]
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "draft_prepared"))
    assert audit.details["never_sent"] is True and "body" not in json.dumps(audit.details)


def test_a_draft_that_breaks_the_content_rules_is_still_shown_with_its_reasons(db, make_lead):
    lead = make_lead("Dana Reyes")
    bad = {"body": "Hi Dana, call me. Jason Wade with GreenSeedTX LLC.", "reasoning": "x", "used": []}
    result = draft_followup(db, ai_settings(), lead, client=Stub(bad))
    assert result["validator_result"]["ok"] is False
    assert any("opt-out" in reason for reason in result["validator_result"]["reasons"])
    assert db.get(Message, result["id"]) is not None, "a rejected draft is visible, not silently dropped"


def test_a_do_not_contact_lead_never_reaches_the_model(db, make_lead):
    lead = make_lead("Dana Reyes")
    lead.local_do_not_contact = True
    db.commit()
    stub = Stub(followup_body())
    with pytest.raises(ValueError, match="do-not-contact"):
        draft_followup(db, ai_settings(), lead, client=stub)
    assert stub.prompts == []


def test_a_cold_lead_keeps_the_cold_gates(db, make_lead):
    lead = make_lead("Dana Reyes")
    lead.outreach_mode = "cold"
    lead.needs_skip_trace = True
    db.commit()
    with pytest.raises(ValueError, match="skip trace"):
        draft_followup(db, ai_settings(), lead, client=Stub(followup_body()))


def test_the_daily_cap_stops_the_call_before_it_is_made(db, make_lead):
    lead = make_lead("Dana Reyes")
    settings = ai_settings(grok_daily_request_limit=1)
    from app.services.ai_grok import record_run

    record_run(db, run_id="used-1", lead_id=lead.id, purpose="advisor", input_hash="a" * 64, model="grok-4.7", error="x")
    db.commit()
    stub = Stub(followup_body())
    with pytest.raises(GrokError) as error:
        draft_followup(db, settings, lead, client=stub)
    assert error.value.code == "daily_cap_reached"
    assert stub.prompts == []


def test_a_switch_off_grok_reports_it_without_calling_anything(db, make_lead):
    lead = make_lead("Dana Reyes")
    with pytest.raises(GrokError) as error:
        draft_followup(db, ai_settings(grok_enabled=False), lead, client=Stub(followup_body()))
    assert error.value.code == "not_configured"


# --- Feature 2: checklist suggestions ---------------------------------------------


def test_suggestions_are_pending_until_a_person_decides(db, make_lead):
    lead = make_lead("Dana Reyes")
    result = suggest_checklist(db, ai_settings(), lead, client=Stub(checklist_body(3)))
    assert len(result["suggestions"]) == 3
    assert result["accept_each"] is True
    ai_items = [row for row in db.scalars(select(LeadChecklistItem)).all() if row.source == "ai"]
    assert ai_items == [], "a suggestion is not a task until accepted"
    assert {row.status for row in db.scalars(select(AiChecklistSuggestion)).all()} == {"pending"}
    assert [item["status"] for item in suggestions_for(db, lead.id)] == ["pending", "pending", "pending"]


def test_each_suggestion_can_be_accepted_or_rejected_on_its_own(db, make_lead):
    lead = make_lead("Dana Reyes")
    result = suggest_checklist(db, ai_settings(), lead, client=Stub(checklist_body(2)))
    first, second = result["suggestions"]
    accepted = decide_suggestion(db, first["id"], True)
    rejected = decide_suggestion(db, second["id"], False)
    assert accepted["status"] == "accepted" and accepted["checklist_item_id"]
    assert rejected["status"] == "rejected" and rejected["checklist_item_id"] is None
    items = [row for row in db.scalars(select(LeadChecklistItem)).all() if row.source == "ai"]
    assert len(items) == 1 and items[0].title == "Check item 0"
    with pytest.raises(ValueError, match="already"):
        decide_suggestion(db, first["id"], True)


def test_the_suggestion_limit_is_enforced(db, make_lead):
    lead = make_lead("Dana Reyes")
    result = suggest_checklist(db, ai_settings(), lead, client=Stub(checklist_body(12)))
    assert len(result["suggestions"]) == 8


# --- Feature 3: the advisor -------------------------------------------------------


def test_advice_is_stored_with_its_model_hash_and_labels(db, make_lead):
    lead = make_lead("Dana Reyes")
    result = advise(db, ai_settings(), lead, client=Stub(advisor_body()))
    assert result["decision_support_only"] is True
    assert result["disclaimer"] == ADVISOR_DISCLAIMER
    assert result["compliance"] == COMPLIANCE_REMINDER
    assert "not legal advice" in COMPLIANCE_REMINDER
    row = db.get(GrokRun, result["run_id"])
    assert row.model_id == "grok-4.7" and row.input_hash and row.created_at
    assert row.output["advice"]["exit_strategy"]["name"] == "Subject-to"
    stored = latest_advice(db, lead.id)
    assert stored["advice"]["confidence"] == "medium"
    assert stored["disclaimer"] == ADVISOR_DISCLAIMER


def test_advice_that_does_not_fit_the_schema_is_retried_once_then_refused(db, make_lead):
    lead = make_lead("Dana Reyes")
    stub = Stub(advisor_body(confidence="certain"), advisor_body(confidence="certain"))
    with pytest.raises(GrokError) as error:
        advise(db, ai_settings(), lead, client=stub)
    assert error.value.code == "schema_invalid"
    assert len(stub.prompts) == 2
    runs = db.scalars(select(GrokRun)).all()
    assert [row.state for row in runs] == ["invalid"]
    assert latest_advice(db, lead.id) is None


def test_a_schema_failure_on_the_first_attempt_can_succeed_on_the_retry(db, make_lead):
    lead = make_lead("Dana Reyes")
    stub = Stub({"situation_summary": "partial"}, advisor_body())
    result = advise(db, ai_settings(), lead, client=stub)
    assert result["advice"]["confidence"] == "medium"
    assert len(stub.prompts) == 2


def test_the_advisor_schema_is_strict_at_every_level():
    def assert_strict(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
            for value in node.values():
                assert_strict(value)
        elif isinstance(node, list):
            for value in node:
                assert_strict(value)

    assert_strict(ADVISOR_SCHEMA)


def test_the_prompt_never_carries_the_phone_or_email(db, make_lead):
    lead = make_lead("Dana Reyes")
    stub = Stub(followup_body())
    draft_followup(db, ai_settings(), lead, client=stub)
    prompt = stub.prompts[0]["prompt"]
    assert "2025550199" not in prompt and "@" not in prompt
