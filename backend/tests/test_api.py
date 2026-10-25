from app.config import ROOT, get_settings
from app.security import valid_session


def test_empty_dashboard_and_list(client):
    assert client.get("/api/health").status_code == 200
    d = client.get("/api/dashboard").json()
    assert all(m["value"] == 0 for m in d["metrics"])
    assert client.get("/api/leads").json()["total"] == 0
    assert client.get("/api/sync").json()["health"] == "never"


def test_search_filters_pagination_and_profile(client, make_lead):
    lead = make_lead(source_status="Qualified")
    make_lead(name="Other Seller", phone="+12025550198")
    assert client.get("/api/leads?search=Test").json()["total"] == 1
    assert client.get("/api/leads?stage=qualified").json()["total"] == 1
    assert len(client.get("/api/leads?page_size=1&page=2").json()["items"]) == 1
    profile = client.get(f"/api/leads/{lead.id}").json()
    assert profile["external_url"] is None and profile["source_notice"]
    assert client.get("/api/leads/99999").status_code == 404
    assert client.get("/api/leads?sort=not_real").status_code == 400


def test_followup_lifecycle_through_api(client, make_lead):
    lead = make_lead()
    response = client.post(
        "/api/followups", json={"lead_id": lead.id, "reason": "Review source", "due_at": "2027-01-01T15:00:00Z"}
    )
    assert response.status_code == 200
    id = response.json()["id"]
    assert client.post(f"/api/followups/{id}/action", json={"action": "complete", "confirm": True}).status_code == 400
    completed = client.post(
        f"/api/followups/{id}/action", json={"action": "complete", "confirm": True, "outcome": "No Answer"}
    )
    assert completed.status_code == 200
    profile = client.get(f"/api/leads/{lead.id}").json()
    assert profile["contact_status"] == "attempted" and profile["last_contact_at"] is None
    assert len(profile["activities"]) == 1


def test_restrictions_cannot_be_silently_overridden(client, make_lead):
    lead = make_lead(source_do_not_contact=True)
    blocked = client.post(
        f"/api/leads/{lead.id}/restriction", json={"restricted": False, "evidence": "Test review", "confirm": True}
    )
    assert blocked.status_code == 400
    assert client.post(f"/api/leads/{lead.id}/draft", json={}).status_code == 400
    profile = client.get(f"/api/leads/{lead.id}").json()
    assert profile["draft"] is None and profile["do_not_contact"]


def test_draft_review_and_edit_only(client, make_lead):
    lead = make_lead(source_do_not_contact=False, contact_outcome="Callback Requested")
    d = client.post(f"/api/leads/{lead.id}/draft", json={})
    assert d.status_code == 200
    updated = client.patch(f"/api/drafts/{d.json()['id']}", json={"body": "Human-edited review-only draft."})
    assert updated.json()["body"] == "Human-edited review-only draft."
    assert client.post("/api/sms/send", json={}).status_code in {404, 405}
    assert client.post("/api/email/send", json={}).status_code in {404, 405}


def test_local_activities_and_stage_do_not_write_crm(client, make_lead):
    lead = make_lead(external_id="existing-crm-id", source_status="New")
    note = client.post(
        f"/api/leads/{lead.id}/activities",
        json={"summary": "Internal note only", "activity_type": "note", "outcome": "Connected"},
    )
    assert note.status_code == 200 and note.json()["source"] == "local"
    assert client.get(f"/api/leads/{lead.id}").json()["contact_status"] == "unknown"
    stage = client.patch(f"/api/leads/{lead.id}/stage", json={"stage_code": "qualified", "confirm": True})
    assert stage.status_code == 200 and stage.json()["source_status"] == "New"
    assert stage.json()["local_stage_override"]


def test_naive_followup_timestamps_rejected(client, make_lead):
    lead = make_lead()
    assert (
        client.post(
            "/api/followups", json={"lead_id": lead.id, "reason": "Test", "due_at": "2026-10-21T15:00:00"}
        ).status_code
        == 400
    )


def test_csv_and_xlsx_import_preview_and_approval(client):
    for filename in ["sample-seller-leads.csv", "sample-seller-leads.xlsx"]:
        path = ROOT / "examples" / filename
        uploaded = client.post("/api/imports/upload", files={"file": (filename, path.read_bytes())})
        assert uploaded.status_code == 200
        batch = uploaded.json()
        if filename.endswith("xlsx"):
            assert len(batch["sheets"]) == 2
        mapping = next(iter(batch["sheets"].values()))["suggested_mapping"]
        preview = client.post(
            f"/api/imports/{batch['id']}/preview", json={"sheets": list(batch["sheets"]), "mapping": mapping}
        )
        assert preview.status_code == 200
        assert preview.json()["counts"]["invalid"] == 1
        ids = client.get(f"/api/imports/{batch['id']}/eligible-ids").json()["row_ids"]
        # CSV pass imports 6 new rows. XLSX repeat is reviewed as duplicates, never silently merged.
        if ids:
            approved = client.post(
                f"/api/imports/{batch['id']}/approve", json={"row_ids": ids, "confirmation": "IMPORT LOCAL"}
            )
            assert approved.status_code == 200
            assert approved.json()["counts"]["imported"] == 6
        assert client.get(f"/api/imports/{batch['id']}/export?kind=rejected").status_code == 200
        assert client.post(f"/api/imports/{batch['id']}/external").status_code == 409


def test_import_rejected_export_is_formula_safe(client):
    content = b'Name,Phone,Notes\n,invalid,=WEBSERVICE("x")\n'
    b = client.post("/api/imports/upload", files={"file": ("bad.csv", content)}).json()
    client.post(
        f"/api/imports/{b['id']}/preview",
        json={"sheets": ["CSV"], "mapping": {"Name": "full_name", "Phone": "primary_phone", "Notes": "notes"}},
    )
    export = client.get(f"/api/imports/{b['id']}/export?kind=rejected")
    assert export.status_code == 200 and "'=WEBSERVICE" in export.text


def test_appointments_and_result_preserve_source(client, make_lead):
    lead = make_lead()
    a = client.post(
        "/api/appointments",
        json={"lead_id": lead.id, "starts_at": "2027-01-01T15:00:00Z", "notes": "Confirmed outside app"},
    ).json()
    response = client.post(f"/api/appointments/{a['id']}/result", json={"result": "kept", "confirm": True})
    assert (
        response.status_code == 200
        and response.json()["status"] == "scheduled"
        and response.json()["local_result"] == "kept"
    )
    assert client.get("/api/appointments").json()[0]["seller"] == lead.full_name


def test_pipeline_configuration_and_settings(client):
    added = client.post("/api/pipeline/stages", json={"code": "due_diligence", "label": "Due Diligence"})
    assert added.status_code == 200
    assert client.patch("/api/pipeline/stages/due_diligence", json={"label": "Property Review"}).status_code == 200
    assert client.post("/api/pipeline/stages", json={"code": "due_diligence", "label": "Duplicate"}).status_code == 400
    assert client.patch("/api/settings", json={"stage_mapping": {"custom": "not_a_stage"}}).status_code == 400
    assert client.patch("/api/settings", json={"stage_mapping": {"custom": "due_diligence"}}).status_code == 200
    assert client.patch("/api/sync/scheduler", json={"enabled": True, "interval_minutes": 30}).status_code == 400


def test_exports_and_reports(client, make_lead):
    make_lead(name="=DANGEROUS FORMULA")
    response = client.get("/api/leads/export")
    assert response.status_code == 200 and "'=DANGEROUS FORMULA" in response.text
    assert client.get("/api/reports/export").status_code == 200
    assert client.get("/api/reports").json()["total"] == 1


def test_secrets_are_not_exposed_by_settings_or_validation(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "resimpli_api_key", "TOP-SECRET-NOT-FOR-FRONTEND")
    assert "TOP-SECRET" not in client.get("/api/settings").text
    long = "PRIVATE-PASSWORD-" * 100
    response = client.post("/api/auth/login", json={"password": long})
    assert response.status_code == 422 and "PRIVATE-PASSWORD-" not in response.text


def test_authentication_and_same_origin_mutation_protection(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_access_password", "private-test-password")
    assert client.get("/api/leads").status_code == 401
    assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    token = client.post("/api/auth/login", json={"password": "private-test-password"}).json()["token"]
    assert valid_session(token)
    assert client.get("/api/leads", headers={"Authorization": "Bearer " + token}).status_code == 200
    assert (
        client.post(
            "/api/auth/login", json={"password": "private-test-password"}, headers={"Origin": "https://evil.test"}
        ).status_code
        == 403
    )
    assert not valid_session(token + "tampered")


def test_loopback_mode_rejects_dns_rebinding_host(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setattr(get_settings(), "app_access_password", "")
    c = TestClient(app, base_url="http://untrusted.example", client=("127.0.0.1", 50400))
    response = c.get("/api/health")
    assert response.status_code == 403 and "Host" in response.text
    c.close()


def test_loopback_mode_accepts_local_hostnames(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setattr(get_settings(), "app_access_password", "")
    c = TestClient(app, base_url="http://localhost:8010", client=("127.0.0.1", 50400))
    assert c.get("/api/health").status_code == 200
    c.close()


def test_test_transport_exception_cannot_be_spoofed_for_real_host_scope(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setattr(get_settings(), "app_access_password", "")
    c = TestClient(app, base_url="http://127.0.0.1:8010", client=("testclient", 50400))
    assert c.get("/api/health").status_code == 403
    c.close()
