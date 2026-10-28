"""Synthetic-only cloud tests; never use an actual account key or network."""

import json
from datetime import timedelta
from pathlib import Path
import httpx
import pytest
from sqlalchemy import select, func
from app.config import Settings
from app.db import utcnow
from app.models import AIInsight, Activity, AuditLog, Draft
from app.services.ai import FACT_KEYS, analyze_lead
from app.services.cloud_ai import (
    create_preview,
    execute_request,
    save_organized_notes,
    ReviewError,
    redacted_context,
    request_dict,
    usage_today,
)
from app.services.groq_client import GroqClient, GroqError, CloudAnalysis, CloudDraft, strict_schema
from app.services import private_settings
from app import config

FAKE_KEY = "gsk_SYNTHETIC_TEST_ONLY_NOT_A_REAL_ACCOUNT_KEY"


@pytest.fixture
def cloud_settings():
    return Settings(_env_file=None, groq_enabled=True, groq_api_key=FAKE_KEY)


def analysis_output(records):
    first = records[0]
    grounded = {"text": first["text"], "evidence": [first["ref"]], "quote": first["text"]}
    return CloudAnalysis.model_validate(
        {
            "summary": grounded,
            "facts": {key: {"value": None, "category": "unknown", "evidence": [], "quote": None} for key in FACT_KEYS},
            "organized_notes": [grounded],
            "missing_information": ["Confirm seller timeline"],
            "conflicts": [],
        }
    )


class FakeClient:
    calls = 0

    def __init__(self, settings):
        pass

    def complete(self, purpose, records, flags):
        FakeClient.calls += 1
        if purpose == "draft":
            return CloudDraft(
                body="Hi {{seller_first_name}}, I’m following up on your callback request about {{property_address}}. What would be a convenient time to talk?",
                evidence=[records[0]["ref"]],
                quote=records[0]["text"],
                review_note="Review source facts before copying.",
            ), {"total_tokens": 120}
        return analysis_output(records), {"total_tokens": 100}

    def close(self):
        pass


@pytest.fixture(autouse=True)
def reset_calls():
    FakeClient.calls = 0


def approve(db, request, settings, **kw):
    return execute_request(
        db,
        request.id,
        settings,
        "SEND REVIEWED CONTEXT",
        request.payload_hash,
        [r["ref"] for r in request.records],
        client_factory=kw.pop("client_factory", FakeClient),
        **kw,
    )


def test_preview_redacts_known_contacts_names_addresses_and_tokens(db, make_lead, cloud_settings):
    lead = make_lead(
        name="Morgan Parker",
        first_name="Morgan",
        last_name="Parker",
        email="morgan@example.test",
        notes="Morgan Parker at (202) 555-0199 / morgan@example.test, 12 Example St, Austin, 78701. " + FAKE_KEY,
    )
    request = create_preview(db, lead, "notes", cloud_settings)
    text = json.dumps(request.records)
    for private in [
        "Morgan",
        "Parker",
        "2025550199",
        "202) 555-0199",
        "morgan@example.test",
        "12 Example St",
        "Austin",
        "78701",
        FAKE_KEY,
    ]:
        assert private not in text
    assert request.state == "pending_review" and FakeClient.calls == 0
    assert all(record["ref"].startswith("E") for record in request.records)
    assert request.result["redactions"] > 0


def test_extra_redactions_are_literal_and_reviewable(db, make_lead):
    lead = make_lead(notes="Third-party name is Another Person. Repair scope is unknown.")
    records, *_ = redacted_context(db, lead, ["Another Person"])
    assert "Another Person" not in json.dumps(records)
    assert "[ADDITIONAL REDACTION]" in json.dumps(records)


def test_disabled_cloud_cannot_preview_or_send(db, make_lead):
    with pytest.raises(ReviewError, match="Enable Groq"):
        create_preview(db, make_lead(), "notes", Settings(_env_file=None))
    assert FakeClient.calls == 0


def test_consent_phrase_required_before_any_cloud_call(db, make_lead, cloud_settings):
    request = create_preview(db, make_lead(seller_motivation="Relocating for work"), "analyze", cloud_settings)
    with pytest.raises(ReviewError, match="Explicitly approve"):
        execute_request(
            db, request.id, cloud_settings, "yes", request.payload_hash, ["E001"], client_factory=FakeClient
        )
    assert FakeClient.calls == 0


def test_expired_review_and_changed_digest_do_not_send(db, make_lead, cloud_settings):
    request = create_preview(db, make_lead(seller_motivation="Relocating"), "notes", cloud_settings)
    with pytest.raises(ReviewError, match="digest"):
        execute_request(
            db, request.id, cloud_settings, "SEND REVIEWED CONTEXT", "0" * 64, ["E001"], client_factory=FakeClient
        )
    request.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(ReviewError, match="expired"):
        approve(db, request, cloud_settings)
    assert request.state == "expired" and FakeClient.calls == 0


def test_source_change_requires_new_review_without_transmission(db, make_lead, cloud_settings):
    lead = make_lead(seller_motivation="Relocating")
    request = create_preview(db, lead, "analyze", cloud_settings)
    lead.source_status = "Updated source state"
    db.commit()
    with pytest.raises(ReviewError, match="Source context changed"):
        approve(db, request, cloud_settings)
    assert FakeClient.calls == 0


def test_approved_analysis_is_grounded_and_preserves_source_records(db, make_lead, cloud_settings):
    lead = make_lead(seller_motivation="Relocating for work")
    original = json.dumps(lead.source_data, sort_keys=True)
    request = approve(db, create_preview(db, lead, "analyze", cloud_settings), cloud_settings)
    assert request.state == "completed" and FakeClient.calls == 1
    assert json.dumps(lead.source_data, sort_keys=True) == original
    insight = db.get(AIInsight, request.result["insight_id"])
    assert insight.model_id.startswith("groq:") and insight.summary
    assert db.scalar(select(func.count()).select_from(Activity)) == 0
    assert usage_today(db) == 1
    assert FAKE_KEY not in json.dumps(request_dict(request), default=str)


def test_repeated_approval_and_identical_context_use_cache(db, make_lead, cloud_settings):
    lead = make_lead(seller_motivation="Relocating")
    first = approve(db, create_preview(db, lead, "notes", cloud_settings), cloud_settings)
    approve(db, first, cloud_settings)
    second = approve(db, create_preview(db, lead, "notes", cloud_settings), cloud_settings)
    assert second.result["cached_from"] == first.id and FakeClient.calls == 1


def test_daily_cap_counts_attempts_and_blocks_new_transmission(db, make_lead, cloud_settings):
    settings = cloud_settings.model_copy(update={"groq_daily_request_limit": 1})
    lead = make_lead(seller_motivation="Relocating")
    approve(db, create_preview(db, lead, "notes", settings), settings)
    next_request = create_preview(db, lead, "notes", settings)
    with pytest.raises(ReviewError, match="daily Groq request cap"):
        approve(db, next_request, settings, force_refresh=True)
    assert FakeClient.calls == 1


@pytest.mark.parametrize("restriction", [True, None])
def test_cloud_drafts_block_dnc_and_unknown_permission(db, make_lead, cloud_settings, restriction):
    lead = make_lead(source_do_not_contact=restriction, contact_outcome="Callback Requested")
    with pytest.raises(ReviewError):
        create_preview(db, lead, "draft", cloud_settings)
    assert FakeClient.calls == 0


def test_draft_without_a_conversation_becomes_an_opener(db, make_lead, cloud_settings):
    """A seller with no stored conversation still gets a reviewable first contact."""
    request = create_preview(db, make_lead(source_do_not_contact=False), "draft", cloud_settings)

    assert request.result["constraints"]["draft_kind"] == "opener"
    assert request.result["constraints"]["conversation_records"] == 0
    assert request.result["constraints"]["signature_added_locally"] is True
    assert FakeClient.calls == 0


def test_cloud_draft_fills_private_placeholders_only_locally(db, make_lead, cloud_settings):
    lead = make_lead(
        name="Morgan Parker", first_name="Morgan", source_do_not_contact=False, contact_outcome="Callback Requested"
    )
    request = approve(db, create_preview(db, lead, "draft", cloud_settings), cloud_settings)
    assert request.state == "completed"
    assert request.result["body"].startswith("Hi Morgan,") and "12 Example St" in request.result["body"]
    assert "Morgan" not in json.dumps(request.records)
    assert db.get(Draft, request.result["draft_id"]).model_id.startswith("groq:")
    lead.source_do_not_contact = True
    db.commit()
    assert "body" not in request_dict(request, lead)["result"]
    with pytest.raises(ReviewError, match="Do Not Contact"):
        approve(db, request, cloud_settings)


def test_notes_proposal_does_not_save_until_explicitly_reviewed(db, make_lead, cloud_settings):
    lead = make_lead(seller_motivation="Relocating")
    request = approve(db, create_preview(db, lead, "notes", cloud_settings), cloud_settings)
    assert db.scalar(select(func.count()).select_from(Activity)) == 0
    with pytest.raises(ReviewError):
        save_organized_notes(db, request.id, False)
    note = save_organized_notes(db, request.id, True)
    assert note.activity_type == "note" and note.outcome is None and lead.contact_status == "unknown"
    assert save_organized_notes(db, request.id, True).id == note.id
    assert db.scalar(select(func.count()).select_from(Activity)) == 1


def test_ungrounded_numbers_fail_without_applying_ai_output(db, make_lead, cloud_settings):
    class Ungrounded(FakeClient):
        def complete(self, purpose, records, flags):
            output = analysis_output(records)
            output.facts["asking_price"].value = 999999
            output.facts["asking_price"].category = "explicit"
            output.facts["asking_price"].evidence = [records[0]["ref"]]
            output.facts["asking_price"].quote = records[0]["text"]
            return output, {}

    request = approve(
        db,
        create_preview(db, make_lead(seller_motivation="Relocating"), "analyze", cloud_settings),
        cloud_settings,
        client_factory=Ungrounded,
    )
    assert request.state == "failed" and "number" in request.error
    assert db.scalar(select(func.count()).select_from(AIInsight)) == 0


def test_context_change_during_provider_call_is_not_applied(db, make_lead, cloud_settings):
    lead = make_lead(seller_motivation="Relocating")

    class Changed(FakeClient):
        def complete(self, purpose, records, flags):
            lead.source_status = "Changed in another tab"
            db.commit()
            return analysis_output(records), {}

    request = approve(db, create_preview(db, lead, "analyze", cloud_settings), cloud_settings, client_factory=Changed)
    assert request.state == "completed_stale"
    assert db.scalar(select(func.count()).select_from(AIInsight)) == 0


def test_rule_analysis_never_uses_cloud_even_if_groq_is_enabled(db, make_lead, cloud_settings):
    insight, _, _ = analyze_lead(db, make_lead(seller_motivation="Relocating"), cloud_settings)
    assert not insight.model_id.startswith("groq:") and FakeClient.calls == 0


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_provider_failure_is_sanitized_and_never_auto_retried(cloud_settings, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "Do not expose " + FAKE_KEY}})

    client = GroqClient(cloud_settings, httpx.MockTransport(handler))
    with pytest.raises(GroqError) as error:
        client.models()
    assert FAKE_KEY not in str(error.value) and len(calls) == 1
    client.close()


def test_documented_groq_request_uses_strict_json_and_no_tools(cloud_settings):
    def handler(request):
        assert request.url.host == "api.groq.com"
        assert request.headers["authorization"] == "Bearer " + FAKE_KEY
        payload = json.loads(request.content)
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert "tools" not in payload and "tool_choice" not in payload
        assert FAKE_KEY not in json.dumps(payload)
        output = analysis_output([{"ref": "E001", "text": "Relocating"}]).model_dump()
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}],
                "usage": {"total_tokens": 100},
            },
        )

    client = GroqClient(cloud_settings, httpx.MockTransport(handler))
    output, usage = client.complete("analyze", [{"ref": "E001", "text": "Relocating"}], {})
    assert output.summary.text == "Relocating" and usage["total_tokens"] == 100
    client.close()


def test_structured_schema_has_fixed_fact_keys_and_required_fields():
    schema = strict_schema("analyze")
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert set(schema["properties"]["facts"]["required"]) == set(FACT_KEYS)
    for definition in schema["$defs"].values():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False


def test_private_credentials_are_not_returned_or_audited(client, db, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    config.get_settings.cache_clear()
    try:
        response = client.post(
            "/api/integrations/credentials",
            json={"provider": "groq", "api_key": FAKE_KEY, "confirm_private_storage": True},
        )
        assert response.status_code == 200, response.text
        assert response.json()["groq"]["key_configured"] is True
        assert FAKE_KEY not in response.text and FAKE_KEY not in repr(config.get_settings())
        path = tmp_path / ".env.secrets"
        assert path.exists()
        if __import__("os").name != "nt":
            assert path.stat().st_mode & 0o077 == 0
        assert FAKE_KEY not in json.dumps([row.details for row in db.scalars(select(AuditLog))])
        removed = client.post(
            "/api/integrations/credentials",
            json={"provider": "groq", "action": "remove", "confirm_private_storage": True},
        )
        assert not removed.json()["groq"]["key_configured"]
    finally:
        config.get_settings.cache_clear()


def test_fixture_adapter_cannot_be_marked_live(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    fixture = Path(__file__).resolve().parents[1] / "fixtures/response-adapter.json"
    with pytest.raises(ValueError, match="synthetic fixture"):
        private_settings.save_adapter(fixture.read_text(), True)


def test_pending_review_cannot_be_sent_using_a_different_account_key(db, make_lead, cloud_settings):
    preview = create_preview(db, make_lead(seller_motivation="Relocating"), "analyze", cloud_settings)
    assert "_credential_fingerprint" not in request_dict(preview)["result"]
    changed = cloud_settings.model_copy(update={"groq_api_key": "gsk_DIFFERENT_SYNTHETIC_TEST_ONLY_KEY"})
    with pytest.raises(ReviewError, match="configuration changed"):
        approve(db, preview, changed)
    assert FakeClient.calls == 0


def test_completion_between_initial_read_and_lock_does_not_duplicate_provider_call(
    db, make_lead, cloud_settings, monkeypatch
):
    from app.models import CloudRequest
    from app.services import cloud_ai

    preview = create_preview(db, make_lead(seller_motivation="Relocating"), "notes", cloud_settings)

    class CompletionBetweenReadAndClaim:
        def acquire(self, blocking=False):
            row = db.get(CloudRequest, preview.id)
            row.state = "completed"
            row.completed_at = utcnow()
            db.commit()
            return True

        def release(self):
            pass

    monkeypatch.setattr(cloud_ai, "EXECUTION_LOCK", CompletionBetweenReadAndClaim())
    result = approve(db, preview, cloud_settings)
    assert result.state == "completed" and FakeClient.calls == 0
