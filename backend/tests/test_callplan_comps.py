"""Pre-call plan (script + question checklist), property extraction, comps brief."""
from __future__ import annotations

from app.services.ai_service import _repair_mojibake
from app.services.comps import comps_brief
from app.services.property_extract import apply_property_data, extract_property_facts

SAMPLE_PAYLOAD = {
    "propertyInfo": {
        "stateAddress": "10312 Arvin Hill Rd",
        "city": "Aubrey",
        "state": "TX",
        "zip": "76227",
        "county": "Denton County",
        "propertyType": "SFR",
        "bedRoomCount": 3,
        "bathRoomCount": 3,
        "livingArea": 3910,
        "yearBuilt": 1992,
        "lotSizeAcres": 2.8,
        "latitude": 33.25953025299243,
        "longitude": -97.01487953653279,
        "ownerOccupied": True,
        "isAbsenteeOwner": False,
        "yearsOwned": 73,
        "equityPercent": 60,
        "vacant": False,
    },
    "valuation": {"estValue": 1210000, "estEquity": 699399, "estProfit": 0},
    "taxInfo": {
        "totalAssessedValue": 888341,
        "totalmarketValue": 907219,
        "taxYear": 2025,
        "propertyTaxes": 10289.64,
        "taxDelinquentYear": 0,
    },
    "mortgageInfo": {"amount": 510400, "lenderName": "First Bank"},
    "mlsInfo": {"status": None, "price": 0},
    "lastSaleInfo": {"saleDate": 1595203200000, "saleAmount": 0},
}


def test_extract_maps_payload_into_columns():
    facts = extract_property_facts(SAMPLE_PAYLOAD)
    assert facts is not None
    assert facts["address_line1"] == "10312 Arvin Hill Rd"
    assert facts["city"] == "Aubrey"
    assert facts["zip_code"] == "76227"
    assert facts["bedrooms"] == 3.0
    assert facts["bathrooms"] == 3.0
    assert facts["square_footage"] == 3910.0
    assert facts["year_built"] == 1992
    assert facts["county"] == "Denton County"
    assert facts["lot_acres"] == 2.8
    assert facts["estimated_value"] == 1210000.0
    assert facts["extra"]["valuation"]["estEquity"] == 699399
    assert facts["extra"]["mortgage"]["lenderName"] == "First Bank"


def test_extract_returns_none_without_property_blocks():
    assert extract_property_facts(None) is None
    assert extract_property_facts({}) is None
    assert extract_property_facts({"_id": "x", "crmQuestionId": "y"}) is None


def test_apply_property_data_merges_without_wiping(db, make_lead):
    lead = make_lead()
    prop = apply_property_data(db, lead, SAMPLE_PAYLOAD)
    db.commit()
    assert prop is not None
    assert prop.bedrooms == 3.0
    assert prop.county == "Denton County"
    # A later payload without beds must never wipe what we already extracted.
    apply_property_data(db, lead, {"valuation": {"estValue": 999000}})
    db.commit()
    db.refresh(prop)
    assert prop.bedrooms == 3.0
    assert prop.estimated_value == 999000.0
    # Newest value wins inside the block; sibling keys survive the merge.
    assert prop.extra["valuation"]["estValue"] == 999000
    assert prop.extra["valuation"]["estEquity"] == 699399
    assert prop.extra["mortgage"]["lenderName"] == "First Bank"


def test_call_plan_rules_engine_has_opener_and_checklist(client, make_lead):
    lead = make_lead()
    res = client.post(f"/api/ai/call-plan/{lead.id}")
    assert res.status_code == 200
    plan = res.json()
    assert plan["refusal_reason"] is None
    assert plan["engine"] == "rules"  # GROQ key is empty in tests
    assert "Did I catch you at a good time" in plan["opener"]
    assert "[your name]" in plan["opener"]
    assert len(plan["questions"]) >= 5
    required = [q["text"].lower() for q in plan["questions"] if q["required"]]
    assert any("reason" in t for t in required)
    assert any("timeline" in t for t in required)
    assert any("price" in t for t in required)
    assert all("asked" in q for q in plan["questions"])
    assert all("used" in p for p in plan["talking_points"])
    assert plan["do_not_say"]


def test_call_plan_checkbox_state_persists(client, make_lead):
    lead = make_lead()
    client.post(f"/api/ai/call-plan/{lead.id}")
    plan = client.get(f"/api/ai/call-plan/{lead.id}").json()
    assert plan is not None
    plan["questions"][0]["asked"] = True
    if plan["talking_points"]:
        plan["talking_points"][0]["used"] = True
    res = client.patch(
        f"/api/ai/call-plan/{lead.id}",
        json={"questions": plan["questions"], "talking_points": plan["talking_points"]},
    )
    assert res.status_code == 200
    again = client.get(f"/api/ai/call-plan/{lead.id}").json()
    assert again["questions"][0]["asked"] is True
    assert len(again["questions"]) == len(plan["questions"])
    if plan["talking_points"]:
        assert again["talking_points"][0]["used"] is True


def test_call_plan_patch_without_plan_is_rejected(client, make_lead):
    lead = make_lead()
    res = client.patch(f"/api/ai/call-plan/{lead.id}", json={"questions": []})
    assert res.status_code == 400


def test_call_plan_refused_for_dnc(client, make_lead):
    lead = make_lead(do_not_contact=True)
    plan = client.post(f"/api/ai/call-plan/{lead.id}").json()
    assert plan["refusal_reason"]
    assert plan["opener"] is None
    assert plan["questions"] == []


def test_call_plan_refused_without_phone(client, make_lead):
    lead = make_lead(phone=None)
    plan = client.post(f"/api/ai/call-plan/{lead.id}").json()
    assert plan["refusal_reason"]
    assert "phone" in plan["refusal_reason"].lower()


def test_lead_detail_includes_call_plan(client, make_lead):
    lead = make_lead()
    client.post(f"/api/ai/call-plan/{lead.id}")
    detail = client.get(f"/api/leads/{lead.id}").json()
    assert detail["call_plan"] is not None
    assert detail["call_plan"]["opener"]


def test_comps_brief_derives_criteria_and_links(client, db, make_lead):
    lead = make_lead()
    apply_property_data(db, lead, SAMPLE_PAYLOAD)
    db.commit()
    res = client.get(f"/api/leads/{lead.id}/comps")
    assert res.status_code == 200
    data = res.json()
    assert data["subject"]["beds"] == 3.0
    crit = data["criteria"]
    assert crit["beds_min"] == 2 and crit["beds_max"] == 4
    assert crit["sqft_min"] == 3128 and crit["sqft_max"] == 4692
    assert crit["price_min"] == 968000 and crit["price_max"] == 1452000
    assert crit["sold_within_months"] == 12
    # Never fabricated: comps stay empty, values come from source records only.
    assert data["comps"] == []
    assert "10312" in data["links"]["zillow"]
    assert "10312" in data["links"]["redfin"]
    assert data["value_refs"][0]["value"] == 1210000
    assert data["value_refs"][0]["source"].startswith("lead payload")


def test_comps_brief_without_property(client, make_lead):
    lead = make_lead(address=None)
    data = client.get(f"/api/leads/{lead.id}/comps").json()
    assert data["subject"] is None
    assert data["reason"]


def test_comps_brief_is_pure_when_called_directly(make_lead):
    lead = make_lead()
    data = comps_brief(lead)
    assert data["subject"]["address"].startswith("412 Sycamore St")
    assert data["links"]
    assert data["comps"] == []


def test_repair_mojibake_fixes_latin1_decoded_utf8():
    assert _repair_mojibake("What’s up") == "What’s up"  # clean -> untouched
    broken = "Whatâ\x80\x99s"  # the bytes of ’ decoded as latin-1
    assert _repair_mojibake(broken) == "What’s"
    # double/triple encoded rows from storage -> multi-pass repairs them
    double = broken.encode("utf-8").decode("latin-1")
    assert _repair_mojibake(double) == "What’s"
    triple = double.encode("utf-8").decode("latin-1")
    assert _repair_mojibake(triple) == "What’s"
    # C1 bytes with no valid utf-8 interpretation pass through unchanged
    assert _repair_mojibake("\x80\x99") == "\x80\x99"
    assert _repair_mojibake("") == ""
