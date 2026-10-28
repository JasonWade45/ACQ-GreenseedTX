"""In-app update check (Phase 8). Reads the latest GitHub release over HTTPS."""

from __future__ import annotations

import json
import urllib.request

REPO = "JasonWade45/ACQ-GreenseedTX"
API = f"https://api.github.com/repos/{REPO}/releases/latest"


def latest_release() -> dict | None:
    try:
        req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json", "User-Agent": "ACQ"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return {
            "tag_name": data.get("tag_name"),
            "name": data.get("name"),
            "body": data.get("body"),
            "html_url": data.get("html_url"),
            "published_at": data.get("published_at"),
            "assets": [{"name": a.get("name"), "browser_download_url": a.get("browser_download_url")} for a in data.get("assets", [])],
        }
    except Exception:
        return None


def is_newer(current: str, latest: str | None) -> bool:
    if not latest:
        return False
    try:
        c = [int(x) for x in current.lstrip("v").split(".")]
        latest_parts = [int(x) for x in latest.lstrip("v").split(".")]
        return latest_parts > c
    except Exception:
        return False
