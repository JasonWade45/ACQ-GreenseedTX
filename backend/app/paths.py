"""Where the program keeps its read-only files and where it keeps yours.

Two different questions, answered separately:

* **Resources** are the files that ship with a build: the compiled interface, the
  database migrations, the fictional fixtures. Inside a packaged program they sit
  in a read-only bundle and are replaced wholesale on every update.
* **Data** is yours: ``acquisitions.db``, the password, backups. It must survive an
  update, an uninstall and a reinstall, so it never lives inside the bundle.

Running from source they are the same folder, which keeps every existing script and
test working unchanged.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_FOLDER_NAME = "AcquisitionsAssistant"
PORTABLE_FOLDER_NAME = "ACQ-data"


def is_frozen() -> bool:
    """True inside a PyInstaller executable, false when running from source."""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Read-only files that ship with this build."""
    if is_frozen():
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            return Path(bundle)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def data_root() -> Path:
    """Writable files that belong to the person using the program.

    ``ACQ_DATA_DIR`` wins, so a portable copy or a test can point somewhere else.
    ``ACQ_PORTABLE=1`` puts everything next to the executable on a USB stick.

    Running from source keeps the old behaviour — the program folder itself — so a
    folder extracted from an earlier ZIP still opens with its existing database.
    Only the installed program separates the two.
    """
    override = os.environ.get("ACQ_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.environ.get("ACQ_PORTABLE", "").strip() == "1" and is_frozen():
        return Path(sys.executable).resolve().parent / PORTABLE_FOLDER_NAME
    if not is_frozen():
        return resource_root()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return (Path(base) / APP_FOLDER_NAME).resolve()
        return (Path.home() / "AppData" / "Local" / APP_FOLDER_NAME).resolve()
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / APP_FOLDER_NAME).resolve()
    xdg = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return (Path(xdg).expanduser() / APP_FOLDER_NAME).resolve()


def data_file(*parts: str) -> Path:
    return data_root().joinpath(*parts)


def resource_file(*parts: str) -> Path:
    return resource_root().joinpath(*parts)


def browser_ui_ready() -> bool:
    """The compiled interface is present, so the server has something to serve."""
    return (resource_root() / "frontend" / "dist" / "index.html").is_file()


def adopt_legacy_data(root: Path | None = None) -> bool:
    """Copy an existing database out of an old program folder, once, without deleting it.

    People upgrading from a ZIP built before the split kept everything in the program
    folder. Installing over that must not look like "all my sellers are gone", so the
    first run copies the database and the password across and leaves the originals alone.
    """
    root = (root or data_root()).resolve()
    source = resource_root()
    if root == source:
        return False
    marker = root / ".adopted-from-program-folder"
    if marker.exists():
        return False
    database = source / "data" / "acquisitions.db"
    environment = source / ".env"
    copied: list[str] = []
    if database.is_file() and not (root / "data" / "acquisitions.db").exists():
        (root / "data").mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(database) + suffix)
            if candidate.is_file():
                shutil.copy2(candidate, Path(str(root / "data" / "acquisitions.db") + suffix))
        copied.append("database")
    if environment.is_file() and not (root / ".env").exists():
        shutil.copy2(environment, root / ".env")
        copied.append("password and settings")
    if copied:
        marker.write_text("Copied from " + str(source) + " on first run.\n", encoding="utf-8")
        return True
    return False


def ensure_data_dirs(root: Path | None = None) -> Path:
    """Create the folders the program writes into. Safe to call repeatedly."""
    root = (root or data_root()).resolve()
    for relative in ("", "data", "data/backups", "logs"):
        (root / relative if relative else root).mkdir(parents=True, exist_ok=True)
    return root
