"""Route-table guarantees: no duplicate registrations, no shadowed static paths."""

from fastapi import FastAPI

from app.main import app
from app.route_audit import duplicate_routes, route_problems, shadowed_routes
from app.services.resimpli import READ_PATHS


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
    for route in app.routes:
        path = (getattr(route, "path", "") or "").lower()
        for word in forbidden:
            assert f"/{word}" not in path or word == "call" and "call-plan" in path, path
        if path.startswith("/api/"):
            assert "resimpli" not in path or "integrations" in path or "sync" in path, path
    # REsimpli stays an explicit read allow-list.
    assert READ_PATHS == frozenset(
        {
            "/lead/list",
            "/lead/details",
            "/activityList",
            "/callLogList",
            "/appointmentList",
            "/getPipelineList",
            "/getUserInfo",
        }
    )
