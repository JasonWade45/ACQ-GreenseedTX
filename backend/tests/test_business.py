from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from app.db import utcnow
from app.models import Followup, Activity, Lead, AppSetting
from app.schemas import FollowupAction
from app.services.leads import day_bounds, apply_contact_outcome, metric_clause, lead_query, set_stage
from app.services.operations import complete_followup, daily_queue, priority_for
from app.services.reporting import dashboard, reports, count_query
from app.services.ai import analyze_lead, generate_draft, infer_locally, ollama_status, AIUnavailable
from app.services.normalization import parse_datetime
from app.services.sync import upsert_lead


def test_pipeline_counts_are_real(db, make_lead):
    make_lead(source_status="Qualified")
    make_lead(name="Second", phone="+12025550198", source_status="New")
    values = {m["key"]: m["value"] for m in dashboard(db, {}, "America/New_York")["metrics"]}
    assert values["total"] == 2 and values["stage:qualified"] == 1 and values["stage:new"] == 1
    assert count_query(db, lead_query({"metric": "stage:qualified"}, "America/New_York")) == 1


def test_unknown_source_status_is_preserved(db, make_lead):
    lead = make_lead(source_status="Custom Seller Stage")
    assert lead.stage_code == "unmapped" and lead.source_status == "Custom Seller Stage"


def test_no_answer_is_not_contact(make_lead):
    lead = make_lead()
    apply_contact_outcome(lead, "No Answer", datetime.now(timezone.utc))
    assert lead.contact_status == "attempted" and lead.last_contact_at is None
    apply_contact_outcome(lead, "Connected", datetime.now(timezone.utc))
    assert lead.contact_status == "contacted" and lead.last_contact_at
    prior = lead.last_contact_at
    apply_contact_outcome(lead, "Left Voicemail", datetime.now(timezone.utc))
    assert lead.contact_status == "contacted" and lead.last_contact_at == prior


def test_admin_completion_does_not_fabricate_contact(db, make_lead):
    lead = make_lead()
    f = Followup(lead_id=lead.id, reason="Review missing information")
    db.add(f)
    db.commit()
    complete_followup(db, f, FollowupAction(action="complete", outcome="Administrative / No Contact", confirm=True))
    assert lead.contact_status == "unknown" and lead.last_contact_at is None
    assert f.status == "completed" and f.completion_outcome == "Administrative / No Contact"
    assert db.scalar(select(Activity)).source == "local"


def test_completion_requires_actual_outcome_and_confirmation(db, make_lead):
    lead = make_lead()
    f = Followup(lead_id=lead.id, reason="Callback")
    db.add(f)
    db.commit()
    with pytest.raises(ValueError, match="confirmation"):
        complete_followup(db, f, FollowupAction(action="complete", outcome="Connected"))
    with pytest.raises(ValueError, match="actual outcome"):
        complete_followup(db, f, FollowupAction(action="complete", confirm=True))
    with pytest.raises(ValueError, match="Describe"):
        complete_followup(db, f, FollowupAction(action="complete", outcome="Other", confirm=True))


def test_followup_reschedule_and_cancel(db, make_lead):
    lead = make_lead()
    f = Followup(lead_id=lead.id, reason="Manual task")
    db.add(f)
    db.commit()
    due = datetime.now(timezone.utc) + timedelta(days=2)
    complete_followup(db, f, FollowupAction(action="reschedule", due_at=due, confirm=True))
    assert f.due_at == due and lead.next_followup_at == due
    complete_followup(db, f, FollowupAction(action="cancel", confirm=True))
    assert f.status == "cancelled" and lead.next_followup_at is None
    with pytest.raises(ValueError, match="no longer pending"):
        complete_followup(db, f, FollowupAction(action="complete", outcome="Connected", confirm=True))


def test_overdue_today_upcoming_unscheduled_and_dnc(db, make_lead):
    start, end = day_bounds("America/New_York")
    lead = make_lead()
    restricted = make_lead(name="Restricted", phone="+12025550198", source_do_not_contact=True)
    for who, due in [
        (lead, start - timedelta(days=3)),
        (lead, start + timedelta(hours=12)),
        (lead, end + timedelta(days=2)),
        (lead, None),
        (restricted, start - timedelta(days=5)),
    ]:
        db.add(Followup(lead_id=who.id, due_at=due, reason="Explicit test due date"))
    db.commit()
    queue = daily_queue(db, "America/New_York")
    assert all(queue["counts"][k] == 1 for k in ["overdue", "today", "upcoming", "unscheduled"])
    assert queue["excluded_dnc"] == 1
    assert not any(item["lead"]["id"] == restricted.id for items in queue["sections"].values() for item in items)
    assert count_query(db, select(Lead).where(metric_clause("overdue", "America/New_York"))) == 1


def test_no_followup_date_is_not_overdue(db, make_lead):
    lead = make_lead()
    db.add(Followup(lead_id=lead.id, reason="No justified date", due_at=None))
    db.commit()
    assert daily_queue(db, "America/New_York")["counts"]["overdue"] == 0


def test_timezone_day_boundary_and_dst():
    now = datetime(2026, 10, 21, 2, tzinfo=timezone.utc)
    start, end = day_bounds("America/New_York", now)
    assert start == datetime(2026, 10, 20, 4, tzinfo=timezone.utc)
    assert end - start == timedelta(hours=24)
    start, end = day_bounds("America/New_York", datetime(2026, 3, 8, 12, tzinfo=timezone.utc))
    assert end - start == timedelta(hours=23)
    start, end = day_bounds("America/New_York", datetime(2026, 11, 1, 12, tzinfo=timezone.utc))
    assert end - start == timedelta(hours=25)


@pytest.mark.parametrize("value", ["2026-03-08T02:30:00", "2026-11-01T01:30:00"])
def test_ambiguous_or_nonexistent_local_time_rejected(value):
    with pytest.raises(ValueError, match="daylight-saving"):
        parse_datetime(value, "America/New_York")
    assert parse_datetime(value + "-05:00", "America/New_York").tzinfo == timezone.utc


def test_explicit_callback_bonus(db, make_lead):
    lead = make_lead(contact_outcome="Callback Requested")
    f = Followup(lead_id=lead.id, priority=40, reason="Callback")
    db.add(f)
    db.commit()
    rules = db.get(AppSetting, "priority_rules").value
    score, factors = priority_for(lead, f, rules, datetime.now(timezone.utc))
    assert score == 70 and any("callback" in reason for reason in factors)


def test_draft_generation_never_sends_and_preserves_context(db, make_lead):
    lead = make_lead(source_do_not_contact=False, contact_outcome="Callback Requested")
    draft = generate_draft(db, lead)
    assert "callback request" in draft.body and draft.context
    assert draft.model_id.startswith("reviewed-context")
    assert not hasattr(draft, "sent_at")


@pytest.mark.parametrize("restriction", [True, None])
def test_dnc_and_unknown_block_drafts(db, make_lead, restriction):
    lead = make_lead(source_do_not_contact=restriction, contact_outcome="Callback Requested")
    with pytest.raises(ValueError, match="Do Not Contact|unknown"):
        generate_draft(db, lead)


def test_insufficient_context_does_not_get_generic_draft(db, make_lead):
    lead = make_lead(source_do_not_contact=False)
    with pytest.raises(ValueError, match="Insufficient"):
        generate_draft(db, lead)


def test_analysis_preserves_unknowns_and_caches(db, make_lead, settings):
    lead = make_lead(asking_price=150000, source_do_not_contact=False)
    insight, cached, warning = analyze_lead(db, lead, settings)
    assert not cached and warning is None
    assert insight.facts["property_condition"]["category"] == "unknown"
    assert insight.facts["seller_motivation"]["value"] is None
    assert insight.facts["asking_price"]["value"] == 150000
    assert insight.facts["asking_price"]["evidence"]
    same, cached, _ = analyze_lead(db, lead, settings)
    assert cached and same.id == insight.id
    db.add(Activity(lead_id=lead.id, activity_type="note", source="local", summary="New factual context"))
    db.commit()
    different, cached, _ = analyze_lead(db, lead, settings)
    assert not cached and different.id != same.id


def test_ollama_unavailable_falls_back(db, make_lead, settings, monkeypatch):
    settings.ollama_enabled = True
    settings.ollama_model = "test-model"
    from app.services import ai

    def unavailable(*args):
        raise AIUnavailable("Local model failed")

    monkeypatch.setattr(ai, "infer_locally", unavailable)
    insight, _, warning = analyze_lead(db, make_lead(), settings)
    assert warning and insight.model_id.startswith("evidence-rules")


def test_external_ai_url_rejected(settings):
    settings.ollama_enabled = True
    settings.ollama_url = "https://external.example.test"
    with pytest.raises(AIUnavailable, match="loopback"):
        infer_locally(settings, [])


def test_unsupported_model_facts_discarded(db, make_lead, settings, monkeypatch):
    from app.services import ai
    from app.services.ai import ModelAnalysis

    settings.ollama_enabled = True
    settings.ollama_model = "test-model"
    monkeypatch.setattr(
        ai,
        "infer_locally",
        lambda *_: ModelAnalysis.model_validate(
            {
                "facts": {
                    "property_condition": {
                        "value": "Perfect",
                        "category": "explicit",
                        "evidence": ["invented:123"],
                        "quote": "not in context",
                    }
                }
            }
        ),
    )
    insight, _, _ = analyze_lead(db, make_lead(), settings)
    assert insight.facts["property_condition"]["category"] == "unknown"


def test_report_denominators_and_zero_division(db, make_lead):
    empty = reports(db, {}, "America/New_York")
    assert all(rate["percent"] is None for rate in empty["rates"])
    lead = make_lead(source_status="Qualified")
    make_lead(name="Second", phone="+12025550198", source_status="New")
    set_stage(db, lead, "offer_made")
    db.commit()
    result = reports(db, {}, "America/New_York")
    all_offer = next(r for r in result["rates"] if r["label"] == "Recorded offer rate — all leads")
    qualified = next(r for r in result["rates"] if r["label"] == "Recorded offer rate — qualified cohort")
    assert all_offer["percent"] == 50 and all_offer["denominator"] == 2
    assert qualified["percent"] == 100 and qualified["denominator"] == 1
    assert result["unknown_creation_dates"] == 2


def test_sync_cannot_clear_source_dnc_or_local_stage_override(db, make_lead, settings):
    lead = make_lead(external_id="source-1", source_status="New", source_do_not_contact=True)
    set_stage(db, lead, "qualified")
    db.commit()
    upsert_lead(
        db,
        {
            "external_id": "source-1",
            "full_name": "Test Seller",
            "primary_phone": "+12025550199",
            "source_status": "Closed",
            "source_do_not_contact": False,
        },
        settings,
        "newhash",
    )
    db.commit()
    assert lead.source_status == "Closed" and lead.stage_code == "qualified"
    assert lead.source_do_not_contact is True


def test_sql_wildcards_in_search_treated_literally(db, make_lead):
    make_lead()
    assert count_query(db, lead_query({"search": "%"}, "America/New_York")) == 0
    assert count_query(db, lead_query({"search": "Example"}, "America/New_York")) == 1


def test_business_original_date_filter_excludes_unknown(db, make_lead):
    make_lead(original_created_at="2010-01-01T12:00:00+00:00")
    make_lead(name="Unknown", phone="+12025550198")
    assert count_query(db, lead_query({"from_date": "2009-01-01", "to_date": "2011-01-01"}, "America/New_York")) == 1


def test_scheduler_rules_and_dnc_are_not_ai_inferences(settings):
    status = ollama_status(settings)
    assert not status["available"] and not status["enabled"]


def test_source_call_log_dnc_cannot_be_cleared_locally(db, make_lead, settings, client):
    from app.services.resimpli import load_adapter
    from app.services.sync import upsert_activity

    lead = make_lead()
    upsert_activity(
        db, lead, {"external_id": "call-dnc", "outcome": "dnc"}, "call", load_adapter(settings), "America/New_York"
    )
    db.commit()
    assert lead.source_do_not_contact is True
    response = client.post(
        f"/api/leads/{lead.id}/restriction",
        json={"restricted": False, "evidence": "Attempted local override", "confirm": True},
    )
    assert response.status_code == 400


def test_sync_updates_property_facts_and_retains_change_evidence(db, make_lead, settings):
    from app.services.normalization import normalize_address

    lead = make_lead(external_id="price-lead", asking_price=100000)
    prop = lead.properties[0]
    prop.normalized_address = normalize_address(
        {"street_address": prop.street_address, "city": prop.city, "state": prop.state, "zip_code": prop.zip_code}
    )
    db.commit()
    upsert_lead(
        db,
        {
            "external_id": "price-lead",
            "full_name": lead.full_name,
            "street_address": "12 Example St",
            "city": "Austin",
            "state": "TX",
            "zip_code": "78701",
            "asking_price": 125000,
        },
        settings,
        "changed",
    )
    db.commit()
    assert prop.asking_price == 125000
    assert any(
        change["field"] == "asking_price" and change["previous"] == 100000
        for change in prop.property_metadata["source_changes"]
    )


def test_custom_pipeline_stage_metrics_and_no_attempt_drilldown(db, make_lead):
    from app.models import PipelineStage

    db.add(PipelineStage(code="custom_review", label="Custom Review", position=30))
    db.commit()
    lead = make_lead()
    set_stage(db, lead, "custom_review")
    db.commit()
    metrics = {m["key"]: m["value"] for m in dashboard(db, {}, "America/New_York")["metrics"]}
    assert metrics["stage:custom_review"] == 1
    assert count_query(db, lead_query({"metric": "no_recorded_attempt"}, "America/New_York")) == 1
    report = reports(db, {}, "America/New_York")
    assert report["counts"]["no_recorded_attempt"] == 1


def test_phone_search_accepts_us_formatting(db, make_lead):
    make_lead()
    assert count_query(db, lead_query({"search": "(202) 555-0199"}, "America/New_York")) == 1


def test_stale_and_unknown_activity_report_drilldowns_are_consistent(db, make_lead):
    first = make_lead(name="Old Call", phone="2025550111")
    make_lead(name="Old Contact", phone="2025550112", last_contact_at=(utcnow() - timedelta(days=40)).isoformat())
    make_lead(
        name="Unknown Recency", phone="2025550113", original_created_at=(utcnow() - timedelta(days=100)).isoformat()
    )
    db.add(
        Activity(
            lead_id=first.id,
            activity_type="activity",
            summary="Recorded source no-answer outcome",
            outcome="No Answer",
            occurred_at=utcnow() - timedelta(days=40),
            source="resimpli",
        )
    )
    db.commit()
    data = reports(db, {}, "America/New_York")
    assert data["counts"]["stale_activity_leads"] == 2
    assert data["counts"]["unknown_activity_recency"] == 1
    assert count_query(db, lead_query({"metric": "stale_activity_leads"}, "America/New_York")) == 2
    assert count_query(db, lead_query({"metric": "unknown_activity_recency"}, "America/New_York")) == 1
    assert (
        data["counts"]["contact_attempts"]
        == count_query(db, lead_query({"metric": "contact_attempts"}, "America/New_York"))
        == 2
    )


@pytest.mark.parametrize("outcome", ["No Answer", "Left Voicemail", "Wrong Number"])
def test_failed_imported_call_with_timestamp_never_implies_connection(db, make_lead, outcome):
    lead = make_lead(contact_outcome=outcome, last_contact_at="2026-10-01T16:00:00+00:00")
    assert lead.contact_status == "attempted" and lead.last_contact_at is None
    assert reports(db, {}, "America/New_York")["counts"]["contact_attempts"] == 1
    assert lead.source_data["normalized"]["last_contact_at"] == "2026-10-01T16:00:00+00:00"


def test_failed_synced_call_date_does_not_fabricate_connection(db, make_lead, settings):
    lead = make_lead(external_id="no-answer-date")
    upsert_lead(
        db,
        {
            "external_id": "no-answer-date",
            "full_name": lead.full_name,
            "contact_outcome": "No Answer",
            "last_contact_at": "2026-10-01T16:00:00Z",
        },
        settings,
        "failed-call",
    )
    db.commit()
    assert lead.contact_status == "attempted" and lead.last_contact_at is None


def test_internal_note_outcomes_are_not_contact_evidence(db, make_lead, client):
    lead = make_lead()
    response = client.post(
        f"/api/leads/{lead.id}/activities",
        json={"activity_type": "note", "summary": "Internal review only", "outcome": "Connected"},
    )
    assert response.status_code == 200
    assert lead.contact_status != "contacted"
    assert reports(db, {}, "America/New_York")["counts"]["contact_attempts"] == 0


def test_out_of_order_source_calls_preserve_latest_outcome_and_dnc(db, make_lead, settings):
    from app.services.resimpli import load_adapter
    from app.services.sync import upsert_activity

    lead = make_lead(external_id="chronology")
    adapter = load_adapter(settings)
    upsert_activity(
        db,
        lead,
        {"external_id": "new", "outcome": "callback", "occurred_at": "2026-10-20T16:00:00Z"},
        "call",
        adapter,
        "America/New_York",
    )
    db.commit()
    upsert_activity(
        db,
        lead,
        {"external_id": "old", "outcome": "no_answer", "occurred_at": "2026-10-18T16:00:00Z"},
        "call",
        adapter,
        "America/New_York",
    )
    db.commit()
    assert lead.contact_outcome == "Callback Requested"
    upsert_activity(
        db,
        lead,
        {"external_id": "old-dnc", "outcome": "dnc", "occurred_at": "2026-10-17T16:00:00Z"},
        "call",
        adapter,
        "America/New_York",
    )
    db.commit()
    assert lead.source_do_not_contact is True
    assert lead.contact_outcome == "Callback Requested"


def test_changed_draft_context_requires_explicit_regeneration(db, make_lead, client):
    lead = make_lead(contact_outcome="Callback Requested", source_do_not_contact=False)
    first = generate_draft(db, lead)
    lead.source_data = {
        **lead.source_data,
        "normalized": {**lead.source_data["normalized"], "notes": "New verified source context requires review."},
    }
    db.commit()
    response = client.get(f"/api/leads/{lead.id}")
    assert response.json()["draft_stale"] is True
    with pytest.raises(ValueError, match="context changed"):
        generate_draft(db, lead)
    replacement = generate_draft(db, lead, regenerate=True)
    assert replacement.id != first.id
    assert client.get(f"/api/leads/{lead.id}").json()["draft_stale"] is False


@pytest.mark.parametrize("value", ["2020", "May 2020", "2020-10"])
def test_partial_source_dates_are_not_completed_with_invented_components(value):
    with pytest.raises(ValueError):
        parse_datetime(value)


def test_overdue_priority_uses_calendar_days_across_dst(db, make_lead):
    lead = make_lead()
    start, _ = day_bounds("America/New_York", datetime(2026, 11, 2, 12, tzinfo=timezone.utc))
    followup = Followup(
        lead_id=lead.id,
        priority=40,
        reason="Explicit source date",
        due_at=parse_datetime("2026-11-01T00:00:00", "America/New_York"),
    )
    rules = db.get(AppSetting, "priority_rules").value
    score, reasons = priority_for(lead, followup, rules, start, "America/New_York")
    assert score == 42
    assert any("1 calendar day" in reason for reason in reasons)


def test_recorded_offer_response_removes_awaiting_queue_without_crm_stage_write(db, make_lead, client):
    lead = make_lead(source_status="Offer Made", source_do_not_contact=False)
    assert daily_queue(db, "America/New_York")["counts"]["offers"] == 1
    response = client.post(
        f"/api/leads/{lead.id}/activities",
        json={
            "activity_type": "offer",
            "summary": "Actual seller rejection recorded by the user.",
            "outcome": "Offer Rejected",
            "confirm": True,
        },
    )
    assert response.status_code == 200
    assert daily_queue(db, "America/New_York")["counts"]["offers"] == 0
    assert lead.stage_code == "offer_made" and lead.local_stage_override is False
