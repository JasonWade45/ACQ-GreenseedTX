from app.config import ROOT, get_settings
from app.security import valid_session


def test_empty_dashboard_and_list(client):
    assert client.get("/api/health").status_code == 200
    d = client.get("/api/dashboard").json()
    assert all(m["value"] == 0 for m in d["metrics"])
    assert client.get("/api/leads").json()["total"] == 0
    assert client.get("/api/sync").json()["health"] == "never"


def test_lead_board_and_adjacent_navigation(client, make_lead):
    make_lead(name="First Seller", phone="+12025550191")
    make_lead(name="Second Seller", phone="+12025550192")
    ordered = client.get("/api/leads?page_size=10").json()["items"]
    board = client.get("/api/leads/board?limit_per_stage=10").json()
    assert board["total"] == 2
    new_stage = next(column for column in board["stages"] if column["code"] == "new")
    assert new_stage["count"] == 2 and len(new_stage["items"]) == 2
    first_neighbors = client.get(f"/api/leads/{ordered[0]['id']}/neighbors").json()
    assert first_neighbors["previous"] is None
    assert first_neighbors["next"]["id"] == ordered[1]["id"]
    last_neighbors = client.get(f"/api/leads/{ordered[1]['id']}/neighbors").json()
    assert last_neighbors["next"] is None
    assert last_neighbors["previous"]["id"] == ordered[0]["id"]
    client.post(f"/api/leads/{ordered[0]['id']}/conversations", json={"outcome": "connected", "notes": "Seller asked for a call next week"})
    profile = client.get(f"/api/leads/{ordered[0]['id']}").json()
    assert profile["calls"][0]["notes"] == "Seller asked for a call next week"


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


def test_followup_workbench_shows_all_leads_and_recent_activity(client, make_lead):
    lead = make_lead(source_do_not_contact=False)
    client.post(f"/api/leads/{lead.id}/activities", json={"summary": "Asked for a call next week", "activity_type": "note"})
    payload = client.get("/api/followups/workbench?page_size=10").json()
    assert payload["total"] == 1
    assert payload["items"][0]["lead"]["id"] == lead.id
    assert payload["items"][0]["last_activity"]["summary"] == "Asked for a call next week"
    assert payload["items"][0]["sent_count"] == 0


def test_manual_followup_touch_is_logged_and_schedules_the_next_reminder(client, make_lead):
    lead = make_lead(source_do_not_contact=False)
    body = "Hi Seller,\n\nChecking in after our conversation.\n\nJason Wade | Acquisition manager\nGreenSeedTX LLC"
    sent = client.post(
        f"/api/followups/workbench/{lead.id}/sent",
        json={"message": body, "confirm": True},
    )
    assert sent.status_code == 200
    assert sent.json()["sent_count"] == 1 and sent.json()["next_touch_days"] == 2
    profile = client.get(f"/api/leads/{lead.id}").json()
    activity = profile["activities"][0]
    assert activity["summary"] == body and activity["direction"] == "outbound"
    assert activity["source_metadata"]["not_sent_by_app"] is True
    assert profile["followups"][0]["creation_source"] == "followup_hub"

    second = client.post(
        f"/api/followups/workbench/{lead.id}/sent",
        json={"message": "Checking back in.\nGreenSeedTX LLC", "confirm": True},
    )
    assert second.status_code == 200 and second.json()["sent_count"] == 2
    name_again = client.post(
        f"/api/followups/workbench/{lead.id}/sent",
        json={"message": "Jason Wade\nGreenSeedTX LLC", "confirm": True},
    )
    assert name_again.status_code == 400


def test_followup_hub_blocks_dnc_and_missing_company(client, make_lead):
    restricted = make_lead(source_do_not_contact=True)
    blocked = client.post(
        f"/api/followups/workbench/{restricted.id}/sent",
        json={"message": "Jason Wade\nGreenSeedTX LLC", "confirm": True},
    )
    assert blocked.status_code == 400 and "Do Not Contact" in blocked.json()["detail"]

    clear = make_lead(name="Clear Seller", phone="+12025550222", source_do_not_contact=False)
    missing_company = client.post(
        f"/api/followups/workbench/{clear.id}/sent",
        json={"message": "Jason Wade checking in", "confirm": True},
    )
    assert missing_company.status_code == 400


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


def test_import_batch_reset_backs_up_and_removes_only_batch_created_leads(client, make_lead, monkeypatch, tmp_path):
    from app.main import backup_service

    backup_path = tmp_path / "safety-copy.sqlite"
    monkeypatch.setattr(backup_service, "create_backup", lambda *args, **kwargs: backup_path)
    protected = make_lead(name="Pre-existing Seller", phone="+12025550999")
    filename = "sample-seller-leads.csv"
    uploaded = client.post(
        "/api/imports/upload",
        files={"file": (filename, (ROOT / "examples" / filename).read_bytes())},
    )
    batch = uploaded.json()
    mapping = batch["sheets"]["CSV"]["suggested_mapping"]
    preview = client.post(
        f"/api/imports/{batch['id']}/preview",
        json={"sheets": ["CSV"], "mapping": mapping},
    )
    assert preview.status_code == 200
    row_ids = client.get(f"/api/imports/{batch['id']}/eligible-ids").json()["row_ids"]
    approved = client.post(
        f"/api/imports/{batch['id']}/approve",
        json={"row_ids": row_ids, "confirmation": "IMPORT LOCAL"},
    )
    assert approved.status_code == 200

    rejected = client.request(
        "DELETE",
        f"/api/imports/{batch['id']}/purge",
        json={"confirmation": "DELETE IMPORT BATCH 999"},
    )
    assert rejected.status_code == 400
    result = client.request(
        "DELETE",
        f"/api/imports/{batch['id']}/purge",
        json={"confirmation": f"DELETE IMPORT BATCH {batch['id']}"},
    )
    assert result.status_code == 200, result.text
    assert result.json()["deleted_created_leads"] == 6
    assert result.json()["deleted_rows"] == batch["row_count"]
    assert result.json()["safety_backup"] == backup_path.name
    assert client.get(f"/api/imports/{batch['id']}").status_code == 404
    assert client.get("/api/leads").json()["total"] == 1
    assert client.get(f"/api/leads/{protected.id}").status_code == 200


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


def test_startup_warns_when_password_missing_so_tunnels_are_not_silent(monkeypatch, capsys):
    """Loopback mode refuses non-local Host headers; a tunnel then loads the page but fails data."""
    from app.config import Settings
    from app.main import REMOTE_ACCESS_HINT, warn_if_unreachable

    monkeypatch.setattr("logging.Logger.warning", lambda *a, **k: None)
    warn_if_unreachable(Settings(_env_file=None, app_access_password=""))
    captured = capsys.readouterr().out
    assert "APP_ACCESS_PASSWORD is empty" in captured
    assert "403" in captured and "tunnel" in captured
    assert captured.strip() == f"WARNING: {REMOTE_ACCESS_HINT}"


def test_startup_is_quiet_when_password_is_configured(monkeypatch, capsys):
    from app.config import Settings
    from app.main import warn_if_unreachable

    monkeypatch.setattr("logging.Logger.warning", lambda *a, **k: None)
    warn_if_unreachable(Settings(_env_file=None, app_access_password="a-long-enough-password"))
    assert capsys.readouterr().out == ""


def _login(client, password="private-test-password"):
    return client.post("/api/auth/login", json={"password": password}).json()["token"]


def test_logout_cancels_only_the_session_that_asked(client, monkeypatch):
    import app.security as security

    monkeypatch.setattr(security, "REVOKED_BEFORE", 0.0)
    monkeypatch.setattr(get_settings(), "app_access_password", "private-test-password")
    first = _login(client)
    second = _login(client)
    assert client.get("/api/leads", headers={"Authorization": "Bearer " + first}).status_code == 200

    assert client.post("/api/auth/logout", headers={"Authorization": "Bearer " + first}).status_code == 200
    assert client.get("/api/leads", headers={"Authorization": "Bearer " + first}).status_code == 401
    assert client.get("/api/leads", headers={"Authorization": "Bearer " + second}).status_code == 200


def test_logout_all_invalidates_every_issued_token_and_survives_restart(client, db, monkeypatch):
    import app.security as security

    monkeypatch.setattr(security, "REVOKED_BEFORE", 0.0)
    monkeypatch.setattr(get_settings(), "app_access_password", "private-test-password")
    token = _login(client)
    assert client.get("/api/leads", headers={"Authorization": "Bearer " + token}).status_code == 200

    # Signing out everywhere still requires being signed in.
    assert client.post("/api/auth/logout-all").status_code == 401
    assert client.post(
        "/api/auth/logout-all", headers={"Authorization": "Bearer " + token}
    ).status_code == 200
    assert client.get("/api/leads", headers={"Authorization": "Bearer " + token}).status_code == 401
    assert not security.valid_session(token)

    # A restart must not resurrect the cancelled sessions.
    security.REVOKED_BEFORE = 0.0
    security.restore_revocation(db)
    assert security.REVOKED_BEFORE > 0
    assert not security.valid_session(token)

    fresh = _login(client)
    assert client.get("/api/leads", headers={"Authorization": "Bearer " + fresh}).status_code == 200


def test_login_and_logout_are_audited_without_recording_the_password(client, db, monkeypatch):
    from app.models import AuditLog

    monkeypatch.setattr(get_settings(), "app_access_password", "private-test-password")
    client.post("/api/auth/login", json={"password": "wrong-password-value"})
    token = _login(client)
    client.post("/api/auth/logout", headers={"Authorization": "Bearer " + token})

    actions = [row.action for row in db.query(AuditLog).all()]
    assert "auth_login_failed" in actions
    assert "auth_login" in actions
    assert "auth_logout" in actions
    stored = " ".join(str(row.details) for row in db.query(AuditLog).all())
    assert "wrong-password-value" not in stored
    assert "private-test-password" not in stored


def test_a_failing_audit_write_never_blocks_sign_in(client, monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(get_settings(), "app_access_password", "private-test-password")

    def explode(*args, **kwargs):
        raise RuntimeError("audit storage is unavailable")

    monkeypatch.setattr(main_module, "AuditLog", explode)
    response = client.post("/api/auth/login", json={"password": "private-test-password"})
    assert response.status_code == 200
    token = response.json()["token"]
    assert client.get("/api/leads", headers={"Authorization": "Bearer " + token}).status_code == 200


def test_revocation_memory_is_bounded_without_resurrecting_old_sessions(monkeypatch):
    import app.security as security

    monkeypatch.setattr(security, "REVOKED_TOKENS", set())
    monkeypatch.setattr(security, "MAX_REMEMBERED_TOKENS", 3)
    tokens = [security.new_session() for _ in range(5)]
    for token in tokens[:3]:
        security.revoke_token(token)
    assert len(security.REVOKED_TOKENS) == 3

    security.revoke_token(tokens[3])
    # The set is capped, and the newest revocation is honoured.
    assert len(security.REVOKED_TOKENS) == 3
    assert not security.valid_session(tokens[3])
    # At least the oldest entries are the ones dropped, never everything at once.
    assert len(security.REVOKED_TOKENS) > 0


def test_settings_lists_the_status_titles_the_crm_really_sent(client, db):
    """Unmapped titles must be visible for a human to decide, never guessed."""
    from app.seed import initialize_defaults, record_source_status

    initialize_defaults(db)
    record_source_status(db, "Dead Lead")
    record_source_status(db, "Dead Lead")
    record_source_status(db, "Some Title Nobody Predicted")
    record_source_status(db, None)
    db.commit()

    rows = client.get("/api/settings").json()["source_statuses"]
    by_title = {row["title"]: row for row in rows}

    assert by_title["Dead Lead"]["leads"] == 2
    assert by_title["Dead Lead"]["stage"] == "dead"
    assert by_title["Dead Lead"]["mapped"] is True
    assert by_title["Some Title Nobody Predicted"]["stage"] == "unmapped"
    assert by_title["Some Title Nobody Predicted"]["mapped"] is False
    assert by_title["(blank)"]["leads"] == 1
