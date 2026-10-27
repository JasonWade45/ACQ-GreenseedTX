"""Desktop launcher: run this app on this computer and open it from any device at home.

It does four things and nothing else:

1. keeps a private ``.env`` with a strong access password (generated on the first run);
2. listens on every network interface so a phone or another laptop can reach it;
3. prints the exact addresses to type, plus a QR code for a phone;
4. opens the browser on this computer once the server answers.

Usage:
    python scripts/acq_desktop.py                 # listen on the local network
    python scripts/acq_desktop.py --port 8010
    python scripts/acq_desktop.py --local-only    # this computer only, no password
    python scripts/acq_desktop.py --show-password
"""

from __future__ import annotations

import argparse
import os
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
ENV_KEYS = ("APP_ACCESS_PASSWORD", "SESSION_SECRET")
MIN_PASSWORD = 12


# --------------------------------------------------------------------------- settings file


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env(path: Path, updates: dict[str, str]) -> None:
    """Merge into an existing file so anything the user added by hand survives."""
    existing = {}
    order: list[str] = []
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                existing[key.strip()] = value
                order.append(key.strip())
    for key, value in updates.items():
        if key not in existing:
            order.append(key)
        existing[key] = value
    body = ["# Written by scripts/acq_desktop.py. Never share or commit this file.", ""]
    body += [f"{key}={existing[key]}" for key in order]
    temporary = path.with_suffix(".env.tmp")
    temporary.write_text("\n".join(body) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def new_password() -> str:
    return "Acq-" + secrets.token_urlsafe(18).replace("-", "x").replace("_", "y")


def ensure_credentials(path: Path, required: bool = True) -> tuple[str, bool]:
    """Return (password, created_now). Generates a strong password once."""
    values = read_env(path)
    password = values.get("APP_ACCESS_PASSWORD", "")
    session = values.get("SESSION_SECRET", "")
    created = False
    updates: dict[str, str] = {}
    if required and len(password) < MIN_PASSWORD:
        password = new_password()
        updates["APP_ACCESS_PASSWORD"] = password
        created = True
    if len(session) < 32:
        updates["SESSION_SECRET"] = secrets.token_hex(32)
    if updates:
        write_env(path, updates)
    return password, created


# --------------------------------------------------------------------------- network


def lan_addresses() -> list[str]:
    """Best-effort list of IPv4 addresses other devices could use. Never loopback."""
    found: set[str] = set()
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            found.add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in found if ip and not ip.startswith("127."))


def local_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def lan_urls(port: int, addresses: list[str]) -> list[str]:
    return [f"http://{ip}:{port}" for ip in addresses]


def port_is_free(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def qr_lines(url: str) -> list[str]:
    """ASCII QR for a phone camera. Optional: segno may be missing on an old install."""
    try:
        import segno
    except ImportError:
        return []
    from io import StringIO

    buffer = StringIO()
    segno.make(url, error="m").terminal(out=buffer, compact=True)
    return [line for line in buffer.getvalue().splitlines() if line.strip()]


# --------------------------------------------------------------------------- server


def wait_until_healthy(port: int, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    target = f"http://127.0.0.1:{port}/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(target, timeout=3) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(0.4)
    return False


def banner(port: int, password: str, created: bool, lan: bool, addresses: list[str]) -> str:
    lines = ["", "  Acquisitions Assistant — running on this computer", ""]
    lines.append(f"  On this computer : {local_url(port)}")
    if lan and addresses:
        lines.append("  From your phone  : " + lan_urls(port, addresses)[0])
        for extra in lan_urls(port, addresses)[1:]:
            lines.append("                     " + extra)
    elif lan:
        lines.append("  From your phone  : no network address found — check Wi-Fi/Ethernet")
    lines.append("")
    if password:
        label = "  Password (save it): " if created else "  Password         : "
        lines.append(label + password)
        if not created:
            lines.append("  (stored in .env · change it there and restart, or run --new-password)")
    else:
        lines.append("  Password         : not set — this computer only")
    lines += ["", "  Keep this window open. Ctrl+C stops the app.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Acquisitions Assistant locally and reach it from any device")
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT", "8010")))
    parser.add_argument("--local-only", action="store_true", help="Bind to 127.0.0.1 and skip the password")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser window")
    parser.add_argument("--show-password", action="store_true", help="Print the saved password and exit")
    parser.add_argument("--new-password", action="store_true", help="Replace the saved password and exit")
    parser.add_argument("--check", action="store_true", help="Report the planned setup and exit")
    args = parser.parse_args(argv)

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "backend"))

    if args.new_password:
        password, _ = ensure_credentials(ENV_FILE, required=False)
        write_env(ENV_FILE, {"APP_ACCESS_PASSWORD": new_password(),
                             "SESSION_SECRET": secrets.token_hex(32)})
        print(f"New password: {read_env(ENV_FILE)['APP_ACCESS_PASSWORD']}")
        return 0
    if args.show_password:
        print(read_env(ENV_FILE).get("APP_ACCESS_PASSWORD", "") or "No password is set.")
        return 0

    lan = not args.local_only
    password, created = ensure_credentials(ENV_FILE, required=lan)
    host = "0.0.0.0" if lan else "127.0.0.1"

    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        print("The bundled interface is missing. Use the complete release folder, not loose source files.")
        return 2
    if not port_is_free(args.port):
        print(f"Port {args.port} is already in use. Close the other copy or pass --port 8011.")
        return 3

    addresses = lan_addresses() if lan else []

    if args.check:
        # Report only; do not touch the process environment of the caller.
        print(banner(args.port, password, created, lan, addresses), flush=True)
        return 0

    os.environ["APP_HOST"] = host
    os.environ["APP_PORT"] = str(args.port)
    if password:
        os.environ["APP_ACCESS_PASSWORD"] = password

    import uvicorn

    print(banner(args.port, password, created, lan, addresses), flush=True)
    if lan and addresses:
        for url in lan_urls(args.port, addresses):
            code = qr_lines(url)
            if code:
                print(f"  Scan to open {url}")
                print("\n".join("    " + line for line in code))
                print(flush=True)
        if not qr_lines("http://example.invalid"):
            print("  (QR codes need the optional 'segno' package: pip install segno)\n", flush=True)

    if not args.no_browser:
        threading.Thread(
            target=lambda: (wait_until_healthy(args.port, timeout=45) and webbrowser.open(local_url(args.port))),
            daemon=True,
        ).start()

    try:
        uvicorn.run(
            "app.main:app",
            host=host,
            port=args.port,
            workers=1,
            access_log=False,
            log_level="info",
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1",
        )
    except KeyboardInterrupt:
        pass
    print("\nStopped. Your data stays in data/acquisitions.db")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
