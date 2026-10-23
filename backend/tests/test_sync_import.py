"""REsimpli synchronisation (mock client) and legacy CSV/XLSX import."""
from __future__ import annotations

from pathlib import Path

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "sample_seller_leads.csv"


def test_sync_run_mock_creates_leads(client):
    result = client.post("/api/sync/run").json()
    assert result["result"] in {"success", "partial"}
    assert result["created_count"] > 0
    assert result["records_fetched"] >= result["created_count"]

    status = client.get("/api/sync/status").json()
    assert status["mock_mode"] is True
    assert status["api_key_configured"] is False
    assert status["health"] == "healthy"
    assert status["leads_in_database"] >= result["created_count"]

    runs = client.get("/api/sync/runs").json()
    assert len(runs["items"]) >= 1
    assert runs["items"][0]["result"] == "success"


def test_sync_is_read_only_and_deterministic(client):
    first = client.post("/api/sync/run").json()
    second = client.post("/api/sync/run").json()
    assert second["created_count"] == 0, "second run must not duplicate leads"
    assert second["failed_count"] == 0

    status = client.get("/api/sync/status").json()
    assert status["leads_in_database"] == first["created_count"]


def test_sync_test_connection_mock_mode(client):
    body = client.post("/api/sync/test-connection").json()
    assert body["ok"] is True
    assert body["mock"] is True


def test_scheduler_disable(client):
    response = client.post("/api/sync/scheduler", json={"enabled": False, "interval_minutes": 45})
    assert response.status_code == 200
    state = client.get("/api/sync/status").json()["scheduler"]
    assert state["enabled"] is False
    assert state["interval_minutes"] == 45


def test_import_upload_inspect_preview_commit(client):
    with SAMPLE.open("rb") as handle:
        uploaded = client.post(
            "/api/imports/upload",
            files={"file": ("sample_seller_leads.csv", handle, "text/csv")},
        )
    assert uploaded.status_code == 200, uploaded.text
    inspection = uploaded.json()
    assert inspection["error"] is None
    assert inspection["row_count"] >= 10
    assert "Phone Number" in inspection["headers"]
    mapping = inspection["auto_mapping"]
    assert mapping["first_name"] or mapping["full_name"] or mapping["phone"]
    assert mapping["phone"] == "Phone Number"

    preview = client.post(
        "/api/imports/preview",
        params={"file": inspection["stored_path"]},
        json={"mapping": {k: v for k, v in mapping.items() if v}},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    batch = body["batch"]
    batch_id = batch["id"]
    assert batch["status"] == "preview"
    assert body["counts"]["rejected"] == 0 or body["counts"]["new"] > 0
    assert body["counts"]["new"] >= 1

    committed = client.post(
        f"/api/imports/{batch_id}/commit",
        json={"skip_duplicates": True},
    )
    assert committed.status_code == 200, committed.text
    summary = committed.json()
    assert summary["imported"] >= 1

    leads = client.get("/api/leads", params={"origin": "import"}).json()
    assert leads["total"] >= 1

    rejected = client.get(f"/api/imports/{batch_id}/rejected.csv")
    assert rejected.status_code == 200
    template = client.get(f"/api/imports/{batch_id}/resimpli-template.csv")
    assert template.status_code == 200
    assert "firstName" in template.text.splitlines()[0]


def test_import_rejects_unsupported_file(client):
    response = client.post(
        "/api/imports/upload",
        files={"file": ("evil.exe", b"MZ...", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert ".csv" in response.json()["detail"]


def test_import_commit_twice_is_rejected(client):
    with SAMPLE.open("rb") as handle:
        inspection = client.post(
            "/api/imports/upload",
            files={"file": ("sample_seller_leads.csv", handle, "text/csv")},
        ).json()
    preview = client.post(
        "/api/imports/preview",
        params={"file": inspection["stored_path"]},
        json={"mapping": {k: v for k, v in inspection["auto_mapping"].items() if v}},
    ).json()
    batch_id = preview["batch"]["id"]
    assert client.post(f"/api/imports/{batch_id}/commit", json={}).status_code == 200
    again = client.post(f"/api/imports/{batch_id}/commit", json={})
    assert again.status_code == 400
    assert "already been committed" in again.json()["detail"]


def test_note_collections_never_become_plain_text(db, make_lead):
    from app.services.sync_service import _looks_stringified_collection, upsert_lead_from_api

    assert _looks_stringified_collection("[{'text': 'Seller wants a fast close.', 'createdAt': '2026-10-01T12:00:00Z'}]")
    assert _looks_stringified_collection('{"text": "roof needs work"}')
    assert not _looks_stringified_collection("Inherited the house from her father; wants a quick cash sale.")

    legacy = make_lead(
        name="Legacy Notes",
        external_id="ext-legacy-notes",
        notes="[{'text': 'Seller wants a fast close.', 'createdAt': '2026-10-01T12:00:00Z'}]",
    )
    upsert_lead_from_api(db, {"external_id": "ext-legacy-notes", "notes": None}, {})
    db.refresh(legacy)
    assert legacy.notes is None, "stringified note collections are cleared (they live as activities)"

    plain = make_lead(name="Plain Notes", external_id="ext-plain-notes", notes="Local note.")
    upsert_lead_from_api(db, {"external_id": "ext-plain-notes", "notes": "Seller wants a cash close."}, {})
    db.refresh(plain)
    assert plain.notes == "Local note.", "sync must never clobber a locally edited note"

    fresh = make_lead(name="Empty Notes", external_id="ext-empty-notes", notes=None)
    upsert_lead_from_api(db, {"external_id": "ext-empty-notes", "notes": "Carried over from REsimpli."}, {})
    db.refresh(fresh)
    assert fresh.notes == "Carried over from REsimpli."


def test_sync_composes_full_name_from_parts(db, make_lead):
    from app.services.sync_service import upsert_lead_from_api

    lead = make_lead(name="Parts Only", external_id="ext-parts", email=None, address=None)
    lead.full_name = None
    db.flush()

    upsert_lead_from_api(
        db,
        {"external_id": "ext-parts", "first_name": "Parts", "last_name": "Only", "full_name": None},
        {},
    )
    db.refresh(lead)
    assert lead.full_name == "Parts Only"
