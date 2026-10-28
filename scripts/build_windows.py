"""Build the Windows program: ACQ.exe, ready to install. Run on Windows.

    python scripts/build_windows.py

It compiles the interface, embeds the version and the icon, and produces
``dist/ACQ.exe``. Two optional steps follow automatically when their tools exist:

* ``ISCC.exe`` (Inno Setup) builds ``dist/ACQ-Setup-<version>.exe``;
* nothing is signed, so Windows SmartScreen shows one "More info → Run anyway"
  prompt on the first run of an unsigned download.

Free of charge throughout: PyInstaller and Inno Setup are both free, and the same
build runs on a GitHub-hosted Windows runner with no local tooling at all.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def version() -> str:
    namespace: dict[str, str] = {}
    exec((ROOT / "backend" / "app" / "version.py").read_text(), namespace)  # noqa: S102 - our own file
    return namespace["APP_VERSION"]


def run(command: list[str], **kwargs) -> None:
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run(command, check=True, cwd=ROOT, **kwargs)


def build_interface() -> None:
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        raise SystemExit("npm is required to compile the interface. Install Node.js, or use the CI build.")
    frontend = ROOT / "frontend"
    if not (frontend / "node_modules").is_dir():
        run([npm, "ci", "--no-audit", "--no-fund"], cwd=frontend)
    run([npm, "run", "build"], cwd=frontend)
    if not (frontend / "dist" / "index.html").is_file():
        raise SystemExit("The interface build produced no index.html.")


def write_version_info() -> Path:
    """Windows file properties: ProductName, version, company. Shown in Explorer."""
    app_version = version()
    numbers = (app_version.split(".") + ["0", "0", "0"])[:4]
    parts = ", ".join(str(int(part)) for part in numbers)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({parts}), prodvers=({parts}), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'GreenSeedTX LLC'),
      StringStruct('FileDescription', 'Acquisitions Assistant'),
      StringStruct('FileVersion', '{app_version}'),
      StringStruct('InternalName', 'ACQ'),
      StringStruct('LegalCopyright', 'GreenSeedTX LLC'),
      StringStruct('OriginalFilename', 'ACQ.exe'),
      StringStruct('ProductName', 'Acquisitions Assistant'),
      StringStruct('ProductVersion', '{app_version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    BUILD.mkdir(parents=True, exist_ok=True)
    path = BUILD / "version_info.txt"
    path.write_text(text, encoding="utf-8")
    return path


def build_exe() -> Path:
    write_version_info()
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD / "pyinstaller"),
            str(ROOT / "desktop" / "acq.spec"),
        ],
        env={**os.environ, "ACQ_BUILD_ROOT": str(ROOT)},
    )
    exe = DIST / "ACQ.exe"
    if not exe.is_file():
        raise SystemExit("PyInstaller finished but ACQ.exe is missing.")
    return exe


def build_installer(exe: Path) -> Path | None:
    """Inno Setup, when installed. Produces the double-click installer."""
    candidates = [
        shutil.which("ISCC"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    iscc = next((c for c in candidates if c and Path(c).is_file()), None)
    if not iscc:
        print("Inno Setup (ISCC.exe) not found — ACQ.exe was built, the installer was skipped.")
        return None
    script = ROOT / "desktop" / "installer.iss"
    run([iscc, f"/DAppVersion={version()}", f"/DSourceExe={exe}", str(script)])
    installer = DIST / f"ACQ-Setup-{version()}.exe"
    return installer if installer.is_file() else None


def main() -> int:
    app_version = version()
    print(f"Building Acquisitions Assistant {app_version} for this computer")
    build_interface()
    exe = build_exe()
    print(f"Program : {exe}  ({exe.stat().st_size / 1048576:.1f} MB)")
    installer = build_installer(exe)
    if installer:
        print(f"Installer: {installer}  ({installer.stat().st_size / 1048576:.1f} MB)")
    print("Both files are unsigned, so the first run asks once for 'More info -> Run anyway'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
