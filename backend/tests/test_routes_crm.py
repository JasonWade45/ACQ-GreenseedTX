"""The new routes over TestClient: every one of them, with both integrations mocked.

The reader is a fixture-mode ResimpliClient over an in-memory transport; the writer is a
live-mode ResimpliWriter over the same kind of transport. No request can leave the
process, and no real key exists in these tests.
"""

import json

import httpx
import pytest
from sqlalchemy import select

from app import routes_crm
from app.config import Settings
from app.models import CrmNoteOutbox, CrmPush, LeadChecklistItem, SyncConflict
from app.services.resimpli import ResimpliClient
from app.services.resimpli_write import ResimpliWriter

DEFAULTS = {
    "marketing_campign_id": "5f1d7c9a1b2c3d4e5f607182",
    "market_id": "5f1d7c9a1b2c3d4e5f607183",
    "pipeline_id": "5f1d7c9a1b2c3d4e5f607184",
    "main_status_id": "5f1d7c9a1b2c3d4e5f607185",
}


def settings_for(**extra):
    values = {
        "resimpli_mode": "live",
        "resimpli_api_key": "not-a-real-key-000000000000",
        "resimpli_adapter_path": "",
        "crm_writes_enabled": True,
        "sync_requests_per_minute": 100,
        "grok_enabled": False,
        "grok_api_key": "",
        **extra,
    }
    return Settings(_env_file=None, **values)


class Wiring:
    """Swap the clients the routes build for ones that answer from memory."""

    def __init__(self, monkeypatch, *, settings=None, existing=(), write_responses=None):
        self.settings = settings or settings_for()
        self.existing = list(existing)
        self.write_responses = list(write_responses or [])
        self.searches = []
        self.writes = []
        monkeypatch.setattr(routes_crm, "_settings", lambda: self.settings)
        monkeypatch.setattr(routes_crm, "ResimpliClient", self._reader)
        monkeypatch.setattr(routes_crm, "ResimpliWriter", self._writer)

    def _read(self, request):
        body = json.loads(request.content or "{}")
        self.searches.append(body)
        query = (body.get("searchStr") or "").lower()
        records = [
            record
            for record in self.existing
            if query in (record.get("phone", "") or "").lower() or query in (record.get("address", "") or "").lower()
        ]
        return httpx.Response(200, json={"ok": True, "data": {"records": records, "total": len(records)}})

    def _write(self, request):
        self.writes.append(json.loads(request.content or "{}"))
        if self.write_responses:
            return self.write_responses.pop(0)
        return httpx.Response(200, json={"ok": True, "data": {"_id": "crm-lead-1"}})

    def _reader(self, _settings):
        return ResimpliClient(
            Settings(_env_file=None, resimpli_mode="fixture"),
            transport=httpx.MockTransport(self._read),
            sleeper=lambda _seconds: None,
        )

    def _writer(self, _settings):
        return ResimpliWriter(self.settings, transport=httpx.MockTransport(self._write), sleeper=lambda _s: None)


def configure(client):
    response = client.patch("/api/integrations/resimpli/push/settings", json=DEFAULTS)
    assert response.status_code == 200, response.text
    return response


# --- settings and queue ------------------------------------------------------------


def test_push_settings_round_trip(client):
    body = client.get("/api/integrations/resimpli/push/settings").json()
    assert body["settings"]["mode"] == "review", "review is the default"
    assert body["confirmation_phrase"] == "PUSH TO CRM"
    assert "Create a lead only" in body["write_scope"]

    saved = client.patch(
        "/api/integrations/resimpli/push/settings",
        json={**DEFAULTS, "mode": "auto", "note_fields": {"equity": False}},
    ).json()
    assert saved["settings"]["mode"] == "auto"
    assert saved["settings"]["marketing_campign_id"] == DEFAULTS["marketing_campign_id"]


def test_an_invalid_mode_is_refused(client):
    assert client.patch("/api/integrations/resimpli/push/settings", json={"mode": "yolo"}).status_code == 422


def test_the_queue_explains_each_lead(client, db, make_lead, monkeypatch):
    Wiring(monkeypatch)
    ready = make_lead("Ready Seller")
    make_lead("No Phone Seller", phone=None)
    configure(client)
    body = client.get("/api/integrations/resimpli/push/queue").json()
    rows = {row["lead_id"]: row for row in body["rows"]}
    assert rows[ready.id]["reason"] is None
    assert body["counts"]["ready"] == 1 and body["counts"]["blocked"] == 1
    assert body["writes_enabled"] is True


# --- preview, push, link -----------------------------------------------------------


def test_a_preview_shows_the_body_and_writes_nothing(client, db, make_lead, monkeypatch):
    Wiring(monkeypatch)
    lead = make_lead("Preview Seller")
    configure(client)
    body = client.post(f"/api/leads/{lead.id}/crm/preview", json={"include_note": True}).json()
    assert body["writes_nothing"] is True
    assert body["body"]["contactDetails"]["phoneNumbers"][0]["phoneNumber"] == "2025550199"
    assert body["note"].startswith("[GreenSeed]")
    assert db.scalars(select(CrmPush)).all() == []
    assert db.scalars(select(CrmNoteOutbox)).all() == [], "a dry run leaves no note either"


def test_a_push_without_the_typed_confirmation_does_not_create_anything(client, db, make_lead, monkeypatch):
    wiring = Wiring(monkeypatch)
    lead = make_lead("Push Seller")
    configure(client)
    body = client.post(f"/api/leads/{lead.id}/crm/push", json={"confirmation": "yes"}).json()
    assert body["state"] == "blocked" and body["reason"] == "confirmation_required"
    assert wiring.writes == []


def test_a_confirmed_push_creates_one_lead(client, db, make_lead, monkeypatch):
    wiring = Wiring(monkeypatch)
    lead = make_lead("Push Seller")
    configure(client)
    body = client.post(f"/api/leads/{lead.id}/crm/push", json={"confirmation": "PUSH TO CRM"}).json()
    assert body["state"] == "pushed" and body["resimpli_lead_id"] == "crm-lead-1"
    assert len(wiring.writes) == 1
    assert db.scalar(select(CrmPush).where(CrmPush.lead_id == lead.id)).state == "pushed"
    assert db.scalar(select(CrmNoteOutbox).where(CrmNoteOutbox.lead_id == lead.id)).state == "delivered"


def test_a_duplicate_in_the_crm_blocks_the_push_over_http(client, db, make_lead, monkeypatch):
    wiring = Wiring(monkeypatch, existing=[{"id": "crm-old", "name": "Same", "phone": "2025550199"}])
    lead = make_lead("Push Seller")
    configure(client)
    body = client.post(f"/api/leads/{lead.id}/crm/push", json={"confirmation": "PUSH TO CRM"}).json()
    assert body["reason"] == "exists_in_crm"
    assert wiring.writes == []
    assert db.scalar(select(SyncConflict).where(SyncConflict.lead_id == lead.id)).crm_value == "crm-old"


def test_linking_the_existing_lead_clears_the_conflict(client, db, make_lead, monkeypatch):
    Wiring(monkeypatch, existing=[{"id": "crm-old", "name": "Same", "phone": "2025550199"}])
    lead = make_lead("Push Seller")
    configure(client)
    client.post(f"/api/leads/{lead.id}/crm/push", json={"confirmation": "PUSH TO CRM"})
    body = client.post(f"/api/leads/{lead.id}/crm/link", json={"resimpli_lead_id": "crm-old"}).json()
    assert body["linked"] is True
    assert db.scalar(select(CrmPush).where(CrmPush.lead_id == lead.id)).state == "pushed"


def test_writes_switched_off_is_a_clear_refusal(client, make_lead, monkeypatch):
    Wiring(monkeypatch, settings=settings_for(crm_writes_enabled=False))
    lead = make_lead("Push Seller")
    response = client.post(f"/api/leads/{lead.id}/crm/push", json={"confirmation": "PUSH TO CRM"})
    assert response.status_code == 400
    assert "switched off" in response.json()["detail"]


def test_a_batch_pushes_the_selection_and_reports_each_lead(client, db, make_lead, monkeypatch):
    wiring = Wiring(
        monkeypatch,
        write_responses=[
            httpx.Response(200, json={"ok": True, "data": {"_id": "crm-1"}}),
            httpx.Response(400, json={"ok": False, "message": "marketId invalid"}),
        ],
    )
    first, second = make_lead("One"), make_lead("Two")
    configure(client)
    body = client.post(
        "/api/integrations/resimpli/push/batch",
        json={"lead_ids": [first.id, second.id], "confirmation": "PUSH TO CRM"},
    ).json()
    assert body["pushed"] == 1 and body["failed"] == 1
    assert len(wiring.writes) == 2


def test_the_account_lists_are_read_only(client, monkeypatch):
    Wiring(monkeypatch)
    body = client.get("/api/integrations/resimpli/push/accounts").json()
    assert body["read_only"] is True
    assert "marketingCampignId" in body["field_names"]["marketing_campign_id"]


# --- notes -------------------------------------------------------------------------


def test_a_note_for_an_existing_lead_is_shown_with_the_reason(client, db, make_lead):
    lead = make_lead("Note Seller")
    created = client.post(f"/api/leads/{lead.id}/notes").json()
    assert created["state"] == "blocked" and "no note endpoint" in created["reason"]
    listed = client.get(f"/api/leads/{lead.id}/notes").json()
    assert listed["note_endpoint_exists"] is False
    assert listed["notes"][0]["body"].startswith("[GreenSeed]")


# --- checklists --------------------------------------------------------------------


def test_checklist_routes_read_edit_and_tick(client, db, make_lead):
    lead = make_lead("Checklist Seller")
    templates = client.get("/api/checklists/templates").json()["templates"]
    assert {template["key"] for template in templates} == {"lead_manager", "acquisition"}

    progress = client.get(f"/api/leads/{lead.id}/checklists").json()
    assert progress["total"] > 0 and progress["done"] == 0
    item_id = progress["checklists"][0]["items"][0]["id"]
    ticked = client.patch(f"/api/checklists/items/{item_id}", json={"done": True}).json()
    assert ticked["done"] is True
    assert client.get(f"/api/leads/{lead.id}/checklists").json()["done"] == 1

    added = client.post(
        f"/api/leads/{lead.id}/checklists/items", json={"title": "Call the title company", "template_key": "acquisition"}
    ).json()
    assert added["title"] == "Call the title company"

    edited = client.patch("/api/checklists/templates/lead_manager", json={"name": "Lead desk"}).json()
    assert any(template["name"] == "Lead desk" for template in edited["templates"])
    assert db.scalars(select(LeadChecklistItem).where(LeadChecklistItem.lead_id == lead.id)).all()


# --- AI ----------------------------------------------------------------------------


def test_grok_status_reports_the_cap_models_and_cost(client, db):
    body = client.get("/api/integrations/grok/status").json()
    assert body["enabled"] is False
    assert body["models"]["advisor"] == "grok-4.3"
    assert body["monthly_estimate"]["basis"] == "planned_volume"
    assert body["fields"] and body["disclaimer"] and body["compliance"]
    assert body["drafts_are_copy_only"] is True


def test_the_grok_preview_names_the_fields_and_hides_contact_data(client, make_lead, monkeypatch):
    Wiring(monkeypatch, settings=settings_for(grok_enabled=True, grok_api_key="xai-not-a-real-key-000000000000"))
    lead = make_lead("Dana Reyes")
    body = client.post(f"/api/leads/{lead.id}/grok/preview", json={"purpose": "advisor"}).json()
    assert "property_address" in body["fields"]
    assert "2025550199" not in body["prompt"]
    assert body["model"] == "grok-4.3" and body["pii_stripped"] is True


def test_an_ai_call_with_the_integration_off_is_a_clear_400(client, make_lead):
    lead = make_lead("Dana Reyes")
    response = client.post(f"/api/leads/{lead.id}/grok/advice")
    assert response.status_code == 400
    assert "switched off" in response.json()["detail"]


def test_suggestion_decisions_go_through_the_route(client, db, make_lead):
    from app.models import AiChecklistSuggestion

    lead = make_lead("Dana Reyes")
    row = AiChecklistSuggestion(lead_id=lead.id, position=0, title="Ask about the loan balance", detail="")
    db.add(row)
    db.commit()
    body = client.post(f"/api/grok/suggestions/{row.id}", json={"accept": True}).json()
    assert body["status"] == "accepted" and body["checklist_item_id"]
    assert client.get(f"/api/leads/{lead.id}/grok/checklist").json()["accept_each"] is True


# --- cards and dashboard -----------------------------------------------------------


def test_the_lead_cards_return_all_six_blocks(client, make_lead):
    lead = make_lead("Card Seller")
    body = client.get(f"/api/leads/{lead.id}/cards").json()
    assert set(body) >= {
        "next_action",
        "checklist",
        "exit_strategy",
        "last_conversation",
        "crm_sync",
        "notes",
    }
    assert body["next_action"]["title"] == "No next action set"
    assert body["crm_sync"]["state"] == "not_pushed"
    assert body["exit_strategy"] is None


def test_the_dashboard_widgets_add_up(client, db, make_lead):
    make_lead("One")
    make_lead("Two", phone=None)
    configure(client)
    body = client.get("/api/dashboard/integrations").json()
    assert body["push_queue"]["total"] == 2
    assert body["push_queue"]["ready"] == 1
    assert body["checklists_due"]["leads_due"] == 2
    assert body["advisor_ready"] == 0
    assert body["failed_syncs"] == 0


def test_an_unknown_lead_is_a_404(client):
    assert client.get("/api/leads/99999/cards").status_code == 404
    assert client.post("/api/leads/99999/crm/preview", json={}).status_code == 404


@pytest.mark.parametrize("path", ["/api/integrations/grok/status", "/api/checklists/templates"])
def test_new_read_routes_are_behind_the_access_middleware(path, client, monkeypatch):
    """The client fixture bypasses the middleware, so assert the middleware still guards them."""
    from app.main import app as real_app

    middleware = [item.cls.__name__ for item in real_app.user_middleware]
    assert "AccessMiddleware" in middleware


# --- the AI settings actually save --------------------------------------------------


def test_the_ai_settings_save_the_field_list_the_cap_and_the_surface(client, db, monkeypatch):
    """The per-field list, the daily cap and the API surface are real settings, not labels."""
    from app.services import private_settings

    captured = {}
    monkeypatch.setattr(private_settings, "write_private", lambda values: captured.update(values))

    response = client.patch(
        "/api/integrations/grok/settings",
        json={"fields": ["property_address", "priority"], "daily_limit": 5, "api": "chat_completions"},
    )
    assert response.status_code == 200, response.text
    assert captured == {
        "GROK_AI_FIELDS": "property_address,priority",
        "GROK_DAILY_REQUEST_LIMIT": 5,
        "GROK_API": "chat_completions",
    }
    body = response.json()
    assert body["saved"] == ["GROK_AI_FIELDS", "GROK_API", "GROK_DAILY_REQUEST_LIMIT"]
    assert body["enabled_fields"] == ["property_address", "priority"]
    assert body["key_logged"] is False
    assert "GROK_API_KEY" not in str(body)


def test_the_ai_settings_refuse_an_unknown_field_and_an_empty_list(client, db, monkeypatch):
    from app.services import private_settings

    written = []
    monkeypatch.setattr(private_settings, "write_private", lambda values: written.append(values))

    unknown = client.patch("/api/integrations/grok/settings", json={"fields": ["phone_number"]})
    assert unknown.status_code == 400
    assert "phone_number" in unknown.json()["detail"]

    empty = client.patch("/api/integrations/grok/settings", json={"fields": []})
    assert empty.status_code == 400

    nothing = client.patch("/api/integrations/grok/settings", json={})
    assert nothing.status_code == 400
    assert written == [], "a rejected change must not touch the private settings file"


def test_the_field_list_can_be_saved_because_the_allow_list_permits_it():
    """write_private refuses any key outside ALLOWED; GROK_AI_FIELDS used to be missing."""
    from app.services import private_settings

    assert "GROK_AI_FIELDS" in private_settings.ALLOWED
