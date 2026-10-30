"""Route-table guarantees: no duplicate registrations, no shadowed static paths."""

from fastapi import APIRouter, FastAPI

from app import route_allowlist
from app.main import app
from app.route_audit import all_routes, duplicate_routes, route_problems, shadowed_routes
from app.services.resimpli import READ_PATHS
from app.services.resimpli_write import WRITE_PATHS


def test_the_real_route_table_has_no_duplicates_or_shadowed_paths():
    problems = route_problems(app)
    assert problems["duplicates"] == [], problems["duplicates"]
    assert problems["shadowed"] == [], problems["shadowed"]


def test_the_checker_detects_a_duplicate_registration():
    broken = FastAPI()

    @broken.post("/api/leads/{lead_id}/draft")
    def first(lead_id: int):
        return {}

    @broken.post("/api/leads/{lead_id}/draft")
    def second(lead_id: int):
        return {}

    assert ("/api/leads/{lead_id}/draft", "POST") in duplicate_routes(broken.routes)


def test_the_checker_detects_a_shadowed_static_route():
    broken = FastAPI()

    @broken.get("/api/backups/{name}")
    def download(name: str):
        return {}

    @broken.get("/api/backups/config")
    def config():
        return {}

    shadowed = shadowed_routes(broken.routes)
    assert shadowed and shadowed[0]["path"] == "/api/backups/config"
    assert shadowed[0]["shadowed_by"] == "/api/backups/{name}"


def test_backups_config_is_reachable_for_get_and_patch(client, tmp_path):
    read = client.get("/api/backups/config")
    assert read.status_code == 200
    assert read.json()["second_folder"] is None

    folder = tmp_path / "drive"
    folder.mkdir()
    written = client.patch("/api/backups/config", json={"second_folder": str(folder)})
    assert written.status_code == 200
    assert written.json()["second_folder"] == str(folder.resolve())
    assert client.get("/api/backups/config").json()["second_folder"] == str(folder.resolve())

    # Clearing it again is explicit and allowed.
    assert client.patch("/api/backups/config", json={"second_folder": None}).json()["second_folder"] is None


def test_backups_config_rejects_a_missing_folder(client, tmp_path):
    response = client.patch("/api/backups/config", json={"second_folder": str(tmp_path / "nope")})
    assert response.status_code == 400
    assert "does not exist" in response.json()["detail"]


def test_no_route_can_send_a_message_or_write_to_the_crm():
    """The draft-only boundary is asserted on the route table, not just on prose."""
    forbidden = {"send", "sms", "email", "call", "sms/send", "email/send", "messages/send", "calls"}
    rows = all_routes(app)
    assert len(rows) > 100, "included routers must be walked, not skipped"
    for route in rows:
        path = (getattr(route, "path", "") or "").lower()
        for word in forbidden:
            assert f"/{word}" not in path or word == "call" and "call-plan" in path, path
        if path.startswith("/api/"):
            assert "resimpli" not in path or "integrations" in path or "sync" in path, path
    # REsimpli stays an explicit read allow-list, plus exactly one write.
    # The two account lists feed the Settings screen's push defaults; both are
    # documented read-only REsimpli reads added deliberately, never implicitly.
    assert READ_PATHS == frozenset(
        {
            "/lead/list",
            "/lead/details",
            "/activityList",
            "/callLogList",
            "/appointmentList",
            "/getPipelineList",
            "/getUserInfo",
            "/marketingCampaignList",
            "/marketList",
        }
    )
    assert WRITE_PATHS == frozenset({"/lead/add"})


def test_every_new_external_route_is_declared_on_the_allowlist():
    assert route_allowlist.undeclared(app) == [], "a route under these prefixes must be declared"
    assert route_allowlist.missing(app) == [], "a declared route that no longer exists is a stale promise"
    assert route_allowlist.OUTBOUND <= route_allowlist.DECLARED
    assert set(route_allowlist.SCOPE) == set(route_allowlist.OUTBOUND)


def test_the_allowlist_would_catch_an_undeclared_route():
    sneaky = FastAPI()

    @sneaky.post("/api/leads/{lead_id}/crm/delete")
    def delete(lead_id: int):
        return {}

    assert ("POST", "/api/leads/{lead_id}/crm/delete") in route_allowlist.undeclared(sneaky)


def test_an_included_router_is_walked_by_the_audit():
    """A send-shaped route inside a router must fail the boundary test, not hide in it."""
    hidden = FastAPI()
    router = APIRouter()

    @router.post("/api/sms/send")
    def send():
        return {}

    hidden.include_router(router)
    paths = [getattr(route, "path", "") for route in all_routes(hidden)]
    assert "/api/sms/send" in paths


def test_a_forbidden_word_is_still_a_failure():
    """The checker itself is checked: a route the boundary forbids is detectable."""
    broken = FastAPI()

    @broken.post("/api/email/send")
    def email_send():
        return {}

    forbidden = {"send", "sms", "email", "call"}
    paths = [getattr(route, "path", "").lower() for route in all_routes(broken)]
    assert any(any(f"/{word}" in path for word in forbidden) for path in paths)
