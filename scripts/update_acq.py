"""Copy a newer release over an existing installation without touching data.

Run it from the NEW release folder (never from the folder being updated):

    Windows      UPDATE-ACQ.cmd
    macOS/Linux  ./update-acq.sh
    Manual       python scripts/update_acq.py --target "/path/to/old/install"

What it guarantees:

* the live database is backed up and validated before a single file changes;
* ``data/``, ``.env``, ``.env.secrets``, ``.venv`` and ``backups/`` are never copied over;
* every overwritten file is kept under ``backups/code-before-<stamp>/``;
* a failure after copying puts the old files back and deletes the new ones;
* the updated copy is started once on a spare port and must answer ``/api/health``.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

APP_NAME = "AcquisitionsAssistant"
MIN_PYTHON = (3, 11)

ROOT = Path(__file__).resolve().parents[1]

# Anything a live installation owns stays behind. A release archive never ships these.
PRESERVED_DIRS = {"data", ".venv", "backups", "node_modules", "__pycache__", ".git", "release"}
PRESERVED_NAMES = {".env", ".env.secrets", ".preview-password"}
PRESERVED_SUFFIXES = (".db", ".db-wal", ".db-shm", ".db-journal", ".log", ".pyc")
IGNORED_DIRS = {
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "node_modules",
    "release",
}

# Files the updater itself must find on both sides to prove it is looking at real installs.
REQUIRED_SOURCE = ("backend/app/version.py", "scripts/manage.py", "frontend/dist/index.html")
REQUIRED_TARGET = ("scripts/manage.py", "backend/app")


class UpdateError(RuntimeError):
    """A condition the user can fix. Printed without a traceback."""


# ---------------------------------------------------------------------------- version


def read_version(root: Path) -> str:
    source = Path(root) / "backend" / "app" / "version.py"
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise UpdateError(f"Could not read the version from {source}: {exc}") from exc
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise UpdateError(f"{source} does not declare APP_VERSION")
    return match.group(1)


def version_tuple(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value)
    return tuple(int(part) for part in parts) if parts else (0,)


# ---------------------------------------------------------------------------- registry
# The first update has to be told where the old folder is. Every successful update
# records the location, so the next one only needs a double-click.


def registry_file() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / APP_NAME / "install.txt"


def record_install(root: Path) -> Path | None:
    """Best effort: a read-only home directory must never fail an update."""
    path = registry_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(Path(root).resolve()), encoding="utf-8")
    except OSError:
        return None
    return path


def recorded_install() -> Path | None:
    path = registry_file()
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not value:
        return None
    candidate = Path(value)
    return candidate if candidate.is_dir() else None


# ---------------------------------------------------------------------------- inspection


def release_files(source: Path) -> list[str]:
    """Every path the release ships, relative to its root, as POSIX strings."""
    files: list[str] = []
    for current, dirs, names in os.walk(source):
        dirs[:] = [name for name in dirs if name not in IGNORED_DIRS]
        for name in names:
            path = Path(current) / name
            relative = path.relative_to(source)
            if relative.parts and relative.parts[0] in PRESERVED_DIRS:
                continue
            if name in PRESERVED_NAMES or name.endswith(PRESERVED_SUFFIXES):
                continue
            files.append(relative.as_posix())
    return sorted(files)


def check_source(source: Path) -> None:
    for relative in REQUIRED_SOURCE:
        if not (source / relative).exists():
            raise UpdateError(
                f"{source} is not a release folder: {relative} is missing.\n"
                "Extract the whole ZIP first and run the updater from inside it."
            )


def check_target(target: Path) -> None:
    if not target.is_dir():
        raise UpdateError(f"The old installation folder does not exist: {target}")
    for relative in REQUIRED_TARGET:
        if not (target / relative).exists():
            raise UpdateError(
                f"{target} is not an Acquisitions Assistant installation: {relative} is missing.\n"
                "Pick the folder that contains START-ACQ.cmd, backend, scripts and data."
            )


def venv_python(target: Path) -> Path:
    candidates = [target / ".venv" / "Scripts" / "python.exe", target / ".venv" / "bin" / "python"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise UpdateError(
        "The old installation has no ready Python environment (.venv).\n"
        "Start it once with START-ACQ.cmd so the environment is created, then run this update again."
    )


def port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def free_port(preferred: int = 0) -> int:
    for candidate in ([preferred] if preferred else []) + [0]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
                return probe.getsockname()[1]
            except OSError:
                continue
    raise UpdateError("No free local port is available for the verification start")


# ---------------------------------------------------------------------------- copying


def snapshot_target(target: Path, relative_files: list[str], stamp: str) -> Path:
    """Keep a copy of every file about to be replaced, so nothing is lost."""
    destination = target / "backups" / f"code-before-{stamp}"
    for relative in relative_files:
        existing = target / relative
        if existing.is_file():
            kept = destination / relative
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(existing, kept)
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def copy_release(source: Path, target: Path, relative_files: list[str]) -> tuple[list[str], list[str]]:
    """Return (replaced, created) so a rollback knows exactly what to undo."""
    replaced: list[str] = []
    created: list[str] = []
    for relative in relative_files:
        origin = source / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            replaced.append(relative)
        else:
            created.append(relative)
        shutil.copy2(origin, destination)
    return replaced, created


def rollback(target: Path, snapshot: Path, created: list[str]) -> list[str]:
    """Put the previous files back and remove the ones this run introduced."""
    restored = 0
    for kept in sorted(snapshot.rglob("*")):
        if not kept.is_file():
            continue
        relative = kept.relative_to(snapshot)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(kept, destination)
        restored += 1
    removed = 0
    touched_dirs: set[Path] = set()
    for relative in created:
        destination = target / relative
        if destination.is_file():
            destination.unlink()
            removed += 1
            touched_dirs.add(destination.parent)
    # Only directories this update created can now be empty; prune from the deepest.
    for directory in sorted(touched_dirs, key=lambda item: len(item.parts), reverse=True):
        while directory != target and directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
            directory = directory.parent
    return [f"restored {restored} file(s)", f"removed {removed} new file(s)"]


# ---------------------------------------------------------------------------- subprocess steps


def run(step: str, command: list[str], cwd: Path, timeout: float = 1800) -> str:
    print(f"  -> {step}", flush=True)
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise UpdateError(f"{step} did not finish within {int(timeout)} seconds") from exc
    except OSError as exc:
        raise UpdateError(f"{step} could not start: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        tail = "\n".join(detail[-8:]) if detail else "no output"
        raise UpdateError(f"{step} failed (exit {completed.returncode}):\n{tail}")
    return completed.stdout


def backup_database(target: Path, python: Path, version: str) -> Path:
    # Local midnight keeps the name readable next to the app's own backups.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    destination = target / "backups" / f"before-update-{version}-{stamp}.db"
    if not (target / "data").is_dir():
        # Nothing has ever run here; there is no database to protect yet.
        print("  -> no data folder yet; nothing to back up")
        return Path()
    run(
        "backup the live database",
        [str(python), "scripts/manage.py", "backup", "--output", str(destination)],
        cwd=target,
    )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise UpdateError("The database backup was not produced; nothing was changed")
    print(f"  -> backup: {destination}")
    return destination


def install_dependencies(target: Path, python: Path) -> None:
    run(
        "install the locked dependencies",
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-q",
         "-r", "backend/requirements-lock.txt"],
        cwd=target,
        timeout=3600,
    )


def migrate(target: Path, python: Path) -> None:
    run("upgrade the database schema", [str(python), "scripts/manage.py", "migrate"], cwd=target)


def health_check(target: Path, python: Path, port: int, timeout: float = 120.0) -> None:
    print(f"  -> verify the updated app answers on port {port}", flush=True)
    process = subprocess.Popen(
        [str(python), "scripts/run.py", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(target),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + timeout
    target_url = f"http://127.0.0.1:{port}/api/health"
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = ""
                if process.stdout is not None:
                    output = process.stdout.read() or ""
                tail = "\n".join(output.strip().splitlines()[-8:])
                raise UpdateError(f"The updated app stopped before answering:\n{tail or 'no output'}")
            try:
                with urllib.request.urlopen(target_url, timeout=3) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, OSError, TimeoutError):
                time.sleep(0.4)
        raise UpdateError(f"The updated app did not answer {target_url} within {int(timeout)} seconds")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()


# ---------------------------------------------------------------------------- relaunch


def launcher_command(target: Path) -> list[str]:
    """Windows opens its own console; elsewhere the server belongs to the user's terminal."""
    return ["cmd", "/c", "start", "", str(target / "START-ACQ.cmd")]


def launch_app(target: Path) -> None:
    if os.name != "nt":
        # start-acq.sh runs the server in the foreground. Starting it hidden here would
        # leave a process nobody can see or stop, so the user is told what to run instead.
        print(f"\nStart it with: cd {target} && ./start-acq.sh")
        return
    print("\nStarting the updated app in a new window...")
    try:
        # Fully detached, or the updater would wait for a console that never closes.
        subprocess.Popen(
            launcher_command(target),
            cwd=str(target),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        print(f"Could not start it automatically ({exc}).")
        print(f"Open it yourself: {target / 'START-ACQ.cmd'}")


# ---------------------------------------------------------------------------- orchestration


def plan(source: Path, target: Path) -> dict:
    check_source(source)
    check_target(target)
    if source.resolve() == target.resolve():
        raise UpdateError(
            "The new and the old folder are the same. Extract the new ZIP into a separate folder first."
        )
    files = release_files(source)
    return {
        "source": source.resolve(),
        "target": target.resolve(),
        "from_version": read_version(target),
        "to_version": read_version(source),
        "files": files,
    }


def update(
    source: Path,
    target: Path,
    port: int = 8010,
    *,
    force: bool = False,
    verify: bool = True,
) -> dict:
    steps = plan(source, target)
    print(f"\nUpdating {steps['target']}", flush=True)
    print(f"  installed : {steps['from_version']}", flush=True)
    print(f"  release   : {steps['to_version']}", flush=True)
    print(f"  files     : {len(steps['files'])}", flush=True)

    if version_tuple(steps["to_version"]) <= version_tuple(steps["from_version"]) and not force:
        print("\nAlready up to date. Nothing changed. Use --force to copy the same release again.")
        return {"status": "up-to-date", **steps}

    if not port_is_free(port):
        raise UpdateError(
            f"Port {port} is in use, so the app is still running.\n"
            "Close the running window (or press Ctrl+C in it) and run the update again."
        )
    python = venv_python(target)
    print(f"  python    : {python}", flush=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_database(target, python, steps["to_version"])
    snapshot = snapshot_target(target, steps["files"], stamp)
    print(f"  -> old code kept in {snapshot}")

    replaced: list[str] = []
    created: list[str] = []
    try:
        replaced, created = copy_release(source, target, steps["files"])
        print(f"  -> {len(replaced)} file(s) replaced, {len(created)} added")
        install_dependencies(target, python)
        migrate(target, python)
        if verify:
            health_check(target, python, free_port())
    except (UpdateError, OSError, shutil.Error) as exc:
        print("\nSomething failed. Putting the previous version back...", flush=True)
        for line in rollback(target, snapshot, created):
            print(f"  -> {line}")
        raise UpdateError(f"Update aborted, previous version restored.\n\n{exc}") from exc

    record_install(target)
    print("\nUpdate finished. Your data, .env and .venv were not touched.")
    print(f"  backup  : {target / 'backups'}")
    print(f"  code    : {snapshot}")
    return {"status": "updated", "replaced": len(replaced), "created": len(created), **steps}


def ask_target(interactive: bool) -> Path:
    remembered = recorded_install()
    if remembered is not None:
        print(f"Using the remembered installation: {remembered}")
        return remembered
    if not interactive:
        raise UpdateError("Pass --target <old installation folder> when nobody can answer a prompt")
    value = input("Path of the OLD installation folder (contains START-ACQ.cmd and data): ").strip().strip('"')
    if not value:
        raise UpdateError("No folder given. Nothing changed.")
    return Path(value).expanduser()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Update an existing Acquisitions Assistant installation from this release folder",
        epilog="Your data, .env, .venv and backups stay exactly where they are.",
    )
    parser.add_argument("--target", help="The folder of the installation to update")
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT", "8010")),
                        help="Port the app uses; the update refuses to run while it is busy")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change and exit")
    parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation")
    parser.add_argument("--force", action="store_true", help="Copy even when the version is not newer")
    parser.add_argument("--no-verify", action="store_true", help="Skip the temporary start on a spare port")
    parser.add_argument("--start", action="store_true", help="Open the updated app when the update succeeds")
    args = parser.parse_args(argv)

    try:
        target = Path(args.target).expanduser() if args.target else ask_target(not args.yes)
        steps = plan(ROOT, target)
        if args.dry_run:
            print(f"Source : {steps['source']} ({steps['to_version']})")
            print(f"Target : {steps['target']} ({steps['from_version']})")
            print(f"Files  : {len(steps['files'])}")
            print("Preserved: data/, .env, .env.secrets, .venv/, backups/")
            print("Dry run only. Nothing was changed.")
            return 0
        if not args.yes:
            print(f"\nThis replaces {len(steps['files'])} program file(s) in {steps['target']}.")
            print("A database backup and a copy of the replaced files are made first.")
            if input("Type UPDATE to continue: ").strip() != "UPDATE":
                print("Cancelled. Nothing changed.")
                return 1
        result = update(
            ROOT,
            target,
            port=args.port,
            force=args.force,
            verify=not args.no_verify,
        )
        if result["status"] == "updated" and args.start:
            launch_app(result["target"])
        return 0
    except UpdateError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled. Nothing changed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
