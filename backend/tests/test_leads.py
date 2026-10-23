"""Health, lead listing/filtering/editing/export and reference data."""
from __future__ import annotations


def test_health_never_contacts_sellers(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "never contacts sellers" in body["note"]


def test_leads_list_search_and_filters(client, make_lead):
    make_lead(name="Dana Seller", source="Facebook", stage="new")
    make_lead(name="Marcus Reed", source="Craigslist", stage="qualified", contact_status="qualified")

    response = client.get("/api/leads")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert {i["full_name"] for i in payload["items"]} == {"Dana Seller", "Marcus Reed"}

    search = client.get("/api/leads", params={"q": "Marcus"}).json()
    assert search["total"] == 1

    staged = client.get("/api/leads", params={"stage": ["qualified"]}).json()
    assert staged["total"] == 1
    assert staged["items"][0]["pipeline_stage"] == "qualified"

    by_source = client.get("/api/leads", params={"source": ["Facebook"]}).json()
    assert by_source["total"] == 1

    never = client.get("/api/leads", params={"never_contacted": True}).json()
    assert never["total"] == 1
    assert never["items"][0]["full_name"] == "Dana Seller"


def test_lead_detail_activity_and_stage_update(client, make_lead, db):
    lead = make_lead(name="Priya Nair", notes="Inherited property, wants a fast close.")

    detail = client.get(f"/api/leads/{lead.id}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["full_name"] == "Priya Nair"
    assert data["missing_fields"], "missing fields should be reported"
    assert data["has_critical_missing"] in {True, False}
    assert data["timeline"] == []

    activity = client.post(
        f"/api/leads/{lead.id}/activities",
        json={"activity_type": "call", "direction": "outbound", "summary": "Spoke with seller", "outcome": "connected"},
    )
    assert activity.status_code == 200, activity.text

    bad_outcome = client.post(
        f"/api/leads/{lead.id}/activities",
        json={"summary": "Made up outcome", "outcome": "sold_the_house"},
    )
    assert bad_outcome.status_code == 400
    assert "Unknown outcome" in bad_outcome.json()["detail"]

    updated = client.patch(
        f"/api/leads/{lead.id}",
        json={"pipeline_stage": "contacted", "contact_status": "spoke_with_seller"},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["pipeline_stage"] == "contacted"

    detail = client.get(f"/api/leads/{lead.id}").json()
    assert len(detail["timeline"]) >= 1
    assert detail["last_contact_at"], "contact should roll forward the lead"


def test_lead_update_writes_audit_entry(client, make_lead):
    lead = make_lead(name="Audit Target")
    client.patch(f"/api/leads/{lead.id}", json={"pipeline_stage": "nurture"})

    audit = client.get("/api/audit", params={"action": "lead.update"}).json()
    assert audit["total"] >= 1
    entry = audit["items"][0]
    assert entry["entity_id"] == lead.id
    assert entry["detail"]["pipeline_stage"]["to"] == "nurture"


def test_lead_export_csv_is_formula_safe(client, make_lead):
    make_lead(name="=cmd|'/C calc'!A1", stage="new")

    response = client.get("/api/leads/export")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    body = response.text
    assert "'=cmd" in body, "formula-prefixed cells must be neutralised"
    for line in body.splitlines()[1:]:
        for cell in line.split(","):
            stripped = cell.strip().strip('"')
            assert not stripped.startswith(("=", "+", "@")), f"unescaped formula cell: {stripped}"


def test_lead_reference_data_exposes_stages(client):
    ref = client.get("/api/leads/meta/reference").json()
    stage_keys = [s["key"] if isinstance(s, dict) else s for s in ref["stages"]]
    assert "new" in stage_keys
    assert "under_contract" in stage_keys
