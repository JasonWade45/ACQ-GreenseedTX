"""AI column mapping, missing-info report, name dedupe, external /lead/add push."""
from __future__ import annotations

from pathlib import Path

from app.services import ai_service, import_service
from app.services.dedupe import LIKELY, NEW, Candidate, find_matches

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "sample_seller_leads.csv"

WEIRD_HEADERS = "Owner,Prop Addr,Call This Number,Mailbox,Why They Selling\n"


def _upload(client, name: str, content: bytes) -> dict:
    response = client.post(
        "/api/imports/upload",
        files={"file": (name, content, "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _preview(client, inspection: dict, mapping: dict | None = None) -> dict:
    response = client.post(
        "/api/imports/preview",
        params={"file": inspection["stored_path"]},
        json={"mapping": mapping or {k: v for k, v in inspection["auto_mapping"].items() if v}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_ai_map_keeps_rules_result_when_all_headers_known(client):
    with SAMPLE.open("rb") as handle:
        inspection = _upload(client, "sample_seller_leads.csv", handle.read())
    result = client.post(
        "/api/imports/ai-map",
        json={"file": inspection["stored_path"], "mapping": {}},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["engine"] == "rules"  # alias table covered every header -> no model call
    assert body["mapping"]["phone"] == "Phone Number"
    assert body["unmapped_headers"] == []


def test_ai_map_calls_model_for_unmapped_headers(client, monkeypatch):
    content = (WEIRD_HEADERS + 'John Doe,123 Main St Columbus OH,614-555-0142,j@x.com,"wants cash close"\n').encode()
    inspection = _upload(client, "weird.csv", content)

    calls: dict = {}

    def fake_map(headers, samples, targets):
        calls["headers"] = headers
        assert "Prop Addr" in headers and samples["Prop Addr"] == ["123 Main St Columbus OH"]
        return (
            {
                "address_line1": "Prop Addr",
                "phone": "Call This Number",
                "email": "Mailbox",
                "motivation": "Why They Selling",
                "notes": "Ghost Header",  # not a real header -> must be dropped
            },
            "groq",
            None,
        )

    monkeypatch.setattr(ai_service, "ai_map_columns", fake_map)
    body = client.post(
        "/api/imports/ai-map",
        json={"file": inspection["stored_path"], "mapping": {}},
    ).json()
    assert body["engine"] == "groq"
    assert body["mapping"]["address_line1"] == "Prop Addr"
    assert body["mapping"]["phone"] == "Call This Number"
    assert body["mapping"]["email"] == "Mailbox"
    assert body["mapping"]["motivation"] == "Why They Selling"
    assert body["mapping"]["notes"] is None  # unknown header rejected
    assert body["unmapped_headers"] == []
    assert set(calls["headers"]) == {"Prop Addr", "Call This Number", "Mailbox", "Why They Selling"}


def test_ai_map_without_model_stays_rules(client):
    content = (WEIRD_HEADERS + "Jane Roe,9 Elm St Dallas TX,214-555-0199,jane@x.com,retiring\n").encode()
    inspection = _upload(client, "weird2.csv", content)
    body = client.post("/api/imports/ai-map", json={"file": inspection["stored_path"], "mapping": {}}).json()
    assert body["engine"] == "rules"  # GROQ key blank in tests, Ollama unreachable
    assert body["mapping"]["assigned_manager"] == "Owner"  # rule-based part still applied
    assert body["mapping"]["phone"] is None
    assert "Call This Number" in body["unmapped_headers"]


def test_preview_reports_missing_info(client):
    with SAMPLE.open("rb") as handle:
        inspection = _upload(client, "sample_seller_leads.csv", handle.read())
    body = _preview(client, inspection)
    missing = body["missing"]
    assert set(missing) == {"phone", "email", "address", "name"}
    assert missing["phone"] == 0  # every sample row carries a phone
    assert missing["email"] >= 1  # RSL-1004 and RSL-1012 have no email
    assert missing["address"] >= 1  # RSL-1012's address column is empty
    assert missing["name"] == 0


def test_name_only_match_flagged_for_review(db, make_lead):
    make_lead(name="Michael O'Brien", phone=None, email=None, address=None)
    result = find_matches(db, Candidate(first_name="Michael", last_name="Obrien"))
    assert result.status == LIKELY
    assert "name" in result.reason

    other = find_matches(db, Candidate(first_name="Completely", last_name="Different"))
    assert other.status == NEW


def test_external_config_defaults_and_override(client):
    body = client.get("/api/imports/external-config").json()
    assert body["available"] is True
    assert body["source"] == "known"
    assert body["ids"]["pipelineId"] == import_service.KNOWN_LEAD_IDS["pipelineId"]

    saved = client.post(
        "/api/imports/external-config",
        json={
            "pipelineId": "custom_pipeline_1",
            "mainStatusId": "custom_status_1",
            "marketId": "custom_market_1",
            "marketingCampignId": "custom_campaign_1",
        },
    ).json()
    assert saved["source"] == "settings"
    assert saved["ids"]["pipelineId"] == "custom_pipeline_1"
    assert saved["ids"]["marketId"] == "custom_market_1"


def test_commit_with_external_pushes_to_mock_resimpli(client):
    # Two rows: one pushable, one with no phone (REsimpli requires one).
    content = (
        b"Lead Name,Phone,Email,Address\n"
        b"Alice Wonder,214-555-0101,alice@example.com,\"10 First St\"\n"
        b"Bob No-Phone,,,\"20 Second St\"\n"
    )
    inspection = _upload(client, "external_test.csv", content)
    body = _preview(client, inspection)
    batch_id = body["batch"]["id"]

    committed = client.post(
        f"/api/imports/{batch_id}/commit",
        json={"skip_duplicates": True, "external": {"enabled": True, "force_mock": True}},
    )
    assert committed.status_code == 200, committed.text
    summary = committed.json()
    assert summary["imported"] == 2
    ext = summary["external"]
    assert ext["enabled"] is True
    assert ext["ids"]["marketingCampignId"] == import_service.KNOWN_LEAD_IDS["marketingCampignId"]
    assert ext["pushed"] == 1
    assert ext["failed"] == 0  # no API errors — the phone-less row is a skip, not a failure
    assert ext["skipped_no_phone"] == 1  # Bob has no phone -> local only
    assert ext["pushed"] + ext["skipped_no_phone"] == summary["imported"]
    assert ext["errors"] == []

    pushed = client.get("/api/leads", params={"origin": "import"}).json()
    ids = [row.get("external_id") for row in pushed["items"]]
    assert any(str(i).startswith("mock_") for i in ids if i)


def test_commit_external_disabled_reports_off(client):
    with SAMPLE.open("rb") as handle:
        inspection = _upload(client, "sample_seller_leads.csv", handle.read())
    body = _preview(client, inspection)
    committed = client.post(
        f"/api/imports/{body['batch']['id']}/commit",
        json={"skip_duplicates": True},
    ).json()
    assert committed["external"]["enabled"] is False
    assert committed["external"]["pushed"] == 0


def test_commit_external_requires_api_key(client):
    with SAMPLE.open("rb") as handle:
        inspection = _upload(client, "sample_seller_leads.csv", handle.read())
    body = _preview(client, inspection)
    # tests run with RESIMPLI_MOCK=true and no force_mock -> refused before any write
    response = client.post(
        f"/api/imports/{body['batch']['id']}/commit",
        json={"external": {"enabled": True}},
    )
    assert response.status_code == 400
    assert "API key" in response.json()["detail"]


def test_address_only_rows_import_and_unidentifiable_row_rejected(client):
    # A fully blank line is dropped by the reader; this row has a cell (a note)
    # but no address/name/phone/email — it must still be rejected.
    content = b"Address,Motivation\n\"2203 Cripple Creek Dr\",\n,\"wants cash\"\n"
    inspection = _upload(client, "address_only.csv", content)
    body = _preview(client, inspection, mapping={"address_line1": "Address"})
    counts = body["counts"]
    assert counts["new"] == 1  # address-only row is now a usable lead
    assert counts["rejected"] == 1  # nothing identifiable to import
    accepted = next(s for s in body["sample"] if s["status"] == "new")
    assert any("Address-only row" in w for w in accepted["warnings"])
    rejected = next(s for s in body["sample"] if s["status"] == "rejected")
    assert "no phone, email, seller name or property address" in (rejected["reason"] or "")


def test_compound_property_cells_and_honest_ranges():
    from app.services.import_service import normalize_row
    from app.services.normalization import extract_property_details, normalize_money

    assert extract_property_details("4 & 2")[:3] == (4.0, 2.0, None)
    assert extract_property_details("3 & 1 and half")[:3] == (3.0, 1.5, None)
    assert extract_property_details("3 beds 3 baths 2,007 sqft")[:3] == (3.0, 3.0, 2007.0)
    beds, baths, sqft, warns = extract_property_details("first one 4 & 2 2rd 3 & 1")
    assert (beds, baths, sqft) == (None, None, None) and warns  # multi-unit: never guessed

    assert normalize_money("$133,916 Redfin")[0] == 133916.0
    assert normalize_money("2,007 sqft")[0] == 2007.0
    assert normalize_money("200k")[0] == 200000.0
    assert normalize_money("(1,000)")[0] == -1000.0
    value, warns = normalize_money("range from 200k to 250k")
    assert value is None and any("multiple values" in w for w in warns)

    row = normalize_row(
        {"Details": "3 beds 3 baths 2,007 sqft", "Addr": "9 Oak St"},
        {"bedrooms": "Details", "address_line1": "Addr"},
        2,
    )
    assert row.errors == []
    assert (row.bedrooms, row.bathrooms, row.square_footage) == (3.0, 3.0, 2007.0)


def test_compound_details_survive_commit(client):
    content = b"Details,Address\n\"3 beds 3 baths 2,007 sqft\",\"9 Oak St Columbus OH\"\n"
    inspection = _upload(client, "details.csv", content)
    body = _preview(
        client, inspection, mapping={"bedrooms": "Details", "address_line1": "Address"}
    )
    assert body["counts"]["new"] == 1
    committed = client.post(
        f"/api/imports/{body['batch']['id']}/commit", json={"skip_duplicates": True}
    ).json()
    assert committed["imported"] == 1

    leads = client.get("/api/leads", params={"q": "9 Oak St"}).json()
    assert leads["total"] == 1
    detail = client.get(f"/api/leads/{leads['items'][0]['id']}").json()
    prop = detail["property"]
    assert prop["bedrooms"] == 3.0
    assert prop["bathrooms"] == 3.0
    assert prop["square_footage"] == 2007.0
