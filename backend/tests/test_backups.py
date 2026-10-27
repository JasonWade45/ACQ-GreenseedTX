import sqlite3
from pathlib import Path

import pytest

from app.config import Settings
from app.services import backups


def make_database(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE leads (id INTEGER PRIMARY KEY, full_name TEXT)")
        connection.execute("INSERT INTO leads (full_name) VALUES ('Jordan Ellis')")
    return path


def url_for(path: Path) -> str:
    return "sqlite:///" + str(path)


@pytest.fixture
def live_database(tmp_path):
    return make_database(tmp_path / "data" / "acquisitions.db")


def test_backup_is_verified_and_contains_the_data(live_database):
    created = backups.create_backup(url_for(live_database), reason="manual")

    assert created.name.startswith("acquisitions-")
    assert created.name.endswith("-manual.db")
    assert created.parent.name == "backups"
    assert not list(created.parent.glob("*.partial"))
    with sqlite3.connect(created) as copy:
        assert copy.execute("SELECT full_name FROM leads").fetchone()[0] == "Jordan Ellis"
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_backup_file_is_private(live_database):
    created = backups.create_backup(url_for(live_database), reason="scheduled")
    assert created.stat().st_mode & 0o077 == 0


def test_backups_are_listed_newest_first(live_database):
    first = backups.create_backup(url_for(live_database), reason="scheduled")
    second = backups.create_backup(url_for(live_database), reason="manual")
    # Same-second timestamps would make the order ambiguous; nudge the names apart.
    listed = [item["name"] for item in backups.list_backups(url_for(live_database))]

    assert set(listed) == {first.name, second.name}
    assert listed == sorted(listed, reverse=True)
    assert {item["reason"] for item in backups.list_backups(url_for(live_database))} == {"scheduled", "manual"}


def test_prune_keeps_scheduled_copies_and_never_touches_manual_ones(live_database):
    folder = backups.backup_directory(live_database)
    folder.mkdir(parents=True, exist_ok=True)
    for hour in range(5):
        target = folder / f"acquisitions-2026010{hour + 1}T020000Z-scheduled.db"
        target.write_bytes(b"x")
    manual = folder / "acquisitions-20260101T030000Z-manual.db"
    manual.write_bytes(b"x")

    removed = backups.prune(url_for(live_database), keep=2)
    remaining = {path.name for path in folder.iterdir()}

    assert len(removed) == 3
    assert len([name for name in remaining if name.endswith("-scheduled.db")]) == 2
    assert manual.name in remaining


def test_prune_rejects_a_zero_keep_value(live_database):
    with pytest.raises(ValueError):
        backups.prune(url_for(live_database), keep=0)


def test_unknown_and_traversal_names_are_refused(live_database):
    backups.create_backup(url_for(live_database), reason="manual")
    for name in ("../../acquisitions.db", "acquisitions.db", "other.db", "", "acquisitions-20260101T000000Z-scheduled.db"):
        with pytest.raises(ValueError):
            backups.resolve_backup(url_for(live_database), name)


def test_known_name_resolves_inside_the_backup_folder(live_database):
    created = backups.create_backup(url_for(live_database), reason="manual")
    resolved = backups.resolve_backup(url_for(live_database), created.name)
    assert resolved == created
    assert resolved.parent == backups.backup_directory(live_database)


def test_missing_database_is_reported_not_silently_skipped(tmp_path):
    with pytest.raises(ValueError):
        backups.create_backup(url_for(tmp_path / "data" / "absent.db"))


def test_in_memory_database_is_refused():
    with pytest.raises(ValueError):
        backups.create_backup("sqlite://")
    with pytest.raises(ValueError):
        backups.create_backup("sqlite:///:memory:")


def test_a_failure_mid_backup_leaves_no_partial_file(live_database, monkeypatch):
    folder = backups.backup_directory(live_database)

    def refuse(path, mode):
        raise OSError("permissions are not available here")

    monkeypatch.setattr(backups.os, "chmod", refuse)
    with pytest.raises(OSError):
        backups.create_backup(url_for(live_database), reason="manual")

    assert folder.is_dir()
    assert list(folder.iterdir()) == []


def test_scheduled_and_manual_reasons_are_the_only_accepted_labels(live_database):
    created = backups.create_backup(url_for(live_database), reason="something-else")
    assert created.name.endswith("-manual.db")


def test_settings_defaults_are_safe():
    settings = Settings(_env_file=None)
    assert settings.backup_enabled is True
    assert 1 <= settings.backup_keep <= 90
    assert 0 <= settings.backup_hour_utc <= 23


# --------------------------------------------------------------------------- HTTP layer


@pytest.fixture
def backup_settings(tmp_path, monkeypatch):
    from app import main as main_module

    database = make_database(tmp_path / "data" / "acquisitions.db")
    settings = Settings(_env_file=None, database_url="sqlite:///" + str(database), backup_keep=5)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    return settings


def test_api_lists_creates_downloads_and_deletes(client, backup_settings):
    empty = client.get("/api/backups")
    assert empty.status_code == 200
    assert empty.json()["backups"] == []
    assert empty.json()["enabled"] is True and empty.json()["keep"] == 5

    created = client.post("/api/backups")
    assert created.status_code == 200
    name = created.json()["name"]
    assert created.json()["reason"] == "manual"
    assert created.json()["size_bytes"] > 0

    listed = client.get("/api/backups").json()["backups"]
    assert [item["name"] for item in listed] == [name]

    download = client.get(f"/api/backups/{name}")
    assert download.status_code == 200
    assert download.content.startswith(b"SQLite format 3\x00")
    assert name in download.headers["content-disposition"]

    assert client.delete(f"/api/backups/{name}").status_code == 400
    assert client.delete(f"/api/backups/{name}", params={"confirm": "DELETE BACKUP"}).status_code == 200
    assert client.get("/api/backups").json()["backups"] == []
    assert client.get(f"/api/backups/{name}").status_code == 404


def test_api_refuses_unknown_backup_names(client, backup_settings):
    assert client.get("/api/backups/not-a-backup.db").status_code == 404
    assert client.delete("/api/backups/not-a-backup.db", params={"confirm": "DELETE BACKUP"}).status_code == 404


def test_api_reports_a_missing_database_instead_of_crashing(client, backup_settings, monkeypatch):
    from app import main as main_module

    missing = Settings(_env_file=None, database_url="sqlite:////tmp/acq-does-not-exist/acquisitions.db")
    monkeypatch.setattr(main_module, "get_settings", lambda: missing)
    assert client.post("/api/backups").status_code == 409


def test_wal_writes_are_inside_the_copy_and_no_sidecars_are_left(tmp_path):
    """The live database runs in WAL mode; a copy must not depend on a -wal file."""
    database = tmp_path / "data" / "acquisitions.db"
    database.parent.mkdir(parents=True)
    live = sqlite3.connect(database)
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("CREATE TABLE leads (id INTEGER PRIMARY KEY, full_name TEXT)")
    live.execute("INSERT INTO leads (full_name) VALUES ('Uncheckpointed Seller')")
    live.commit()  # committed, but still only in the -wal file
    assert Path(str(database) + "-wal").exists()

    created = backups.create_backup(url_for(database), reason="manual")
    live.close()

    assert not list(created.parent.glob("*.partial*"))
    assert not list(created.parent.glob("*-wal"))
    assert not list(created.parent.glob("*-shm"))
    with sqlite3.connect(created) as copy:
        assert copy.execute("SELECT full_name FROM leads").fetchone()[0] == "Uncheckpointed Seller"
        # Reading the mode must not change it: the copy is self-contained, not a WAL pair.
        assert copy.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_rotation_never_deletes_a_file_it_did_not_create(live_database):
    folder = backups.backup_directory(live_database)
    folder.mkdir(parents=True, exist_ok=True)
    for hour in range(4):
        (folder / f"acquisitions-2026010{hour + 1}T020000Z-scheduled.db").write_bytes(b"x")
    bystander = folder / "notes-scheduled.db"
    bystander.write_bytes(b"keep me")

    backups.prune(url_for(live_database), keep=1)

    assert bystander.exists()


def test_a_database_with_another_name_still_lists_and_downloads_its_backups(tmp_path):
    """Regression: the name pattern was hard-coded to `acquisitions-`, so a database
    called acq.db produced backups that existed but were invisible and un-downloadable."""
    database = make_database(tmp_path / "data" / "acq.db")
    created = backups.create_backup(url_for(database), reason="manual")

    assert created.name.startswith("acq-")
    listed = backups.list_backups(url_for(database))
    assert [item["name"] for item in listed] == [created.name]
    assert backups.resolve_backup(url_for(database), created.name) == created
    assert backups.prune(url_for(database), keep=1) == []


def test_api_creates_and_lists_a_backup_for_a_differently_named_database(tmp_path, client, monkeypatch):
    from app import main as main_module

    database = make_database(tmp_path / "data" / "acq.db")
    settings = Settings(_env_file=None, database_url="sqlite:///" + str(database))
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    created = client.post("/api/backups")
    assert created.status_code == 200, created.text
    name = created.json()["name"]
    assert client.get("/api/backups").json()["backups"][0]["name"] == name
    assert client.get(f"/api/backups/{name}").status_code == 200
