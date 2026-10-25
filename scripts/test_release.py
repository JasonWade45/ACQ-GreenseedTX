"""Extract a public release into a path with spaces, verify hashes and boot its real app.

Uses this interpreter's installed dependencies, not Node or dependencies in the ZIP.
No production database, vendor key, live provider or native Windows helper is used.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]

CHECK = r"""
from pathlib import Path
import json, os, re, sqlite3
from fastapi.testclient import TestClient
from app.main import app
from app.config import ROOT, get_settings
from app.db import SessionLocal, engine
from app.services.cloud_ai import cloud_status
assert ROOT == Path.cwd()
settings = get_settings()
assert settings.resimpli_mode == "disabled" and not settings.resimpli_api_key
assert not settings.groq_enabled and not settings.groq_api_key
assert not settings.ollama_enabled and not settings.sync_enabled
with TestClient(app) as client:
    index = client.get("/")
    assert index.status_code == 200 and '<div id="root"></div>' in index.text
    assets = re.findall(r'(?:src|href)="([^\"]+\.(?:js|css))"', index.text)
    assert len(assets) == 2 and all(path.startswith("/assets/") for path in assets)
    assert all(client.get(path).status_code == 200 for path in assets)
    assert client.get("/leads/1").status_code == 200
    assert client.get("/api/leads").status_code == 401
    token = client.post("/api/auth/login", json={"password":settings.app_access_password}).json()["token"]
    client.headers["Authorization"] = "Bearer " + token
    assert client.get("/api/leads").json()["total"] == 0
    assert client.get("/api/workspace-merges").json() == []
    view = client.get("/api/settings").json()
    assert not view["external_writes"] and not view["automatic_communication"]
    with SessionLocal() as session:
        cloud = cloud_status(session, settings)
        assert cloud["consent_mode"] == "redacted_review_each_request"
        assert not cloud["automatic_processing"] and not cloud["crm_writes"]
    original = settings.app_access_password
    settings.app_access_password = ""
    assert client.get("/api/health", headers={"host":"untrusted.invalid"}).status_code == 403
    settings.app_access_password = original
engine.dispose()
path = Path(settings.database_url.removeprefix("sqlite:///"))
with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True) as db:
    revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'") if not row[0].startswith("sqlite_")}
    assert revision == "0a6d91cf17b2" and {"call_plans","workspace_merges"}.issubset(tables)
    assert db.execute("SELECT count(*) FROM leads").fetchone()[0] == 0
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not db.execute("PRAGMA foreign_key_check").fetchall()
print(json.dumps({
    "passed":True,"release":"1.2.1","fresh_database_leads":0,"revision":revision,
    "application_tables":len(tables)-1,"index_http_status":200,"built_assets_served":len(assets),
    "authenticated_api_checked":True,"groq_disabled":True,"crm_disabled":True,
    "keys_not_configured":True,"consent_policy":"redacted_review_each_request",
    "loopback_host_rebinding_rejected":True,"integrity":"ok","foreign_key_violations":0,
    "path_contains_spaces":True,"actual_company_database_used":False,
    "native_windows_helper_executed":False
}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT.parent / "acquisitions-assistant-v1.2.zip")
    parser.add_argument("--report", type=Path, help="Optional JSON report output")
    args = parser.parse_args()
    (ROOT / "data").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="release smoke with spaces ", dir=ROOT / "data") as directory:
        destination = Path(directory)
        with zipfile.ZipFile(args.archive) as archive:
            assert archive.testzip() is None
            for name in archive.namelist():
                path = PurePosixPath(name)
                assert not path.is_absolute() and ".." not in path.parts and path.parts[0] == "acquisitions-assistant"
                assert not {"data", "node_modules", ".venv", "__pycache__", "backups"}.intersection(path.parts)
                assert not path.name.startswith(".preview")
                assert not path.name.startswith(".env") or path.name == ".env.example"
                assert not path.name.endswith((".db", ".db-wal", ".db-shm", ".bak", ".log"))
            archive.extractall(destination)
        project = destination / "acquisitions-assistant"
        manifest = project / "RELEASE_FILES.sha256"
        records = manifest.read_text(encoding="utf-8").splitlines()
        for record in records:
            expected, relative = record.split("  ", 1)
            assert hashlib.sha256((project / relative).read_bytes()).hexdigest() == expected, relative
        private = destination / "isolated runtime"
        private.mkdir(mode=0o700)
        env = {
            **os.environ,
            "PYTHONPATH": str(project / "backend"),
            "DATABASE_URL": "sqlite:///" + str(private / "fresh.db"),
            "APP_HOST": "127.0.0.1",
            "APP_ACCESS_PASSWORD": secrets.token_urlsafe(24),
            "SESSION_SECRET": secrets.token_urlsafe(40),
            "APP_PRIVATE_SETTINGS_PATH": str(private / "unused-private.env"),
            "RESIMPLI_MODE": "disabled",
            "RESIMPLI_API_KEY": "",
            "SYNC_ENABLED": "false",
            "GROQ_ENABLED": "false",
            "GROQ_API_KEY": "",
            "OLLAMA_ENABLED": "false",
        }
        result = subprocess.run(
            [sys.executable, "-c", CHECK], cwd=project, env=env, capture_output=True, text=True, timeout=60
        )
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        report = json.loads(result.stdout.strip().splitlines()[-1])
        report["archive_files"] = len(records) + 1
        report["all_included_file_hashes_verified"] = True
        report["private_runtime_files_excluded"] = True
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
