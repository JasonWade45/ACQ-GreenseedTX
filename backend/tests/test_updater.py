"""The one-click update must never cost a user their data.

These tests build a fake "old installation" in a temporary folder and copy the real
release files over it, so every promise in the banner is checked, not described.
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("update_acq", ROOT / "scripts" / "update_acq.py")
updater = importlib.util.module_from_spec(SPEC)
sys.modules["update_acq"] = updater
SPEC.loader.exec_module(updater)


def make_install(tmp_path, version="1.2.5", password="Acq-keep-me-please-123"):
    """A small but structurally real installation: code, .env, data and a venv marker."""
    old = tmp_path / "old-install"
    (old / "backend" / "app").mkdir(parents=True)
    (old / "backend" / "app" / "version.py").write_text(f'APP_VERSION = "{version}"\n', encoding="utf-8")
    (old / "scripts").mkdir()
    (old / "scripts" / "manage.py").write_text("# old manage\n", encoding="utf-8")
    (old / "frontend" / "dist").mkdir(parents=True)
    (old / "frontend" / "dist" / "index.html").write_text("<html>old</html>", encoding="utf-8")
    (old / "data").mkdir()
    (old / "data" / "acquisitions.db").write_bytes(b"SQLite format 3\x00 old database")
    (old / ".env").write_text(
        f"APP_ACCESS_PASSWORD={password}\nSESSION_SECRET={'a' * 64}\n", encoding="utf-8"
    )
    (old / ".venv" / "bin").mkdir(parents=True)
    (old / ".venv" / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
    (old / "backups").mkdir()
    return old


def make_release(tmp_path, version="1.2.6"):
    """A release folder shaped like the real ZIP: code, docs, plus files to preserve."""
    new = tmp_path / "new-release"
    (new / "backend" / "app").mkdir(parents=True)
    (new / "backend" / "app" / "version.py").write_text(f'APP_VERSION = "{version}"\n', encoding="utf-8")
    (new / "backend" / "app" / "main.py").write_text("# new main\n", encoding="utf-8")
    (new / "scripts").mkdir()
    (new / "scripts" / "manage.py").write_text("# new manage\n", encoding="utf-8")
    (new / "frontend" / "dist").mkdir(parents=True)
    (new / "frontend" / "dist" / "index.html").write_text("<html>new</html>", encoding="utf-8")
    (new / "README.md").write_text("# release\n", encoding="utf-8")
    # A release must never ship these, but if one sneaks in it still must not win.
    (new / ".env").write_text("APP_ACCESS_PASSWORD=leaked\n", encoding="utf-8")
    (new / "data").mkdir()
    (new / "data" / "acquisitions.db").write_bytes(b"empty template")
    (new / "node_modules").mkdir()
    (new / "node_modules" / "junk.js").write_text("x", encoding="utf-8")
    return new


def test_release_files_skips_data_env_venv_and_node_modules(tmp_path):
    new = make_release(tmp_path)
    files = updater.release_files(new)

    assert "backend/app/main.py" in files
    assert "frontend/dist/index.html" in files
    assert not any(name.startswith("data/") for name in files)
    assert ".env" not in files
    assert not any("node_modules" in name for name in files)


def test_read_version_reads_the_declared_constant(tmp_path):
    new = make_release(tmp_path, "1.2.10")
    assert updater.read_version(new) == "1.2.10"
    assert updater.version_tuple("1.2.10") > updater.version_tuple("1.2.9")


def test_source_must_be_a_release_and_target_an_installation(tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    with pytest.raises(updater.UpdateError, match="not a release folder"):
        updater.check_source(broken)

    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "scripts").mkdir()
    (empty / "scripts" / "manage.py").write_text("", encoding="utf-8")
    with pytest.raises(updater.UpdateError, match="versions.py|is not an Acquisitions Assistant installation"):
        updater.check_target(empty)


def test_copying_never_overwrites_the_live_data_or_settings(tmp_path):
    old = make_install(tmp_path)
    new = make_release(tmp_path)
    password_before = (old / ".env").read_text(encoding="utf-8")
    database_before = (old / "data" / "acquisitions.db").read_bytes()

    files = updater.release_files(new)
    replaced, created = updater.copy_release(new, old, files)

    assert "backend/app/main.py" in created
    assert "frontend/dist/index.html" in replaced
    assert (old / ".env").read_text(encoding="utf-8") == password_before
    assert (old / "data" / "acquisitions.db").read_bytes() == database_before
    assert (old / "frontend" / "dist" / "index.html").read_text(encoding="utf-8") == "<html>new</html>"
    assert updater.read_version(old) == "1.2.6"


def test_snapshot_keeps_every_file_that_will_be_replaced(tmp_path):
    old = make_install(tmp_path)
    new = make_release(tmp_path)
    files = updater.release_files(new)

    snapshot = updater.snapshot_target(old, files, "20260101-000000")

    assert snapshot.parent == old / "backups"
    assert (snapshot / "scripts" / "manage.py").read_text(encoding="utf-8") == "# old manage\n"
    assert (snapshot / "frontend" / "dist" / "index.html").exists()
    # Files that do not exist yet are not invented in the snapshot.
    assert not (snapshot / "backend" / "app" / "main.py").exists()


def test_rollback_restores_replaced_files_and_deletes_new_ones(tmp_path):
    old = make_install(tmp_path)
    new = make_release(tmp_path)
    files = updater.release_files(new)
    snapshot = updater.snapshot_target(old, files, "20260101-000000")
    replaced, created = updater.copy_release(new, old, files)
    assert (old / "backend" / "app" / "main.py").exists()

    updater.rollback(old, snapshot, created)

    assert not (old / "backend" / "app" / "main.py").exists()
    assert (old / "scripts" / "manage.py").read_text(encoding="utf-8") == "# old manage\n"
    assert (old / "frontend" / "dist" / "index.html").read_text(encoding="utf-8") == "<html>old</html>"
    assert updater.read_version(old) == "1.2.5"
    assert (old / "data" / "acquisitions.db").exists()
    assert (old / ".env").exists()


def test_plan_refuses_the_same_folder_and_missing_venv(tmp_path):
    old = make_install(tmp_path)
    with pytest.raises(updater.UpdateError, match="same"):
        updater.plan(old, old)

    new = make_release(tmp_path)
    (old / ".venv" / "bin" / "python").unlink()
    steps = updater.plan(new, old)  # planning alone must not need a venv
    assert steps["to_version"] == "1.2.6"
    with pytest.raises(updater.UpdateError, match="ready Python environment"):
        updater.venv_python(old)


def test_update_is_refused_while_the_port_is_busy(tmp_path):
    old = make_install(tmp_path)
    new = make_release(tmp_path)
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        port = busy.getsockname()[1]
        with pytest.raises(updater.UpdateError, match="still running"):
            updater.update(new, old, port=port, verify=False)


def test_same_version_stops_before_touching_anything(tmp_path):
    old = make_install(tmp_path, "1.2.6")
    new = make_release(tmp_path, "1.2.6")

    result = updater.update(new, old, port=updater.free_port(), verify=False)

    assert result["status"] == "up-to-date"
    assert not (old / "backups").joinpath("code-before-20260101-000000").exists()


def test_a_failed_step_restores_the_previous_version(tmp_path, monkeypatch):
    old = make_install(tmp_path)
    new = make_release(tmp_path)

    def fake_backup(target, python, version):
        # Pretend the database was copied; the real command needs a real interpreter.
        destination = target / "backups" / f"before-update-{version}.db"
        destination.write_bytes(b"backup")
        return destination

    def explode(*args, **kwargs):
        raise updater.UpdateError("simulated dependency failure")

    monkeypatch.setattr(updater, "backup_database", fake_backup)
    monkeypatch.setattr(updater, "install_dependencies", explode)

    with pytest.raises(updater.UpdateError, match="previous version restored"):
        updater.update(new, old, port=updater.free_port(), verify=False)

    assert updater.read_version(old) == "1.2.5"
    assert not (old / "backend" / "app" / "main.py").exists()
    assert (old / "scripts" / "manage.py").read_text(encoding="utf-8") == "# old manage\n"
    assert (old / ".env").exists()
    assert (old / "data" / "acquisitions.db").read_bytes() == b"SQLite format 3\x00 old database"


def test_a_missing_backup_stops_before_any_file_changes(tmp_path, monkeypatch):
    old = make_install(tmp_path)
    monkeypatch.setattr(updater, "run", lambda *args, **kwargs: "")

    with pytest.raises(updater.UpdateError, match="backup was not produced"):
        updater.backup_database(old, Path("python"), "1.2.6")

    assert updater.read_version(old) == "1.2.5"
    assert (old / "scripts" / "manage.py").read_text(encoding="utf-8") == "# old manage\n"


def test_the_remembered_folder_is_reused(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    old = make_install(tmp_path)

    assert updater.recorded_install() is None
    updater.record_install(old)
    assert updater.recorded_install() == old.resolve()
    assert updater.ask_target(interactive=False) == old.resolve()


def test_release_ships_the_updater_entry_points():
    for name in ("UPDATE-ACQ.cmd", "update-acq.sh", "scripts/update_acq.py"):
        assert (ROOT / name).is_file(), f"{name} is missing from the repository"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits only")
def test_update_script_is_executable():
    assert os.access(ROOT / "update-acq.sh", os.X_OK)


def test_launch_never_blocks_the_updater(monkeypatch, tmp_path):
    """A hidden child that inherits the terminal would hang the updater forever."""
    spawned = []

    class FakeProcess:
        pass

    def fake_popen(command, **kwargs):
        spawned.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(updater.os, "name", "nt")

    updater.launch_app(tmp_path)

    assert spawned, "the app was not started on Windows"
    command, kwargs = spawned[0]
    assert kwargs["stdin"] is updater.subprocess.DEVNULL
    assert kwargs["stdout"] is updater.subprocess.DEVNULL
    assert kwargs["start_new_session"] is True


def test_launch_only_prints_a_command_off_windows(monkeypatch, tmp_path, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("a hidden server must never be started off Windows")

    monkeypatch.setattr(updater.subprocess, "Popen", forbidden)
    monkeypatch.setattr(updater.os, "name", "posix")

    updater.launch_app(tmp_path)

    assert "start-acq.sh" in capsys.readouterr().out
