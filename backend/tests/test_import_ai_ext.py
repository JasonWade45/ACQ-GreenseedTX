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


def test_possessive_and_trailing_space_headers_map_and_import(client):
    """Google-Forms headers ("Seller's name ", "Phone number ", "MV") must map.

    DictReader rows are keyed by the RAW header text while the mapper works on
    stripped headers — before the strip fix every value under a header with a
    trailing space was silently dropped.
    """
    content = (
        b"Column 1,Timestamp,Killer Name ( Put your Name Here ),\"Seller's name \",\"Phone number \","
        b"Address,\"Asking price\",MV,\"Beds,Baths And Sqft\"\n"
        b"VALID,28/01/2026 21:58:31,Jonathan ,Jose Diaz,(682) 560-1911,"
        b"\"2203 Cripple Creek Dr, Arlington TX 76001\",$325k,\"260,700 $\",\"3 beds 2 baths 1,850 sqft\"\n"
    )
    inspection = _upload(client, "camp_headers.csv", content)
    auto = {k: v for k, v in inspection["auto_mapping"].items() if v}
    assert auto["full_name"] == "Seller's name"
    assert auto["phone"] == "Phone number"
    assert auto["bedrooms"] == "Beds,Baths And Sqft"
    assert auto["estimated_value"] == "MV"
    assert auto["assigned_manager"] == "Killer Name ( Put your Name Here )"
    assert auto["asking_price"] == "Asking price"

    body = _preview(client, inspection)
    assert body["missing"]["name"] == 0
    assert body["missing"]["phone"] == 0
    row = body["sample"][0]
    assert row["name"] == "Jose Diaz"
    assert "".join(ch for ch in row["phone"] if ch.isdigit()) == "6825601911"

    committed = client.post(
        f"/api/imports/{body['batch']['id']}/commit", json={"skip_duplicates": True}
    ).json()
    assert committed["imported"] == 1

    leads = client.get("/api/leads", params={"q": "Cripple Creek"}).json()
    assert leads["total"] == 1
    detail = client.get(f"/api/leads/{leads['items'][0]['id']}").json()
    assert detail["full_name"] == "Jose Diaz"
    assert detail["assigned_manager"] == "Jonathan"
    prop = detail["property"]
    assert prop["asking_price"] == 325000
    assert prop["estimated_value"] == 260700
    assert (prop["bedrooms"], prop["bathrooms"], prop["square_footage"]) == (3.0, 2.0, 1850.0)


def test_update_matched_fills_blanks_and_pushes_to_resimpli(client):
    addr = '"1604 Dowling Dr, Dallas TX 75204"'
    # 1) address-only import — the state the Camp Leads batch was left in.
    first = b"Address\n" + addr.encode() + b"\n"
    inspection = _upload(client, "update_phase1.csv", first)
    body = _preview(client, inspection, mapping={"address_line1": "Address"})
    assert body["counts"]["new"] == 1
    c1 = client.post(
        f"/api/imports/{body['batch']['id']}/commit", json={"skip_duplicates": True}
    ).json()
    assert c1["imported"] == 1
    assert c1["updated"] == 0

    leads = client.get("/api/leads", params={"q": "1604 Dowling"}).json()
    lead_id = leads["items"][0]["id"]
    detail = client.get(f"/api/leads/{lead_id}").json()
    assert detail["full_name"] == "(no name)"
    assert not detail["primary_phone"]

    # 2) same file with the name/price columns filled in → matched duplicate →
    #    the blanks get filled AND the lead is pushed to REsimpli (now it has a phone).
    second = (
        b'"Seller\'s name","Phone number",Address,"Asking price"\n'
        b"Jose Diaz,(682) 560-1911," + addr.encode() + b",$310k\n"
    )
    inspection2 = _upload(client, "update_phase2.csv", second)
    body2 = _preview(client, inspection2)
    assert body2["counts"]["same_property_diff_seller"] == 1
    c2 = client.post(
        f"/api/imports/{body2['batch']['id']}/commit",
        json={
            "skip_duplicates": True,
            "update_matched": True,
            "external": {"enabled": True, "force_mock": True},
        },
    ).json()
    assert c2["updated"] == 1
    assert c2["imported"] == 0
    assert c2["failed"] == 0
    assert c2["skipped"] == 0
    assert c2["external"]["pushed"] == 1
    assert c2["external"]["failed"] == 0
    assert c2["external"]["errors"] == []

    detail = client.get(f"/api/leads/{lead_id}").json()
    assert detail["full_name"] == "Jose Diaz"
    assert "".join(ch for ch in detail["primary_phone"] if ch.isdigit()) == "6825601911"
    assert str(detail["external_id"]).startswith("mock_")
    assert detail["property"]["asking_price"] == 310000

    # 3) identical file once more → nothing left to learn → honest skip.
    inspection3 = _upload(client, "update_phase3.csv", second)
    body3 = _preview(client, inspection3)
    c3 = client.post(
        f"/api/imports/{body3['batch']['id']}/commit",
        json={
            "skip_duplicates": True,
            "update_matched": True,
            "external": {"enabled": True, "force_mock": True},
        },
    ).json()
    assert c3["updated"] == 0
    assert c3["imported"] == 0
    assert c3["skipped"] == 1


def test_update_matched_never_overwrites_existing_values(client):
    addr = "9 Oak St Columbus OH"
    first = (
        f"Address,Lead Name,Phone,Email\n\"{addr}\",Old Name,614-555-0100,old@example.com\n"
    ).encode()
    inspection = _upload(client, "keep1.csv", first)
    body = _preview(client, inspection)
    assert body["counts"]["new"] == 1
    client.post(f"/api/imports/{body['batch']['id']}/commit", json={"skip_duplicates": True})

    # Same property, different contact details: the existing identity wins.
    second = (
        f"Address,Lead Name,Phone,Email\n\"{addr}\",New Name,614-555-0199,new@example.com\n"
    ).encode()
    inspection2 = _upload(client, "keep2.csv", second)
    body2 = _preview(client, inspection2)
    assert body2["counts"]["same_property_diff_seller"] == 1
    c2 = client.post(
        f"/api/imports/{body2['batch']['id']}/commit",
        json={"skip_duplicates": True, "update_matched": True},
    ).json()
    assert c2["updated"] == 0  # nothing was empty → nothing changed
    assert c2["skipped"] == 1

    leads = client.get("/api/leads", params={"q": "9 Oak St"}).json()
    detail = client.get(f"/api/leads/{leads['items'][0]['id']}").json()
    assert detail["full_name"] == "Old Name"
    assert detail["email"] == "old@example.com"
    assert "".join(ch for ch in detail["primary_phone"] if ch.isdigit()) == "6145550100"


def test_update_targets_property_lead_and_skips_duplicate_crm_push(client, make_lead):
    """The same seller recorded twice (CRM lead + nameless property twin).

    The row must complete the NAMELESS twin (the lead that needs the data) and
    must NOT push the person into REsimpli again — they already live there.
    """
    crm = make_lead(
        name="CRM Guy",
        phone="214-555-0111",
        address="1 CRM St",
        city="Dallas",
        state="TX",
        zip_code="75201",
        origin="resimpli",
        external_id="ext_crm_1",
    )

    # Nameless twin: address-only import (the state the Camp batch is in).
    twin_file = b'Address\n"2 Twin St Dallas TX 75202"\n'
    inspection = _upload(client, "p5_twin.csv", twin_file)
    body = _preview(client, inspection, mapping={"address_line1": "Address"})
    assert body["counts"]["new"] == 1
    client.post(f"/api/imports/{body['batch']['id']}/commit", json={"skip_duplicates": True})
    twins = client.get("/api/leads", params={"q": "2 Twin St"}).json()
    twin_id = twins["items"][0]["id"]
    assert twin_id != crm.id

    # One row: the CRM person's phone + the twin's property.
    row = (
        b"Address,Lead Name,Phone,Asking price\n"
        b'"2 Twin St Dallas TX 75202",CRM Guy,214-555-0111,$150k\n'
    )
    inspection2 = _upload(client, "p5_row.csv", row)
    body2 = _preview(client, inspection2)
    assert body2["counts"]["same_seller_diff_property"] == 1
    assert "property lead" in body2["sample"][0]["reason"]

    committed = client.post(
        f"/api/imports/{body2['batch']['id']}/commit",
        json={
            "skip_duplicates": True,
            "update_matched": True,
            "external": {"enabled": True, "force_mock": True},
        },
    ).json()
    assert committed["updated"] == 1
    assert committed["imported"] == 0
    assert committed["external"]["pushed"] == 0  # person already in REsimpli
    assert committed["external"]["skipped_existing_crm"] == 1
    assert committed["external"]["failed"] == 0

    twin = client.get(f"/api/leads/{twin_id}").json()
    assert twin["full_name"] == "CRM Guy"
    assert "".join(ch for ch in twin["primary_phone"] if ch.isdigit()) == "2145550111"
    assert twin["property"]["asking_price"] == 150000

    crm_after = client.get(f"/api/leads/{crm.id}").json()
    assert crm_after["property"]["address_line1"] == "1 CRM St"  # untouched
    assert crm_after["external_id"] == "ext_crm_1"


def test_within_file_second_property_fills_twin_and_pushes_once(client):
    """Two file rows: one seller, two properties — both property leads get
    filled, but the person is pushed into REsimpli only once."""
    twin_file = b'Address\n"5 Elm St Austin TX"\n"7 Elm St Austin TX"\n'
    inspection = _upload(client, "wf_twin.csv", twin_file)
    body = _preview(client, inspection, mapping={"address_line1": "Address"})
    assert body["counts"]["new"] == 2
    client.post(f"/api/imports/{body['batch']['id']}/commit", json={"skip_duplicates": True})

    rows = (
        b"Address,Lead Name,Phone,Asking price\n"
        b'"5 Elm St Austin TX",Ann Lee,512-555-0142,$100k\n'
        b'"7 Elm St Austin TX",Ann Lee,512-555-0142,$110k\n'
    )
    inspection2 = _upload(client, "wf_row.csv", rows)
    body2 = _preview(client, inspection2)
    # Row 2 repeats row 1's phone on a different property → NOT a verbatim
    # duplicate; it must reach the DB dedupe so its property lead can update.
    assert body2["counts"]["exact_duplicate"] == 0
    assert body2["counts"]["same_property_diff_seller"] == 2

    committed = client.post(
        f"/api/imports/{body2['batch']['id']}/commit",
        json={
            "skip_duplicates": True,
            "update_matched": True,
            "external": {"enabled": True, "force_mock": True},
        },
    ).json()
    assert committed["updated"] == 2
    assert committed["failed"] == 0
    assert committed["external"]["pushed"] == 1  # second row: same person
    assert committed["external"]["skipped_existing_crm"] == 1
    assert committed["external"]["failed"] == 0

    seen_external = []
    for addr, price in (("5 Elm St", 100000), ("7 Elm St", 110000)):
        leads = client.get("/api/leads", params={"q": addr}).json()
        detail = client.get(f"/api/leads/{leads['items'][0]['id']}").json()
        assert detail["full_name"] == "Ann Lee"
        assert "".join(ch for ch in detail["primary_phone"] if ch.isdigit()).endswith("5125550142")
        assert detail["property"]["asking_price"] == price
        seen_external.append(bool(detail["external_id"]))
    assert sum(seen_external) == 1  # exactly one lead owns the REsimpli id
