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

The packaged program (``ACQ.exe``, built from ``desktop/``) runs the same code with
a window instead of a console; both share ``app.launcher``.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.launcher import (  # noqa: E402
    MIN_PASSWORD,
    banner,
    ensure_credentials,
    lan_addresses,
    lan_urls,
    local_url,
    new_password,
    port_is_free,
    qr_lines,
    read_env,
    wait_until_healthy,
    write_env,
)
from app.paths import adopt_legacy_data, data_root, ensure_data_dirs, resource_root  # noqa: E402

ENV_FILE = data_root() / ".env"
ENV_KEYS = ("APP_ACCESS_PASSWORD", "SESSION_SECRET")

# Re-exported so tests and START-ACQ keep using the same names as before.
__all__ = [
    "MIN_PASSWORD",
    "banner",
    "ensure_credentials",
    "lan_addresses",
    "lan_urls",
    "local_url",
    "main",
    "new_password",
    "port_is_free",
    "qr_lines",
    "read_env",
    "wait_until_healthy",
    "write_env",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Acquisitions Assistant locally and reach it from any device")
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT", "8010")))
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Bind to 127.0.0.1 only; a password already saved in .env still applies",
    )
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser window")
    parser.add_argument("--show-password", action="store_true", help="Print the saved password and exit")
    parser.add_argument("--new-password", action="store_true", help="Replace the saved password and exit")
    parser.add_argument("--check", action="store_true", help="Report the planned setup and exit")
    args = parser.parse_args(argv)

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "backend"))

    if args.new_password:
        write_env(ENV_FILE, {"APP_ACCESS_PASSWORD": new_password(), "SESSION_SECRET": os.urandom(32).hex()})
        print(f"New password: {read_env(ENV_FILE)['APP_ACCESS_PASSWORD']}")
        return 0
    if args.show_password:
        print(read_env(ENV_FILE).get("APP_ACCESS_PASSWORD", "") or "No password is set.")
        return 0

    ensure_data_dirs()
    adopt_legacy_data()
    lan = not args.local_only
    password, created = ensure_credentials(ENV_FILE, required=lan)
    host = "0.0.0.0" if lan else "127.0.0.1"

    if not (resource_root() / "frontend" / "dist" / "index.html").exists():
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
            else:
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
    print(f"\nStopped. Your data stays in {data_root() / 'data' / 'acquisitions.db'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
