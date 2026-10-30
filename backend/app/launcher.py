"""Shared runtime for every way of starting the app on a computer.

Both entry points use this module:

* ``scripts/acq_desktop.py`` — the window-with-a-console launcher used by
  ``START-ACQ.cmd`` and by anyone running from source;
* ``desktop/acq_app.py`` — the same thing packaged as ``ACQ.exe`` with no console,
  a native window and a single-instance check.

Only the standard library is imported here, so a frozen build carries no surprises.
"""

from __future__ import annotations

import os
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from io import StringIO
from pathlib import Path

MIN_PASSWORD = 12
ENV_KEYS = ("APP_ACCESS_PASSWORD", "SESSION_SECRET")


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
    body = ["# Written by the desktop launcher. Never share or commit this file.", ""]
    body += [f"{key}={existing[key]}" for key in order]
    path.parent.mkdir(parents=True, exist_ok=True)
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
    buffer = StringIO()
    segno.make(url, error="m").terminal(out=buffer, compact=True)
    return [line for line in buffer.getvalue().splitlines() if line.strip()]


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
    if password and created:
        lines.append("  Password (save it): " + password)
    elif password:
        # Never print a stored secret on every start: a shared screen or a screen
        # recording would leak it. The explicit flag exists for when you need it.
        lines.append("  Password         : saved in .env — pass --show-password to print it")
    else:
        lines.append("  Password         : not set — this computer only")
    lines += ["", "  Keep this window open. Ctrl+C stops the app.", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- one copy only


class InstanceLock:
    """A lock file that proves this program is the only copy running.

    Two copies would fight over one SQLite file and one port, so the second one
    opens the window that already exists instead of starting a second server.

    Platform note: a Windows byte-region lock denies every other handle access
    to the file itself, including reading it -- and the pid inside the lock file
    is exactly what a person or the support screen may want to read. So on
    Windows the hold lives on a sidecar ``<name>.lock`` stays readable, and the
    lock lives on ``<name>.lock.hold``. POSIX flocks keep the pid file readable,
    so there the lock stays on the same file.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._handle = None
        self._hold = None

    def _hold_path(self) -> Path:
        suffix = self.path.suffix
        return self.path.with_suffix(suffix + ".hold")

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            hold = open(self._hold_path(), "a+", encoding="utf-8")
            try:
                import msvcrt

                hold.seek(0)
                msvcrt.locking(hold.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                hold.close()
                return False
            pid = open(self.path, "w", encoding="utf-8")
            try:
                pid.write(f"{os.getpid()}\n")
                pid.flush()
            except OSError:
                hold.close()
                pid.close()
                return False
            self._hold = hold
            self._handle = pid
            return True
        handle = open(self.path, "a+", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        self._handle = handle
        return True

    def release(self) -> None:
        handle, self._handle = self._handle, None
        hold, self._hold = self._hold, None
        if hold is not None:
            try:
                import msvcrt

                hold.seek(0)
                msvcrt.locking(hold.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            finally:
                hold.close()
        if handle is None:
            return
        try:
            if os.name != "nt":
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()

    def __enter__(self) -> "InstanceLock":
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


# --------------------------------------------------------------------------- server


def server_config(host: str, port: int, log_level: str = "info"):
    """A uvicorn config that never installs console signal handlers."""
    import uvicorn

    return uvicorn.Config(
        "app.main:app",
        host=host,
        port=port,
        workers=1,
        access_log=False,
        log_level=log_level,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


def run_in_thread(host: str, port: int, log_level: str = "info"):
    """Start the server on a background thread; returns (server, thread)."""
    import uvicorn

    server = uvicorn.Server(server_config(host, port, log_level))
    # uvicorn handles being started off the main thread: it skips signal handlers.
    thread = threading.Thread(target=server.run, name="acq-server", daemon=True)
    thread.start()
    return server, thread


def stop(server, thread: threading.Thread | None = None, timeout: float = 20.0) -> None:
    if server is not None:
        server.should_exit = True
    if thread is not None:
        thread.join(timeout)


def python_executable_hint() -> str:
    """What the user would have to type if Python were missing. Only used in messages."""
    return sys.executable or "python"
