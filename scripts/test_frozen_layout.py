"""Prove the packaged layout works before PyInstaller is ever involved.

PyInstaller puts read-only files in a temporary bundle directory and tells the app
where it is through ``sys._MEIPASS``. This script builds that same layout in a
temporary folder, fakes the three attributes PyInstaller sets, and then boots the
real application from inside it: migrations, interface, health, and the data folder.

It catches the failure that would otherwise only show up on a user's PC: a file the
app reads but the build forgot to carry.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_windows import bundle_datas  # noqa: E402

CHILD = r'''
import json, os, sys
from pathlib import Path

# What PyInstaller sets in a real executable.
sys.frozen = True
sys._MEIPASS = os.environ["FAKE_BUNDLE"]
sys.executable = str(Path(os.environ["FAKE_BUNDLE"]) / "ACQ.exe")

from fastapi.testclient import TestClient
from app.main import app, migrate
from app.config import get_settings, ROOT, DATA_ROOT
from app.paths import browser_ui_ready, data_root, resource_root
import sqlite3

settings = get_settings()
root_matches = str(resource_root()) == os.environ["FAKE_BUNDLE"]
data_matches = str(data_root()) == os.environ["ACQ_DATA_DIR"]
assert root_matches, f"resource root is {resource_root()}, expected the bundle"
assert data_matches, f"data root is {data_root()}, expected ACQ_DATA_DIR"
assert ROOT == resource_root() and DATA_ROOT == data_root()
assert browser_ui_ready(), "the compiled interface was not found inside the bundle"
assert str(data_root()) not in str(resource_root()), "data must live outside the bundle"

with TestClient(app) as client:
    assert client.get("/api/health").status_code == 200
    index = client.get("/")
    assert index.status_code == 200 and '<div id="root">' in index.text
    import re
    asset = re.search(r'src="(/assets/[^"]+\.js)"', index.text).group(1)
    assert client.get(asset).status_code == 200, asset

database = Path(settings.database_url.removeprefix("sqlite:///"))
assert database.is_file(), f"no database at {database}"
assert str(database).startswith(os.environ["ACQ_DATA_DIR"]), "the database was written inside the bundle"
with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
    revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

print(json.dumps({
    "frozen_layout_ok": True,
    "resource_root": str(resource_root()),
    "data_root": str(data_root()),
    "database": str(database),
    "revision": revision,
    "interface_served": True,
    "migrations_applied": True,
}))
'''


def build_bundle(destination: Path) -> None:
    """Copy the bundle exactly the way PyInstaller reads ``datas``.

    The second element is a *folder* in the bundle: a folder's contents are copied
    into it, a file is placed inside it — which is how an ``alembic.ini``
    destination of "alembic.ini" became a directory and killed the packaged
    program on Windows.
    """
    for source, folder in bundle_datas():
        src = Path(source)
        target_folder = destination / folder
        if not src.exists():
            raise SystemExit(f"Missing build input: {source}")
        target_folder.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, target_folder, dirs_exist_ok=True)
        else:
            shutil.copy2(src, target_folder / src.name)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="acq-frozen-") as temporary:
        base = Path(temporary)
        bundle = base / "bundle"
        data = base / "user-data"
        build_bundle(bundle)

        env = {
            **os.environ,
            "FAKE_BUNDLE": str(bundle),
            "ACQ_DATA_DIR": str(data),
            "PYTHONPATH": str(ROOT / "backend"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "RESIMPLI_MODE": "disabled",
            "SYNC_ENABLED": "false",
            "GROQ_ENABLED": "false",
            "OLLAMA_ENABLED": "false",
            "APP_ACCESS_PASSWORD": "",
        }
        for stray in ("RESIMPLI_API_KEY", "GROQ_API_KEY", "APP_PRIVATE_SETTINGS_PATH"):
            env.pop(stray, None)

        result = subprocess.run(
            [sys.executable, "-c", CHILD], cwd=bundle, env=env, capture_output=True, text=True, timeout=180
        )
        if result.returncode:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            return 1
        report = json.loads(result.stdout.strip().splitlines()[-1])
        print(json.dumps(report, indent=2))
        print("The packaged layout boots, migrates and serves the interface with data kept outside it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
