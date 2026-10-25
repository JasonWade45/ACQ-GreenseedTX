import json
import httpx
import pytest
from sqlalchemy import select, func
from app.config import Settings
from app.models import Lead, Activity, Appointment, AIInsight, SyncRun
from app.services.resimpli import ResimpliClient, IntegrationError, load_adapter, at_path
from app.services.sync import begin_sync, sync_run


def live_client(settings, handler, **kwargs):
    live = Settings(_env_file=None, resimpli_mode="live", resimpli_api_key="test-only-secret")
    return ResimpliClient(
        live, transport=httpx.MockTransport(handler), sleeper=lambda _: None, adapter=load_adapter(settings), **kwargs
    )


def test_missing_api_key_rejected_before_network():
    with pytest.raises(IntegrationError, match="API_KEY"):
        ResimpliClient(Settings(_env_file=None, resimpli_mode="live"))


def test_unverified_response_adapter_blocks_live():
    with pytest.raises(IntegrationError, match="unverified"):
        ResimpliClient(Settings(_env_file=None, resimpli_mode="live", resimpli_api_key="test"))


def test_disabled_integration_does_not_open_network():
    with pytest.raises(IntegrationError, match="disabled"):
        ResimpliClient(Settings(_env_file=None))


def test_raw_authorization_header_and_documented_post(settings):
    def handler(request):
        assert request.headers["authorization"] == "test-only-secret"
        assert request.method == "POST"
        assert request.url.path == "/api/v6/openapi/lead/list"
        assert json.loads(request.content)["page"] == 1
        return httpx.Response(200, json={"ok": True, "data": {"records": [], "total": 0}})

    client = live_client(settings, handler)
    assert list(client.pages("/lead/list", client.adapter.leads)) == []
    client.close()


@pytest.mark.parametrize("status", [401, 403])
def test_invalid_credentials_do_not_retry(settings, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"secret": "must not leak"})

    client = live_client(settings, handler)
    with pytest.raises(IntegrationError, match="credentials") as exc:
        client.request("/getUserInfo")
    assert len(calls) == 1 and "must not leak" not in str(exc.value)
    client.close()


def test_rate_limit_retry(settings):
    attempts = []

    def handler(request):
        attempts.append(request)
        return (
            httpx.Response(429, headers={"Retry-After": "2"})
            if len(attempts) < 3
            else httpx.Response(200, json={"ok": True})
        )

    client = live_client(settings, handler)
    delays = []
    client.sleeper = delays.append
    assert client.request("/getUserInfo") == {"ok": True}
    assert len(attempts) == 3 and 2 in delays
    client.close()


def test_long_retry_after_does_not_retry_early(settings):
    client = live_client(settings, lambda _: httpx.Response(429, headers={"Retry-After": "3600"}))
    with pytest.raises(IntegrationError, match="cooldown"):
        client.request("/getUserInfo")
    client.close()


@pytest.mark.parametrize("failure", ["timeout", "500"])
def test_bounded_retry(settings, failure):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("mock", request=request)
        return httpx.Response(500)

    client = live_client(settings, handler)
    with pytest.raises(IntegrationError, match="bounded"):
        client.request("/getUserInfo")
    assert len(calls) == 4
    client.close()


def test_pagination_and_missing_optional_fields(settings):
    def handler(request):
        page = json.loads(request.content)["page"]
        return httpx.Response(
            200, json={"ok": True, "data": {"records": [{"id": f"test-{page}"}] if page <= 2 else [], "total": 2}}
        )

    client = live_client(settings, handler)
    items = list(client.pages("/lead/list", client.adapter.leads, limit=1))
    assert len(items) == 2 and items[0]["full_name"] is None and items[1]["external_id"] == "test-2"
    client.close()


def test_pagination_without_total_uses_short_page(settings):
    def handler(request):
        page = json.loads(request.content)["page"]
        return httpx.Response(
            200, json={"ok": True, "data": {"records": [{"id": "a"}, {"id": "b"}] if page == 1 else [{"id": "c"}]}}
        )

    client = live_client(settings, handler)
    assert len(list(client.pages("/lead/list", client.adapter.leads, limit=2))) == 3
    client.close()


def test_repeated_page_detected(settings):
    client = live_client(settings, lambda _: httpx.Response(200, json={"ok": True, "data": {"records": [{"id": "a"}]}}))
    with pytest.raises(IntegrationError, match="Repeated page"):
        list(client.pages("/lead/list", client.adapter.leads, limit=1))
    client.close()


@pytest.mark.parametrize("payload", [None, [], {"ok": True, "data": {}}, {"ok": False}])
def test_malformed_responses(settings, payload):
    client = live_client(
        settings,
        lambda _: httpx.Response(200, json=payload) if payload is not None else httpx.Response(200, text="not-json"),
    )
    with pytest.raises(IntegrationError):
        list(client.pages("/lead/list", client.adapter.leads))
    client.close()


def test_write_and_communication_paths_are_blocked(settings):
    client = ResimpliClient(settings)
    for path in ["/lead/add", "/lead/delete", "/sms/send", "/email/send", "/calls/create", "https://evil.test"]:
        with pytest.raises(IntegrationError, match="blocked"):
            client.request(path, {})
    with pytest.raises(IntegrationError, match="disabled"):
        client.create_lead({})
    client.close()


def test_adapter_array_paths():
    assert at_path({"phones": [{"number": "123"}]}, "phones.0.number") == "123"
    assert at_path({"phones": []}, "phones.0.number") is None


def test_fixture_sync_idempotency_and_context_cache(db, factory, settings):
    run = begin_sync(db, settings)
    sync_run(run.id, factory, settings)
    db.expire_all()
    result = db.get(SyncRun, run.id)
    assert result.result == "success" and result.fetched == 6 and result.created == 6
    assert db.scalar(select(func.count()).select_from(Lead)) == 6
    assert db.scalar(select(func.count()).select_from(Appointment)) == 1
    assert db.scalar(select(func.count()).select_from(AIInsight)) == 6
    first_activity_count = db.scalar(select(func.count()).select_from(Activity))
    second = begin_sync(db, settings)
    sync_run(second.id, factory, settings)
    db.expire_all()
    assert db.get(SyncRun, second.id).skipped == 6
    assert db.scalar(select(func.count()).select_from(Lead)) == 6
    assert db.scalar(select(func.count()).select_from(Activity)) == first_activity_count
    assert db.scalar(select(func.count()).select_from(AIInsight)) == 6
    assert db.scalar(select(Lead).where(Lead.external_id == "fixture-seller-001")).contact_status == "attempted"


def test_sync_failure_is_persisted(db, factory):
    settings = Settings(_env_file=None, resimpli_mode="disabled")
    run = begin_sync(db, settings)
    sync_run(run.id, factory, settings)
    db.expire_all()
    result = db.get(SyncRun, run.id)
    assert result.result == "failed" and result.finished_at and result.errors


def test_overlapping_sync_runs_rejected(db, settings):
    begin_sync(db, settings)
    with pytest.raises(ValueError, match="already running"):
        begin_sync(db, settings)
