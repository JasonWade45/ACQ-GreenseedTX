"""One-process, same-origin local server. Use Ctrl+C to stop."""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)


def main():
    import uvicorn
    from app.config import get_settings

    parser = argparse.ArgumentParser(description="Run Acquisitions Assistant AI locally")
    parser.add_argument("--host", help="Default: 127.0.0.1. A non-loopback bind requires a strong APP_ACCESS_PASSWORD.")
    parser.add_argument("--port", type=int, help="Default: 8000")
    args = parser.parse_args()
    if args.host:
        os.environ["APP_HOST"] = args.host
    if args.port:
        os.environ["APP_PORT"] = str(args.port)
    get_settings.cache_clear()
    settings = get_settings()
    if settings.app_host not in {"127.0.0.1", "localhost", "::1"} and len(settings.app_access_password) < 12:
        parser.error(
            "Remote binding requires APP_ACCESS_PASSWORD with at least 12 characters. Use a trusted TLS tunnel."
        )
    if not (ROOT / "frontend/dist/index.html").exists():
        parser.error("Build the frontend first: cd frontend && npm ci && npm run build")
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        workers=1,
        access_log=False,
        log_level="info",
        use_colors=False if os.name == "nt" else None,
        proxy_headers=True,
        # Behind Caddy in Docker the peer is a bridge address, not loopback. Set
        # FORWARDED_ALLOW_IPS to that network (or "*" when the app port is not published)
        # so rate limiting sees real clients instead of one shared proxy address.
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
