"""The xAI client against a mocked server: schemas, retries, cap, and no PII on the wire."""

import json

import httpx
import pytest
from sqlalchemy import select

from app.config import Settings
from app.models import GrokRun
from app.services.ai_grok import (
    AI_FIELDS,
    DEFAULT_AI_FIELDS,
    GrokClient,
    GrokError,
    cap_status,
    cost_usd,
    model_for,
    monthly_estimate,
    record_run,
    strip_pii,
    usage_today,
)

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def grok_settings(**extra):
    values = {
        "grok_enabled": True,
        "grok_api_key": "xai-not-a-real-key-000000000000",
        "grok_api": "responses",
        "grok_followup_model": "grok-4.3",
        "grok_checklist_model": "grok-4.3",
        "grok_advisor_model": "grok-4.7",
        "grok_daily_request_limit": 5,
        "grok_timeout_seconds": 5,
        **extra,
    }
    return Settings(_env_file=None, **values)


class Server:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.sleeps = []

    def handler(self, request):
        self.requests.append(request)
        answer = self.responses.pop(0) if self.responses else httpx.Response(200, json={})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def client(self, settings):
        return GrokClient(settings, transport=httpx.MockTransport(self.handler), sleeper=self.sleeps.append)


def responses_ok(text, tokens=(120, 40)):
    return httpx.Response(
        200,
        json={
            "id": "resp_1",
            "object": "response",
            "model": "grok-4.3",
            "status": "completed",
            "output": [
                {"type": "reasoning", "summary": []},
                {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]},
            ],
            "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]},
        },
    )


def chat_ok(text):
    return httpx.Response(
        200,
        json={
            "id": "chat_1",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 90, "completion_tokens": 30},
        },
    )


def test_responses_api_sends_a_strict_schema_and_parses_the_answer():
    server = Server(responses_ok('{"answer": "ok"}'))
    client = server.client(grok_settings())
    try:
        result = client.complete(purpose="advisor", prompt="assess this lead", schema=SCHEMA, name="advisor")
    finally:
        client.close()
    body = json.loads(server.requests[0].content)
    assert server.requests[0].url.path == "/v1/responses"
    assert body["text"]["format"] == {"type": "json_schema", "name": "advisor", "schema": SCHEMA, "strict": True}
    assert body["store"] is False
    assert result.data == {"answer": "ok"}
    assert result.input_tokens == 120 and result.output_tokens == 40
    assert result.model == "grok-4.7", "the advisor model is its own setting"


def test_chat_completions_is_one_setting_away():
    server = Server(chat_ok('{"answer": "ok"}'))
    client = server.client(grok_settings(grok_api="chat_completions"))
    try:
        result = client.complete(purpose="checklist_suggest", prompt="suggest", schema=SCHEMA)
    finally:
        client.close()
    body = json.loads(server.requests[0].content)
    assert server.requests[0].url.path == "/v1/chat/completions"
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA
    assert result.data == {"answer": "ok"}
    assert result.model == "grok-4.3"


def test_an_answer_that_is_not_json_is_refused_rather_than_saved():
    server = Server(responses_ok("Sure! Here is your JSON: not json"))
    client = server.client(grok_settings())
    try:
        with pytest.raises(GrokError) as error:
            client.complete(purpose="advisor", prompt="assess", schema=SCHEMA)
    finally:
        client.close()
    assert error.value.code == "invalid_json"
    assert "nothing was saved" in str(error.value)


def test_a_timeout_is_retried_then_reported_without_a_key():
    server = Server(httpx.ReadTimeout("t"), httpx.ReadTimeout("t"), httpx.ReadTimeout("t"))
    client = server.client(grok_settings())
    try:
        with pytest.raises(GrokError) as error:
            client.complete(purpose="advisor", prompt="assess")
    finally:
        client.close()
    assert error.value.code == "timeout" and error.value.retryable is True
    assert len(server.requests) == 3
    assert "not-a-real-key" not in str(error.value)


def test_rate_limiting_is_retried_and_then_succeeds():
    server = Server(
        httpx.Response(429, headers={"Retry-After": "1"}, json={"error": "slow down"}),
        responses_ok("hello"),
    )
    client = server.client(grok_settings())
    try:
        result = client.complete(purpose="followup_draft", prompt="draft")
    finally:
        client.close()
    assert result.text == "hello"
    assert len(server.requests) == 2 and server.sleeps


def test_rejected_credentials_are_not_retried():
    server = Server(httpx.Response(401, json={"error": "bad key"}))
    client = server.client(grok_settings())
    try:
        with pytest.raises(GrokError) as error:
            client.complete(purpose="advisor", prompt="assess")
    finally:
        client.close()
    assert error.value.code == "rejected_credentials"
    assert len(server.requests) == 1


def test_a_disabled_integration_or_a_missing_key_explains_itself():
    with pytest.raises(GrokError) as disabled:
        GrokClient(grok_settings(grok_enabled=False))
    assert disabled.value.code == "not_configured"
    with pytest.raises(GrokError) as keyless:
        GrokClient(grok_settings(grok_api_key=""))
    assert keyless.value.code == "not_configured"


def test_phone_email_and_credentials_never_reach_the_prompt():
    server = Server(responses_ok("ok"))
    client = server.client(grok_settings())
    try:
        client.complete(
            purpose="followup_draft",
            prompt="Call Dana at (512) 555-0143 or dana@example.test. Key sk-abcdefghijklmnop.",
        )
    finally:
        client.close()
    sent = server.requests[0].content.decode()
    assert "555-0143" not in sent and "dana@example.test" not in sent and "sk-abcdefghij" not in sent
    assert "[PHONE REDACTED]" in sent and "[EMAIL REDACTED]" in sent and "[CREDENTIAL REDACTED]" in sent


def test_the_preview_is_exactly_what_would_be_sent_and_holds_no_key():
    client = GrokClient(grok_settings())
    try:
        preview = client.preview(purpose="advisor", prompt="Seller email is dana@example.test", schema=SCHEMA)
    finally:
        client.close()
    assert preview["api"] == "responses" and preview["path"] == "/responses"
    assert "dana@example.test" not in json.dumps(preview)
    assert "not-a-real-key" not in json.dumps(preview)


def test_strip_pii_is_shared_by_every_path():
    assert strip_pii("(202) 555-0101") == "[PHONE REDACTED]"
    assert strip_pii("a@b.co") == "[EMAIL REDACTED]"
    assert strip_pii("nothing to hide") == "nothing to hide"


def test_the_daily_cap_counts_todays_runs(db):
    settings = grok_settings(grok_daily_request_limit=2)
    assert usage_today(db) == 0
    for index in range(2):
        record_run(
            db,
            run_id=f"run-{index}",
            lead_id=None,
            purpose="advisor",
            input_hash="a" * 64,
            model="grok-4.7",
            error="failed",
        )
    db.commit()
    status = cap_status(db, settings)
    assert status["used"] == 2 and status["exhausted"] is True and status["remaining"] == 0
    assert status["models"]["advisor"] == "grok-4.7"
    assert status["enabled"] is True and status["key_configured"] is True


def test_the_monthly_estimate_uses_the_plan_then_the_observed_usage(db):
    settings = grok_settings(grok_expected_daily_calls=10, grok_expected_tokens_in=1000, grok_expected_tokens_out=500)
    planned = monthly_estimate(settings)
    assert planned["basis"] == "planned_volume"
    assert planned["monthly_usd"] > 0

    record_run(
        db,
        run_id="run-1",
        lead_id=None,
        purpose="advisor",
        input_hash="b" * 64,
        model="grok-4.7",
        error="failed",
    )
    db.add(
        GrokRun(
            id="run-2",
            lead_id=None,
            purpose="advisor",
            api="responses",
            model_id="grok-4.7",
            state="succeeded",
            input_hash="c" * 64,
            request_preview={},
            output={},
            usage={},
            input_tokens=1_000_000,
            output_tokens=0,
            duration_ms=5,
        )
    )
    db.commit()
    observed = monthly_estimate(settings, db)
    assert observed["basis"] == "observed_last_30_days"
    assert observed["monthly_usd"] == pytest.approx(2.0, abs=0.01)


def test_cost_uses_the_documented_list_price():
    assert cost_usd(1_000_000, 0, "grok-4.3") == pytest.approx(1.25)
    assert cost_usd(0, 1_000_000, "grok-4.7") == pytest.approx(6.00)


def test_the_same_model_setting_is_used_for_its_purpose():
    settings = grok_settings()
    assert model_for("followup_draft", settings) == "grok-4.3"
    assert model_for("checklist_suggest", settings) == "grok-4.3"
    assert model_for("advisor", settings) == "grok-4.7"


def test_every_ai_field_is_described_and_the_defaults_are_a_subset():
    assert set(DEFAULT_AI_FIELDS) <= set(AI_FIELDS)
    assert "conversation" not in DEFAULT_AI_FIELDS, "conversation text is opt-in"


def test_a_recorded_run_holds_the_preview_and_no_raw_prompt(db):
    server = Server(responses_ok("draft text"))
    client = server.client(grok_settings())
    try:
        result = client.complete(purpose="followup_draft", prompt="Email dana@example.test")
        record_run(db, run_id="run-9", lead_id=None, purpose="followup_draft", input_hash="d" * 64, result=result)
        db.commit()
    finally:
        client.close()
    row = db.scalar(select(GrokRun).where(GrokRun.id == "run-9"))
    assert row.state == "succeeded"
    assert row.output["text"] == "draft text"
    assert "dana@example.test" not in json.dumps(row.request_preview)
    assert row.api == "responses" and row.model_id == "grok-4.3"
