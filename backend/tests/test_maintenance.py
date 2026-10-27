import os
import sqlite3
import subprocess
import sys
import pytest
from app.config import ROOT


def test_migrations_online_backup_and_integrity(tmp_path):
    database = tmp_path / "new.db"
    env = {**os.environ, "DATABASE_URL": "sqlite:///" + str(database), "APP_ACCESS_PASSWORD": ""}
    migrated = subprocess.run(
        [sys.executable, "scripts/manage.py", "migrate"], cwd=ROOT, env=env, capture_output=True, text=True
    )
    assert migrated.returncode == 0, migrated.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM leads").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM pipeline_stages").fetchone()[0] == 15
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    backup = tmp_path / "backup.db"
    result = subprocess.run(
        [sys.executable, "scripts/manage.py", "backup", "--output", str(backup)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and backup.exists()
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    refused = subprocess.run(
        [sys.executable, "scripts/manage.py", "backup", "--output", str(backup)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert refused.returncode == 1  # Existing backups are never overwritten silently.


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_RESIMPLI_TESTS") != "I_APPROVE_READ_ONLY_ACCOUNT_TEST",
    reason="Real account access is explicit opt-in; fixtures are the default",
)
def test_real_account_key_validation_opt_in_only():
    from app.config import get_settings
    from app.services.resimpli import ResimpliClient

    settings = get_settings()
    assert settings.resimpli_mode == "live" and settings.resimpli_adapter_verified
    client = ResimpliClient(settings)
    try:
        assert isinstance(client.request("/getUserInfo"), dict)
    finally:
        client.close()


def test_restore_preserves_backup_and_rejects_wrong_confirmation(tmp_path):
    source = tmp_path / "trusted.db"
    env = {**os.environ, "DATABASE_URL": "sqlite:///" + str(source), "APP_ACCESS_PASSWORD": ""}
    assert (
        subprocess.run(
            [sys.executable, "scripts/manage.py", "migrate"], cwd=ROOT, env=env, capture_output=True
        ).returncode
        == 0
    )
    target = tmp_path / "restored.db"
    env["DATABASE_URL"] = "sqlite:///" + str(target)
    refused = subprocess.run(
        [sys.executable, "scripts/manage.py", "restore", "--input", str(source), "--confirm", "no"],
        cwd=ROOT,
        env=env,
        capture_output=True,
    )
    assert refused.returncode != 0 and not target.exists()
    restored = subprocess.run(
        [sys.executable, "scripts/manage.py", "restore", "--input", str(source), "--confirm", "RESTORE LOCAL DATABASE"],
        cwd=ROOT,
        env=env,
        capture_output=True,
    )
    assert restored.returncode == 0, restored.stderr
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT count(*) FROM pipeline_stages").fetchone()[0] == 15
    again = subprocess.run(
        [sys.executable, "scripts/manage.py", "restore", "--input", str(source), "--confirm", "RESTORE LOCAL DATABASE"],
        cwd=ROOT,
        env=env,
        capture_output=True,
    )
    assert again.returncode == 0
    assert len(list(tmp_path.glob("restored.db.pre-restore-*.bak"))) == 1


def test_migration_preserves_application_error_loggers(tmp_path):
    env = {
        **os.environ,
        "DATABASE_URL": "sqlite:///" + str(tmp_path / "logging.db"),
        "APP_ACCESS_PASSWORD": "",
        "RESIMPLI_MODE": "disabled",
        "RESIMPLI_API_KEY": "",
        "SYNC_ENABLED": "false",
        "OLLAMA_ENABLED": "false",
    }
    script = """
import logging, sys
sys.path.insert(0, 'backend')
from app.main import migrate
loggers = [logging.getLogger(name) for name in ('uvicorn', 'uvicorn.error', 'apscheduler.scheduler')]
assert all(not logger.disabled for logger in loggers)
migrate()
assert all(not logger.disabled for logger in loggers), 'Migration disabled application error logging'
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_busy_local_port_reports_error_instead_of_silent_exit(tmp_path):
    import socket

    env = {
        **os.environ,
        "DATABASE_URL": "sqlite:///" + str(tmp_path / "busy-port.db"),
        "APP_HOST": "127.0.0.1",
        "APP_ACCESS_PASSWORD": "",
        "RESIMPLI_MODE": "disabled",
        "RESIMPLI_API_KEY": "",
        "SYNC_ENABLED": "false",
        "OLLAMA_ENABLED": "false",
    }
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        result = subprocess.run(
            [sys.executable, "scripts/run.py", "--port", str(port)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "ERROR" in output and str(port) in output, output


def test_backup_is_one_self_contained_file_even_from_a_wal_database(tmp_path):
    """`manage.py backup` must not leave a copy that depends on a -wal sidecar."""
    database = tmp_path / "live.db"
    env = {**os.environ, "DATABASE_URL": "sqlite:///" + str(database), "APP_ACCESS_PASSWORD": ""}
    assert subprocess.run(
        [sys.executable, "scripts/manage.py", "migrate"], cwd=ROOT, env=env, capture_output=True
    ).returncode == 0

    live = sqlite3.connect(database)
    live.execute("PRAGMA journal_mode=WAL")
    # A settings row keeps the fixture independent of the leads NOT NULL columns.
    live.execute("INSERT INTO app_settings (key, value) VALUES ('wal_marker', '{\"written\": true}')")
    live.commit()  # still only in the -wal file
    assert (tmp_path / "live.db-wal").exists()

    backup = tmp_path / "copy.db"
    result = subprocess.run(
        [sys.executable, "scripts/manage.py", "backup", "--output", str(backup)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    live.close()
    assert result.returncode == 0, result.stderr

    assert sorted(p.name for p in tmp_path.glob("copy.db*")) == ["copy.db"]
    with sqlite3.connect(backup) as copy:
        marker = copy.execute("SELECT value FROM app_settings WHERE key='wal_marker'").fetchone()
        assert marker is not None and "written" in marker[0]
        assert copy.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
