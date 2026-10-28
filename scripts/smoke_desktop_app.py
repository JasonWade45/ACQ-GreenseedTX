"""Start the desktop program for real, use it, close it, start it again.

This is the check that matters for an installed app: the window's entry point must
boot the server, put the database and password in the data folder (not in the
program folder), refuse a second copy, keep the data across a restart, and answer a
real request with the same password as before.

    python scripts/smoke_desktop_app.py

Runs headless with ``--no-window``, so it works in CI on any platform. It uses a
temporary data folder and touches no real database.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "desktop" / "acq_app.py"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def request(url: str, timeout: float = 3.0, payload: dict | None = None, token: str = ""):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.status, response.read()


def upload(base: str, token: str, csv_text: str) -> dict:
    """Import one seller through the real import endpoints (the way a person does)."""
    boundary = "----acq-smoke"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"leads.csv\"\r\n"
        f"Content-Type: text/csv\r\n\r\n{csv_text}\r\n--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(base + "/api/imports/upload", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as response:
        batch = json.loads(response.read())
    mapping = {
        "name": "full_name",
        "phone": "primary_phone",
        "address": "street_address",
        "city": "city",
        "state": "state",
        "zip": "zip_code",
        "status": "source_status",
        "source": "lead_source",
    }
    request(
        f"{base}/api/imports/{batch['id']}/preview",
        payload={"sheets": ["CSV"], "mapping": mapping, "date_order": "reject"},
        token=token,
    )
    _, detail = request(f"{base}/api/imports/{batch['id']}", token=token)
    rows = [row["id"] for row in json.loads(detail)["rows"]]
    _, done = request(
        f"{base}/api/imports/{batch['id']}/approve",
        payload={"row_ids": rows, "confirmation": "IMPORT LOCAL", "destination": "local"},
        token=token,
    )
    return json.loads(done)


def wait_for(url: str, timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if request(url)[0] == 200:
                return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(0.5)
    return False


def launch(data_dir: Path, port: int, env_extra: dict | None = None) -> subprocess.Popen:
    env = {
        **os.environ,
        "ACQ_DATA_DIR": str(data_dir),
        "ACQ_NO_WINDOW": "1",
        **{k: v for k, v in (env_extra or {}).items()},
    }
    for stray in ("APP_ACCESS_PASSWORD", "RESIMPLI_API_KEY", "GROQ_API_KEY", "APP_PRIVATE_SETTINGS_PATH"):
        env.pop(stray, None)
    return subprocess.Popen(
        [sys.executable, str(APP), "--no-window", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def stop(process: subprocess.Popen) -> str:
    process.terminate()
    try:
        output, _ = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        output = ""
    return output or ""


def main() -> int:
    report: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="acq-desktop-smoke-") as temporary:
        data_dir = Path(temporary) / "user-data"
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        password = ""

        # ---- first run: creates the data folder, the password and the database
        first = launch(data_dir, port)
        try:
            if not wait_for(base + "/api/health"):
                print(stop(first))
                raise SystemExit("The program never answered /api/health on its first run")
            status, page = request(base + "/")
            if status != 200 or b'<div id="root">' not in page:
                raise SystemExit("The interface was not served")
            password = ""
            env_text = (data_dir / ".env").read_text()
            for line in env_text.splitlines():
                if line.startswith("APP_ACCESS_PASSWORD="):
                    password = line.split("=", 1)[1].strip()
            if len(password) < 12:
                raise SystemExit("No usable password was generated in the data folder")
            database = data_dir / "data" / "acquisitions.db"
            if not database.is_file():
                raise SystemExit("The database was not created in the data folder")
            if str(database).startswith(str(ROOT / "data")):
                raise SystemExit("The database was written inside the program folder")

            # a second copy must not start its own server
            other_port = free_port()
            second = launch(data_dir, other_port)
            second_rc = second.wait(timeout=60)
            if second_rc != 0:
                print(second.stdout.read() if second.stdout else "")
                raise SystemExit("A second copy exited with an error instead of standing down")
            try:
                request(f"http://127.0.0.1:{other_port}/api/health", timeout=2)
                raise SystemExit("A second copy started its own server")
            except (urllib.error.URLError, OSError, TimeoutError):
                pass

            # write something through the real API so the restart has data to keep
            status, body = request(base + "/api/auth/login", payload={"password": password})
            token = json.loads(body)["token"]
            imported = upload(
                base,
                token,
                "name,phone,address,city,state,zip,status,source\n"
                "Smoke Test Seller,+15125550101,10 Smoke Test Rd,Austin,TX,78701,New Lead,Smoke\n",
            )
            if imported["counts"]["imported"] != 1:
                raise SystemExit(f"The import did not save the seller: {imported['counts']}")
            status, body = request(base + "/api/leads", token=token)
            listed = json.loads(body)
            before = listed["total"]
            names = [item["full_name"] for item in listed["items"]]
            if "Smoke Test Seller" not in names:
                raise SystemExit("The imported seller is not listed")
            report["first_run"] = {
                "health": True,
                "password_saved": True,
                "database_in_data_folder": True,
                "second_copy_refused": True,
                "leads_before_restart": before,
            }
        finally:
            stop(first)

        # ---- second run: same folder, same password, same database
        port2 = free_port()
        base2 = f"http://127.0.0.1:{port2}"
        again = launch(data_dir, port2)
        try:
            if not wait_for(base2 + "/api/health"):
                print(stop(again))
                raise SystemExit("The program did not start again on the same data folder")
            status, body = request(base2 + "/api/auth/login", payload={"password": password})
            if status != 200:
                raise SystemExit("The saved password stopped working after a restart")
            token = json.loads(body)["token"]
            status, body = request(base2 + "/api/leads", token=token)
            listed = json.loads(body)
            after = listed["total"]
            names = [item["full_name"] for item in listed["items"]]
            if after != report["first_run"]["leads_before_restart"] or "Smoke Test Seller" not in names:
                raise SystemExit("The seller did not survive a restart")
            report["second_run"] = {
                "health": True,
                "password_reused": True,
                "leads_after_restart": after,
                "seller_survived_restart": True,
            }
        finally:
            stop(again)

    report["passed"] = True
    print(json.dumps(report, indent=2))
    print("The desktop program starts, keeps its data outside the program folder, refuses a second copy and reopens the same database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
