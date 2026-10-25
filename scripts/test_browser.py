"""Run real browser tests against a disposable, authenticated fixture workspace."""

import argparse
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true", help="Use the existing production frontend build")
    parser.add_argument(
        "--cloud-fixture", action="store_true", help="Synthetic Groq provider; no real account or external requests"
    )
    args = parser.parse_args()
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("Node.js/npm is required. Run the setup script first.")
    if not args.skip_build:
        subprocess.run([npm, "--prefix", "frontend", "run", "build"], cwd=ROOT, check=True)
    if not (ROOT / "frontend/dist/index.html").exists():
        raise SystemExit("No production frontend build. Run npm --prefix frontend run build.")
    (ROOT / "data").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="browser-qa-", dir=ROOT / "data") as directory:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        legacy_source = Path(directory) / "synthetic-legacy-source.db"
        with sqlite3.connect(legacy_source) as legacy:
            legacy.executescript((ROOT / "backend/fixtures/legacy-workspace.sql").read_text(encoding="utf-8"))
        password = secrets.token_urlsafe(24)
        env = {
            **os.environ,
            "DATABASE_URL": "sqlite:///" + str(Path(directory) / "isolated.db"),
            "APP_TIMEZONE": "America/New_York",
            "MAX_IMPORT_ROWS": "50000",
            "MAX_UPLOAD_MB": "25",
            "GROQ_ENABLED": "true" if args.cloud_fixture else "false",
            "GROQ_API_KEY": "gsk_SYNTHETIC_BROWSER_TEST_ONLY_NOT_REAL" if args.cloud_fixture else "",
            "APP_PRIVATE_SETTINGS_PATH": str(Path(directory) / "private.env"),
            "ALLOW_SYNTHETIC_CLOUD_HARNESS": "SYNTHETIC_ONLY_NO_NETWORK" if args.cloud_fixture else "",
            "E2E_CLOUD_FIXTURE": "1" if args.cloud_fixture else "",
            "RESIMPLI_MODE": "fixture",
            "RESIMPLI_API_KEY": "",
            "SYNC_ENABLED": "false",
            "OLLAMA_ENABLED": "false",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": str(port),
            "APP_ACCESS_PASSWORD": password,
            "SESSION_SECRET": secrets.token_urlsafe(40),
            "E2E_PASSWORD": password,
            "E2E_LEGACY_SOURCE": str(legacy_source),
            "E2E_BASE_URL": f"http://127.0.0.1:{port}",
        }
        with open(Path(directory) / "server.log", "w+", encoding="utf-8") as log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "qa_cloud_server:app" if args.cloud_fixture else "app.main:app",
                    "--app-dir",
                    "scripts" if args.cloud_fixture else "backend",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        raise RuntimeError("Isolated test server exited during startup.")
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(0.1)
                else:
                    raise TimeoutError("Isolated test server did not become healthy in 60 seconds.")
                print("Running browser tests with a fresh synthetic database; no real account is accessed.", flush=True)
                result = subprocess.run([npm, "run", "test:e2e"], cwd=ROOT / "frontend", env=env)
                return result.returncode
            except Exception:
                log.flush()
                log.seek(0)
                print(log.read()[-12000:], file=sys.stderr)
                raise
            finally:
                server.terminate()
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
