"""Phase 2/3: Data Syndicate address-only import, skip-trace loop and context fields."""

from pathlib import Path


from app.models import Lead, LeadPhone
from app.services import skip_trace
from app.services.imports import create_local_lead
from app.services.normalization import normalize_record, guess_mapping

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "sample-data-syndicate.csv"


def _upload(client, profile="auto"):
    with SAMPLE.open("rb") as handle:
        response = client.post(
            f"/api/imports/upload?profile={profile}",
            files={"file": ("sample-data-syndicate.csv", handle, "text/csv")},
        )
    assert response.status_code == 200, response.text
    return response.json()


def _preview_and_approve(client, batch, resolutions=None, fill_missing=False):
    mapping = batch["sheets"]["CSV"]["suggested_mapping"]
    preview = client.post(
        f"/api/imports/{batch['id']}/preview",
        json={"sheets": ["CSV"], "mapping": mapping, "date_order": "MDY"},
    )
    assert preview.status_code == 200, preview.text
    eligible = client.get(f"/api/imports/{batch['id']}/eligible-ids").json()
    approved = client.post(
        f"/api/imports/{batch['id']}/approve",
        json={
            "row_ids": eligible["row_ids"] + eligible["update_row_ids"],
            "resolutions": resolutions or {},
            "confirmation": "IMPORT LOCAL",
            "fill_missing": fill_missing,
        },
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def test_data_syndicate_headers_are_recognised():
    headers = [
        "Flags",
        "Compatible Offers",
        "Recorded Date",
        "Sale Likelihood",
        "Estimated Equity (%)",
        "County",
        "Lead Type",
        "Address",
        "City",
        "State",
        "Zip",
        "Expand details",
    ]
    mapping = guess_mapping(headers)
    assert mapping["Address"] == "street_address"
    assert mapping["Sale Likelihood"] == "score"
    assert mapping["Estimated Equity (%)"] == "equity_pct"
    assert mapping["Flags"] == "ds_flags"
    assert mapping["Compatible Offers"] == "ds_compatible_offers"
    assert mapping["Recorded Date"] == "recorded_date"
    assert "Expand details" not in mapping


def test_address_only_profile_rejects_an_address_without_state():
    data, errors, _ = normalize_record(
        {"Address": "123 Main St", "City": "Austin", "Zip": ""},
        {"Address": "street_address", "City": "city", "Zip": "zip_code"},
        "America/New_York",
        "MDY",
        profile="address_only",
    )
    assert data.get("street_address") == "123 Main St"
    assert any("state" in error.lower() for error in errors)


def test_full_import_creates_58_address_only_leads(client, db):
    batch = _upload(client)
    assert batch["profile"] == "address_only"
    approved = _preview_and_approve(client, batch)
    assert approved["counts"]["imported"] == 58, approved["counts"]
    leads = db.query(Lead).all()
    assert len(leads) == 58
    assert all(lead.needs_skip_trace for lead in leads)
    assert all(lead.outreach_mode == "cold" for lead in leads)
    assert all(str(lead.external_id).startswith("ds:") for lead in leads)
    assert all(lead.primary_phone is None and not lead.full_name for lead in leads)

    first = db.query(Lead).filter(Lead.score == 87.1).one()
    assert first.heat == "HOT"
    assert first.equity_pct == -3.0
    assert first.lead_type == "Tax Deed Sale"
    assert first.ds_flags.get("free_and_clear") is True
    assert "Vendor Specific Flag" in first.ds_extra_flags
    assert first.ds_flags_raw.startswith("Free & Clear")
    assert "Seller Finance" in first.ds_compatible_offers

    second = db.query(Lead).filter(Lead.score == 92.4).one()
    assert second.heat == "VERY_HOT"
    assert second.equity_pct == 100.0


def test_dekalb_georgia_rows_are_out_of_license(client, db):
    batch = _upload(client)
    _preview_and_approve(client, batch)
    georgia = [lead for lead in db.query(Lead).all() if lead.properties[0].state == "GA"]
    assert len(georgia) == 5
    assert all(lead.in_license is False for lead in georgia)


def test_reimport_is_idempotent_and_never_overwrites_a_manual_edit(client, db):
    batch = _upload(client)
    _preview_and_approve(client, batch)
    lead = db.query(Lead).filter(Lead.score == 87.1).one()
    # Jason corrects the county by hand.
    edited = client.patch(
        f"/api/leads/{lead.id}/fields",
        json={"fields": {"county": "Parker", "lead_type": "Probate"}, "confirm": True},
    )
    assert edited.status_code == 200, edited.text
    assert "county" in edited.json()["user_edited_fields"]

    # The same file again is recognised as the same batch (no second copy).
    again = _upload(client)
    assert again["id"] == batch["id"]
    assert again["repeated_file"] is True

    # A changed vendor file (new checksum) refreshes the same leads, not new ones.
    content = SAMPLE.read_text(encoding="utf-8").replace("87.1 Score HOT", "95.5 Score VERY HOT")
    response = client.post(
        "/api/imports/upload?profile=auto",
        files={"file": ("sample-data-syndicate-v2.csv", content.encode(), "text/csv")},
    )
    changed_batch = response.json()
    mapping = changed_batch["sheets"]["CSV"]["suggested_mapping"]
    assert client.post(
        f"/api/imports/{changed_batch['id']}/preview",
        json={"sheets": ["CSV"], "mapping": mapping, "date_order": "MDY"},
    ).status_code == 200
    eligible = client.get(f"/api/imports/{changed_batch['id']}/eligible-ids").json()
    assert eligible["row_ids"] == []
    assert len(eligible["update_row_ids"]) == 58
    resolutions = {str(row): "update" for row in eligible["update_row_ids"]}
    result = client.post(
        f"/api/imports/{changed_batch['id']}/approve",
        json={"row_ids": eligible["update_row_ids"], "resolutions": resolutions, "confirmation": "IMPORT LOCAL"},
    )
    assert result.status_code == 200, result.text
    assert db.query(Lead).count() == 58
    refreshed = db.query(Lead).filter(Lead.score == 95.5).one()
    assert refreshed.id == lead.id
    # Manually edited fields survived; vendor fields refreshed.
    assert refreshed.county == "Parker"
    assert refreshed.lead_type == "Probate"
    assert refreshed.heat == "VERY_HOT"


def test_reimport_requires_an_explicit_resolution(client, db):
    batch = _upload(client)
    _preview_and_approve(client, batch)
    content = SAMPLE.read_text(encoding="utf-8").replace("87.1 Score HOT", "88.1 Score HOT")
    response = client.post(
        "/api/imports/upload",
        files={"file": ("v3.csv", content.encode(), "text/csv")},
    )
    changed = response.json()
    mapping = changed["sheets"]["CSV"]["suggested_mapping"]
    client.post(
        f"/api/imports/{changed['id']}/preview",
        json={"sheets": ["CSV"], "mapping": mapping, "date_order": "MDY"},
    )
    eligible = client.get(f"/api/imports/{changed['id']}/eligible-ids").json()
    bad = client.post(
        f"/api/imports/{changed['id']}/approve",
        json={"row_ids": eligible["update_row_ids"], "confirmation": "IMPORT LOCAL"},
    )
    assert bad.status_code == 400
    assert "resolve duplicate" in bad.json()["detail"].lower()


def _skip_traced_lead(db, **extra):
    data = {
        "full_name": "Dana Seller",
        "primary_phone": "+12025550143",
        "street_address": "1000 Oak Ridge Dr",
        "city": "Arlington",
        "state": "TX",
        "zip_code": "76015",
        "normalized_address": "1000oakridgedr|arlington|tx|76015",
        "external_id": "ds:1000oakridgedr|arlington|tx|76015",
        "outreach_mode": "cold",
        **extra,
    }
    lead = create_local_lead(db, data, data, source_kind="import")
    db.commit()
    return lead


def test_skip_trace_export_lists_only_address_only_leads(client, db):
    batch = _upload(client)
    _preview_and_approve(client, batch)
    summary = client.get("/api/skip-trace/summary").json()
    assert summary["needs_skip_trace"] == 53  # the five Georgia leads are out of license
    exported = client.get("/api/skip-trace/export")
    assert exported.status_code == 200
    body = exported.content.decode("utf-8-sig")
    assert "lead_key,address,city,state,zip" in body
    assert "Decatur" not in body


def test_skip_trace_results_complete_the_loop(client, db):
    batch = _upload(client)
    _preview_and_approve(client, batch)
    lead = db.query(Lead).filter(Lead.score == 87.1).one()
    key = lead.external_id
    results = (
        "lead_key,owner_name,phone1,phone2,email\n"
        f"{key},Dana Seller,202-555-0143,202-555-0199,dana@example.com\n"
        "ds:does-not-exist,Nobody Here,202-555-0101,,\n"
    )
    upload = client.post(
        "/api/skip-trace/upload",
        files={"file": ("results.csv", results.encode(), "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    body = upload.json()
    assert body["counts"]["matched"] == 1
    assert body["counts"]["rejected"] == 1

    preview = client.post(f"/api/skip-trace/{body['batch_id']}/preview")
    assert preview.status_code == 200
    rejected = client.get(f"/api/skip-trace/{body['batch_id']}/rejected")
    assert "does not match" in rejected.content.decode("utf-8-sig")

    not_confirmed = client.post(f"/api/skip-trace/{body['batch_id']}/apply", json={"confirmation": "yes"})
    assert not_confirmed.status_code == 400

    applied = client.post(
        f"/api/skip-trace/{body['batch_id']}/apply", json={"confirmation": "IMPORT LOCAL"}
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] == 1
    db.expire_all()
    refreshed = db.get(Lead, lead.id)
    assert refreshed.needs_skip_trace is False
    assert refreshed.full_name == "Dana Seller"
    assert refreshed.primary_phone == "+12025550143"
    assert refreshed.stage_code == "not_contacted"
    assert {phone.phone_normalized for phone in refreshed.phones} == {"+12025550143", "+12025550199"}
    assert refreshed.in_license is True


def test_skip_trace_never_silently_replaces_a_crm_phone(client, db, make_lead):
    lead = make_lead(
        name="Crm Owner",
        phone="+12025550111",
        external_id="ds:crm|tx|76015",
        needs_skip_trace=True,
        outreach_mode="cold",
    )
    lead.source_kind = "resimpli"
    db.commit()
    results = (
        "lead_key,owner_name,phone1\n"
        f"{lead.external_id},Skip Trace Name,202-555-0155\n"
    )
    body = client.post(
        "/api/skip-trace/upload", files={"file": ("r.csv", results.encode(), "text/csv")}
    ).json()
    preview = client.post(f"/api/skip-trace/{body['batch_id']}/preview").json()
    assert preview["rows"][0]["incoming"]["phones"] == ["+12025550155"]
    # Default (no explicit overwrite) keeps the CRM number.
    applied = client.post(f"/api/skip-trace/{body['batch_id']}/apply", json={"confirmation": "IMPORT LOCAL"})
    assert applied.status_code == 200
    db.expire_all()
    refreshed = db.get(Lead, lead.id)
    assert refreshed.primary_phone == "+12025550111"
    assert "+12025550155" in {phone.phone_normalized for phone in refreshed.phones}


def test_manual_field_edit_requires_confirmation_and_is_audited(client, db):
    lead = _skip_traced_lead(db)
    no_confirm = client.patch(f"/api/leads/{lead.id}/fields", json={"fields": {"county": "Dallas"}, "confirm": False})
    assert no_confirm.status_code == 400
    bad_field = client.patch(
        f"/api/leads/{lead.id}/fields", json={"fields": {"external_id": "x"}, "confirm": True}
    )
    assert bad_field.status_code == 400
    ok = client.patch(f"/api/leads/{lead.id}/fields", json={"fields": {"county": "Dallas"}, "confirm": True})
    assert ok.status_code == 200 and ok.json()["updated"] == 1
    audit = client.get("/api/audit?limit=5").json()
    assert any(row["action"] == "lead_field_edited" for row in audit)


def test_data_syndicate_filters_and_sorting(client, db):
    batch = _upload(client)
    _preview_and_approve(client, batch)
    hot = client.get("/api/leads?heat=VERY_HOT").json()
    assert hot["total"] >= 1
    assert all(item["heat"] == "VERY_HOT" for item in hot["items"])
    negative = client.get("/api/leads?max_equity=0").json()
    assert negative["total"] == 1 and negative["items"][0]["equity_pct"] == -3.0
    by_flags = client.get("/api/leads?flags=senior_owner").json()
    assert by_flags["total"] >= 1
    by_offer = client.get("/api/leads?offer=Novation").json()
    assert by_offer["total"] >= 1
    skip = client.get("/api/leads?needs_skip_trace=true").json()
    assert skip["total"] == 58
    top = db.query(Lead).order_by(Lead.score.desc()).first().score
    sorted_rows = client.get("/api/leads?sort=score&direction=desc&page_size=5").json()
    assert sorted_rows["items"][0]["score"] == top
    assert client.get("/api/leads?sort=not_a_field").status_code == 400


def test_phone_slots_are_stored_individually(db):
    data = {
        "full_name": "Multi Phone",
        "primary_phone": "+12025550142",
        "street_address": "5 Test St",
        "city": "Fort Worth",
        "state": "TX",
        "zip_code": "76107",
    }
    lead = create_local_lead(db, {**data, "phones": [{"number": "+12025550142"}, {"number": "+12025550177"}]}, data)
    db.commit()
    assert db.query(LeadPhone).filter(LeadPhone.lead_id == lead.id).count() == 2
    assert skip_trace.RESULT_HEADERS[0] == "lead_key"
