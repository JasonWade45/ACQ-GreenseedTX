# PyInstaller build for ACQ.exe — a window, no console, everything inside.
#
# Built by `scripts/build_windows.py`, which also compiles the interface first and
# passes the paths through ACQ_BUILD_ROOT. Run it through that script, not directly.

import os
import sys
from pathlib import Path

BUILD_ROOT = Path(os.environ.get("ACQ_BUILD_ROOT", Path(SPECPATH).resolve().parents[1])).resolve()
ICON = BUILD_ROOT / "desktop" / "acq.ico"
VERSION_FILE = BUILD_ROOT / "build" / "version_info.txt"

datas = [
    (str(BUILD_ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(BUILD_ROOT / "backend" / "migrations"), "backend/migrations"),
    (str(BUILD_ROOT / "backend" / "fixtures"), "backend/fixtures"),
    (str(BUILD_ROOT / "examples"), "examples"),
    (str(BUILD_ROOT / "alembic.ini"), "alembic.ini"),
]

# Modules the app imports lazily (inside functions), so PyInstaller cannot see them.
hiddenimports = [
    "app.main",
    "app.routes_unified",
    "app.intelligence_routes",
    "alembic",
    "alembic.config",
    "alembic.script",
    "alembic.runtime.migration",
    "sqlalchemy.dialects.sqlite",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "apscheduler.schedulers.background",
    "apscheduler.triggers.cron",
    "openpyxl",
    "phonenumbers",
    "segno",
    "multipart",
]

excludes = [
    "tkinter.test",
    "test",
    "tests",
    "pytest",
    "ruff",
    "pygments",
    "playwright",
    "numpy",
    "pandas",
    "matplotlib",
    "IPython",
]

a = Analysis(
    [str(BUILD_ROOT / "desktop" / "acq_app.py")],
    pathex=[str(BUILD_ROOT / "backend"), str(BUILD_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# Migrations are read as files; keep them out of the archive so Alembic sees real paths.
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ACQ",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ICON) if ICON.is_file() else None,
    version=str(VERSION_FILE) if VERSION_FILE.is_file() else None,
)
