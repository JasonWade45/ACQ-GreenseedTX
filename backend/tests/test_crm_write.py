"""The CRM write client: one path, no invented data, no blind retries."""

import json

import httpx
import pytest

from app.config import Settings
from app.services.resimpli import IntegrationError
from app.services.resimpli_write import (
    WRITE_PATHS,
    CrmDefaults,
    CrmPushBlocked,
    CrmWriteError,
    ResimpliWriter,
    build_lead_payload,
    candidate_lead_ids,
    lead_address,
    lead_apn,
    payload_hash,
    ten_digit_phone,
)

DEFAULTS = CrmDefaults(
    marketing_campign_id="5f1d7c9a1b2c3d4e5f607182",
    market_id="5f1d7c9a1b2c3d4e5f607183",
    pipeline_id="5f1d7c9a1b2c3d4e5f607184",
    main_status_id="5f1d7c9a1b2c3d4e5f607185",
)


@pytest.fixture
def live_settings():
    """A key that is obviously not real, and live mode: the transport is always mocked."""
    return Settings(
        _env_file=None,
        resimpli_mode="live",
        resimpli_api_key="not-a-real-key-000000000000",
        sync_requests_per_minute=100,
    )


class Recorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.sleeps = []

    def transport(self, request):
        self.requests.append(request)
        answer = self.responses.pop(0) if self.responses else httpx.Response(200, json={"ok": True})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def writer(self, settings):
        return ResimpliWriter(settings, transport=httpx.MockTransport(self.transport), sleeper=self.sleeps.append)


def body_of(lead, **kwargs):
    return build_lead_payload(lead, DEFAULTS, **kwargs)["body"]


def test_payload_sends_ten_digit_phones_and_no_invented_name(make_lead):
    lead = make_lead()
    built = build_lead_payload(lead, DEFAULTS)
    body = built["body"]
    assert body["contactDetails"]["phoneNumbers"] == [{"phoneNumber": "2025550199", "isPrimary": True}]
    assert "firstName" not in body["contactDetails"], "a name that is not on the lead must not be sent"
    assert "lastName" not in body["contactDetails"]
    assert body["propertyType"] == "residential"
    assert body["marketingCampignId"] == DEFAULTS.marketing_campign_id, "the API's spelling is reproduced"
    assert body["address"] == "12 Example St, Austin, TX 78701"
    assert built["warnings"], "the residential assumption is reported, not hidden"


def test_every_usable_phone_travels_with_one_primary(make_lead):
    lead = make_lead(phone="+12025550199", phone2="(512) 555-0143")
    phones = body_of(lead)["contactDetails"]["phoneNumbers"]
    assert [item["phoneNumber"] for item in phones] == ["2025550199", "5125550143"]
    assert [item["isPrimary"] for item in phones] == [True, False]


def test_a_lead_without_a_phone_is_blocked_not_guessed(make_lead):
    lead = make_lead(phone=None)
    with pytest.raises(CrmPushBlocked) as error:
        build_lead_payload(lead, DEFAULTS)
    assert error.value.reason == "needs_phone"
    assert "REsimpli requires a phone" in str(error.value)


def test_a_bad_phone_is_blocked_rather_than_truncated(make_lead):
    lead = make_lead(phone="12345")
    with pytest.raises(CrmPushBlocked) as error:
        build_lead_payload(lead, DEFAULTS)
    assert error.value.reason == "invalid_phone"


def test_land_without_an_apn_is_blocked_with_a_reason(make_lead, db):
    lead = make_lead()
    lead.properties[0].property_type = "Vacant Land"
    db.commit()
    with pytest.raises(CrmPushBlocked) as error:
        build_lead_payload(lead, DEFAULTS)
    assert error.value.reason == "land_without_apn"


def test_land_with_an_apn_sends_the_apn_it_has(make_lead, db):
    lead = make_lead()
    lead.properties[0].property_type = "land"
    lead.properties[0].property_metadata = {"facts": {"apn": "123-456-789"}}
    db.commit()
    body = body_of(lead)
    assert body["propertyType"] == "land"
    assert body["apn"] == "123-456-789"


def test_a_do_not_contact_lead_is_never_sent(make_lead, db):
    lead = make_lead()
    lead.local_do_not_contact = True
    db.commit()
    with pytest.raises(CrmPushBlocked) as error:
        build_lead_payload(lead, DEFAULTS)
    assert error.value.reason == "do_not_contact"


def test_a_lead_without_an_address_is_blocked(make_lead):
    lead = make_lead(address=None)
    assert lead_address(lead) is None
    with pytest.raises(CrmPushBlocked) as error:
        build_lead_payload(lead, DEFAULTS)
    assert error.value.reason == "missing_address"


def test_the_payload_body_is_what_the_hash_covers(make_lead):
    lead = make_lead()
    first = body_of(lead)
    second = body_of(lead)
    assert payload_hash(first) == payload_hash(second)
    changed = {**first, "address": "13 Example St, Austin, TX 78701"}
    assert payload_hash(changed) != payload_hash(first)


def test_only_lead_creation_is_an_authorized_write(live_settings):
    assert WRITE_PATHS == frozenset({"/lead/add"})
    recorder = Recorder()
    writer = recorder.writer(live_settings)
    try:
        for path in ("/lead/delete", "/lead/list", "/sms/send", "/email/send", "https://evil.test"):
            with pytest.raises(CrmWriteError) as error:
                writer.post(path, {})
            assert error.value.code == "path_not_authorized"
            assert isinstance(error.value, IntegrationError)
    finally:
        writer.close()
    assert recorder.requests == [], "a refused path must not open a socket"


def test_fixture_mode_never_writes():
    settings = Settings(_env_file=None, resimpli_mode="fixture", resimpli_api_key="not-a-real-key-000000000000")
    with pytest.raises(CrmWriteError) as error:
        ResimpliWriter(settings)
    assert error.value.code == "writes_need_live_mode"


def test_a_missing_key_is_reported_before_any_request():
    settings = Settings(_env_file=None, resimpli_mode="live", resimpli_api_key="")
    with pytest.raises(CrmWriteError) as error:
        ResimpliWriter(settings)
    assert error.value.code == "missing_api_key"


def test_the_key_travels_as_a_raw_authorization_header(live_settings):
    recorder = Recorder(httpx.Response(200, json={"ok": True}))
    writer = recorder.writer(live_settings)
    try:
        writer.add_lead({"contactDetails": {}})
    finally:
        writer.close()
    assert recorder.requests[0].headers["Authorization"] == "not-a-real-key-000000000000"


def test_rate_limiting_is_retried_and_creates_one_lead(live_settings):
    recorder = Recorder(
        httpx.Response(429, headers={"Retry-After": "1"}, json={"message": "slow down"}),
        httpx.Response(200, json={"ok": True, "data": {"_id": "abc123"}}),
    )
    writer = recorder.writer(live_settings)
    try:
        result = writer.add_lead({"contactDetails": {}})
    finally:
        writer.close()
    assert result.attempts == 2
    assert result.resimpli_lead_id == "abc123"
    assert len(recorder.requests) == 2
    assert recorder.sleeps, "the client waited before retrying"


def test_a_server_error_is_not_retried_because_the_lead_may_exist(live_settings):
    recorder = Recorder(httpx.Response(503, json={"message": "upstream"}))
    writer = recorder.writer(live_settings)
    try:
        with pytest.raises(CrmWriteError) as error:
            writer.add_lead({"contactDetails": {}})
    finally:
        writer.close()
    assert error.value.code == "outcome_unknown"
    assert len(recorder.requests) == 1


def test_a_timeout_after_sending_is_outcome_unknown_and_not_retried(live_settings):
    recorder = Recorder(httpx.ReadTimeout("timed out"))
    writer = recorder.writer(live_settings)
    try:
        with pytest.raises(CrmWriteError) as error:
            writer.add_lead({"contactDetails": {}})
    finally:
        writer.close()
    assert error.value.code == "outcome_unknown"
    assert "may exist" in str(error.value)
    assert len(recorder.requests) == 1


def test_a_connection_that_never_opened_is_safe_to_retry(live_settings):
    recorder = Recorder(
        httpx.ConnectError("refused"),
        httpx.ConnectError("refused"),
        httpx.Response(200, json={"ok": True}),
    )
    writer = recorder.writer(live_settings)
    try:
        result = writer.add_lead({"contactDetails": {}})
    finally:
        writer.close()
    assert result.attempts == 3
    assert len(recorder.requests) == 3


def test_rejected_credentials_are_not_retried(live_settings):
    recorder = Recorder(httpx.Response(401, json={"message": "bad key"}))
    writer = recorder.writer(live_settings)
    try:
        with pytest.raises(CrmWriteError) as error:
            writer.add_lead({"contactDetails": {}})
    finally:
        writer.close()
    assert error.value.code == "rejected_credentials"
    assert len(recorder.requests) == 1


def test_a_refused_payload_reports_the_short_reason_only(live_settings):
    recorder = Recorder(
        httpx.Response(400, json={"message": "marketId is required", "echo": "2025550199"})
    )
    writer = recorder.writer(live_settings)
    try:
        with pytest.raises(CrmWriteError) as error:
            writer.add_lead({"contactDetails": {}})
    finally:
        writer.close()
    assert error.value.code == "rejected_payload"
    assert "marketId is required" in str(error.value)
    assert "2025550199" not in str(error.value), "the echoed payload never reaches a message"


def test_the_request_body_is_the_reviewed_body(live_settings, make_lead):
    lead = make_lead()
    body = body_of(lead)
    recorder = Recorder(httpx.Response(200, json={"ok": True}))
    writer = recorder.writer(live_settings)
    try:
        writer.add_lead(body)
    finally:
        writer.close()
    sent = json.loads(recorder.requests[0].content)
    assert sent == body
    assert recorder.requests[0].url.path == "/api/v6/openapi/lead/add"


def test_a_lead_id_is_read_from_the_shapes_the_response_might_use():
    assert candidate_lead_ids({"leadId": "1"}) == ["1"]
    assert candidate_lead_ids({"data": {"_id": "2"}}) == ["2"]
    assert candidate_lead_ids({"data": "3"}) == ["3"]
    assert candidate_lead_ids({"ok": True}) == []


def test_an_unrecognised_response_still_counts_as_created(live_settings):
    recorder = Recorder(httpx.Response(200, json={"ok": True, "unexpected": "shape"}))
    writer = recorder.writer(live_settings)
    try:
        result = writer.add_lead({"contactDetails": {}})
    finally:
        writer.close()
    assert result.resimpli_lead_id is None
    assert result.response_keys == ["ok", "unexpected"]


@pytest.mark.parametrize(
    "value, expected",
    [("+12025550199", "2025550199"), ("(512) 555-0143", "5125550143"), ("12345", None), (None, None), ("", None)],
)
def test_phone_conversion_is_explicit(value, expected):
    assert ten_digit_phone(value) == expected


def test_an_imported_apn_reaches_the_crm_payload(db, make_lead):
    """End to end for the gap this build found: an imported parcel number used to vanish."""
    from app.services.imports import attach_property

    lead = make_lead("Dana Reyes", phone="+12025550199", address="12 Example St", state="TX")
    attach_property(
        db,
        lead,
        {
            "street_address": "12 Example St",
            "city": "Austin",
            "state": "TX",
            "property_type": "land",
            "apn": "123-456-789",
        },
    )
    db.commit()
    db.refresh(lead)

    assert lead_apn(lead) == "123-456-789"
    payload = build_lead_payload(lead, DEFAULTS)
    assert payload["body"]["propertyType"] == "land"
    assert payload["body"]["apn"] == "123-456-789"
