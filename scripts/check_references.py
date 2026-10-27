"""Fail the build when documentation points at files that no longer exist.

This exists because archived Windows helpers were moved to ``legacy/windows`` and
several guides kept telling people to double-click files at the project root.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Release notes and verification logs are historical records; they describe what shipped
# at that time and are deliberately not rewritten.
HISTORICAL = re.compile(r"docs/(RELEASE_[^/]*|VERIFICATION\.md|upgrade-check\.json)$")

# Helpers that used to live at the repository root and now live under legacy/windows/.
MOVED = {
    "START-WINDOWS.cmd": "legacy/windows/START-WINDOWS.cmd",
    "START-ONLINE-WINDOWS.cmd": "legacy/windows/START-ONLINE-WINDOWS.cmd",
    "SETUP-TUNNEL-WINDOWS.cmd": "legacy/windows/SETUP-TUNNEL-WINDOWS.cmd",
    "UPDATE-WINDOWS.cmd": "legacy/windows/UPDATE-WINDOWS.cmd",
    "UPDATE-WINDOWS.ps1": "legacy/windows/UPDATE-WINDOWS.ps1",
    "MERGE-WORKSPACES.cmd": "legacy/windows/MERGE-WORKSPACES.cmd",
    "MERGE-WORKSPACES.ps1": "legacy/windows/MERGE-WORKSPACES.ps1",
    "UPLOAD-DATABASES.cmd": "legacy/windows/UPLOAD-DATABASES.cmd",
    "UPLOAD-DATABASES.ps1": "legacy/windows/UPLOAD-DATABASES.ps1",
    "RESTORE-DATABASES.cmd": "legacy/windows/RESTORE-DATABASES.cmd",
    "RESTORE-DATABASES.ps1": "legacy/windows/RESTORE-DATABASES.ps1",
    "START_HERE_WINDOWS_AR.md": "legacy/windows/START_HERE_WINDOWS_AR.md",
    "scripts/start_windows.ps1": "legacy/windows/scripts/start_windows.ps1",
    "scripts/start_online_windows.ps1": "legacy/windows/scripts/start_online_windows.ps1",
    "scripts/setup_tunnel_windows.ps1": "legacy/windows/scripts/setup_tunnel_windows.ps1",
    "scripts/setup.ps1": "legacy/windows/scripts/setup.ps1",
}


def markdown_files() -> list[Path]:
    files = sorted(ROOT.glob("*.md"))
    files += sorted((ROOT / "docs").glob("*.md"))
    files += sorted((ROOT / "legacy").rglob("*.md"))
    return files


def broken_links(paths: list[Path] | None = None) -> list[str]:
    problems: list[str] = []
    for document in paths or markdown_files():
        text = document.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if not (document.parent / target).resolve().exists():
                problems.append(f"{document.relative_to(ROOT).as_posix()}: broken link -> {target}")
    return problems


# A sentence that explains where a helper went is not a stale instruction.
EXPLANATORY = re.compile(
    r"legacy[/\\]windows|moved|replaced|archived|no longer|previously|instead of|relocated"
    r"|نُقلت|نقلت|مؤرشف|مؤرشفة|غير مدعوم|بدلًا|بدلا",
    re.IGNORECASE,
)


def stale_references(paths: list[Path] | None = None) -> list[str]:
    """A moved helper presented as a live instruction in an active document."""
    problems: list[str] = []
    for document in paths or markdown_files():
        relative = document.relative_to(ROOT).as_posix()
        if HISTORICAL.search(relative) or relative.startswith("legacy/"):
            continue
        for number, line in enumerate(document.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if EXPLANATORY.search(line):
                continue
            for old, new in MOVED.items():
                if old.startswith("scripts/"):
                    continue
                if re.search(r"(?<![\w./\\-])" + re.escape(old), line):
                    problems.append(f"{relative}:{number}: mentions {old}, which moved to {new}")
    return problems


def missing_packaged_files() -> list[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from package_release import public_files  # noqa: PLC0415

    problems = []
    for path in public_files():
        if not path.is_file():
            problems.append(f"packaging lists a missing file: {path}")
    return problems


def main() -> int:
    problems = broken_links() + stale_references() + missing_packaged_files()
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{len(problems)} documentation problem(s) found", file=sys.stderr)
        return 1
    print(f"References OK: {len(markdown_files())} documents, no broken links or stale paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
