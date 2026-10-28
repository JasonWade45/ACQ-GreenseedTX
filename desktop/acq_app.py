"""ACQ.exe — the installed program. No console, no PowerShell, no browser tab.

What it does, in order:

1. refuses to start twice (a second copy focuses the window that already exists);
2. generates and stores the workspace password on the first run;
3. starts the server on a background thread;
4. opens a real window: a native WebView2 window when ``pywebview`` is present,
   otherwise a small Tk window with the address, the phone address and buttons;
5. stops the server and releases the lock on close.

Everything it needs is inside the executable: ``backend/``, the compiled interface,
the migrations and the fictional fixtures. Your database, password and backups live
outside it in the folder reported by ``--data-dir``.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import webbrowser
from pathlib import Path


class _NoConsole:
    """Stands in for a missing stdout/stderr in the windowed build.

    ``ACQ.exe`` has no console, so PyInstaller hands the program ``sys.stdout = None``
    and ``sys.stderr = None``. A single ``print()`` or a logging handler pointed at
    them would raise ``AttributeError: 'NoneType' object has no attribute 'write'``
    and kill the program before the window appears.
    """

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        raise OSError("this build has no console")


def ensure_streams() -> None:
    """Give the program something to write to when it has no console."""
    if sys.stdout is None:
        sys.stdout = _NoConsole()  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = _NoConsole()  # type: ignore[assignment]


ensure_streams()

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.launcher import (  # noqa: E402
    InstanceLock,
    ensure_credentials,
    lan_addresses,
    lan_urls,
    local_url,
    port_is_free,
    qr_lines,
    run_in_thread,
    stop,
    wait_until_healthy,
)
from app.paths import adopt_legacy_data, browser_ui_ready, data_root, ensure_data_dirs  # noqa: E402

APP_TITLE = "Acquisitions Assistant"


# --------------------------------------------------------------------------- window


def native_window(url: str, on_close) -> bool:
    """Embed the app in a WebView2 window. Returns False if that is not possible.

    ``on_close`` runs only after a window really opened and the user closed it, so a
    failed attempt leaves the fallback free to open a different window.
    """
    try:
        import webview  # pywebview
    except Exception:
        return False
    try:
        webview.create_window(APP_TITLE, url, width=1280, height=860, min_size=(900, 640))
        webview.start(private_mode=False)
    except Exception:
        return False
    on_close()
    return True


def tk_window(url: str, password: str, phone_urls: list[str], on_close) -> None:
    """A small, dependency-free control window. Always available on Windows."""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("620x430")
    root.minsize(560, 380)

    header = ttk.Frame(root, padding=16)
    header.pack(fill="x")
    ttk.Label(header, text=APP_TITLE, font=("Segoe UI", 16, "bold")).pack(anchor="w")
    ttk.Label(header, text="Running on this computer. Close this window to stop it.").pack(anchor="w", pady=(2, 0))

    body = ttk.Frame(root, padding=(16, 0, 16, 16))
    body.pack(fill="both", expand=True)

    ttk.Label(body, text="Open on this computer", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(10, 0))
    local_row = ttk.Frame(body)
    local_row.pack(fill="x", pady=(2, 10))
    local_entry = ttk.Entry(local_row, width=44)
    local_entry.insert(0, url)
    local_entry.configure(state="readonly")
    local_entry.pack(side="left", fill="x", expand=True)

    def open_browser() -> None:
        webbrowser.open(url)

    ttk.Button(local_row, text="Open", command=open_browser).pack(side="left", padx=(8, 0))

    if phone_urls:
        ttk.Label(body, text="Open from your phone (same Wi-Fi)", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(4, 0))
        phone_entry = ttk.Entry(body, width=44)
        phone_entry.insert(0, phone_urls[0])
        phone_entry.configure(state="readonly")
        phone_entry.pack(fill="x", pady=(2, 6))
    else:
        ttk.Label(body, text="No network address found — this computer only.").pack(anchor="w", pady=(4, 6))

    if password:
        ttk.Label(body, text="Password for other devices", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(4, 0))
        password_row = ttk.Frame(body)
        password_row.pack(fill="x", pady=(2, 6))
        shown = tk.StringVar(value="•" * len(password))
        password_entry = ttk.Entry(password_row, textvariable=shown, width=32, state="readonly")
        password_entry.pack(side="left")

        def toggle() -> None:
            shown.set(password if shown.get().startswith("•") else "•" * len(password))

        ttk.Button(password_row, text="Show", command=toggle).pack(side="left", padx=(8, 0))

        def copy_password() -> None:
            root.clipboard_clear()
            root.clipboard_append(password)

        ttk.Button(password_row, text="Copy", command=copy_password).pack(side="left", padx=(8, 0))

    actions = ttk.Frame(body)
    actions.pack(fill="x", pady=(12, 0))

    def show_qr() -> None:
        target = phone_urls[0] if phone_urls else url
        lines = qr_lines(target)
        window = tk.Toplevel(root)
        window.title("Scan with your phone camera")
        text = "\n".join(lines) if lines else "QR codes need the 'segno' package."
        ttk.Label(window, text=text, font=("Consolas", 7), justify="left").pack(padx=16, pady=16)

    ttk.Button(actions, text="Open in browser", command=open_browser).pack(side="left")
    ttk.Button(actions, text="Scan from phone", command=show_qr).pack(side="left", padx=(8, 0))

    def open_folder() -> None:
        folder = data_root()
        try:
            if os.name == "nt":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.system(f'open "{folder}"')
            else:
                webbrowser.open(folder.as_uri())
        except OSError:
            pass

    ttk.Button(actions, text="Open data folder", command=open_folder).pack(side="left", padx=(8, 0))
    ttk.Button(actions, text="Stop", command=root.destroy).pack(side="right")

    footer = ttk.Label(body, text=f"Your data: {data_root()}", foreground="#666")
    footer.pack(anchor="w", side="bottom", pady=(12, 0))

    try:
        root.mainloop()
    finally:
        on_close()


def open_window(url: str, password: str, phone_urls: list[str], on_close) -> None:
    """Prefer a real embedded window; fall back to a control window, then a browser."""
    if os.environ.get("ACQ_NO_WINDOW") == "1":
        on_close()
        return
    if native_window(url, on_close):
        return
    try:
        tk_window(url, password, phone_urls, on_close)
        return
    except Exception:
        pass
    webbrowser.open(url)
    on_close()


# --------------------------------------------------------------------------- main


def _already_running(port: int) -> None:
    """A second copy opens what is already there instead of starting another server."""
    if wait_until_healthy(port, timeout=3):
        webbrowser.open(local_url(port))
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquisitions Assistant — local desktop app")
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT", "8010")))
    parser.add_argument("--local-only", action="store_true", help="This computer only; no password and no LAN")
    parser.add_argument("--no-window", action="store_true", help="Start the server and wait (for scripts)")
    parser.add_argument("--check", action="store_true", help="Print the plan, start nothing, exit")
    parser.add_argument("--data-dir", action="store_true", help="Print the data folder and exit")
    args = parser.parse_args(argv)

    if args.data_dir:
        print(data_root())
        return 0

    ensure_data_dirs()
    adopt_legacy_data()
    env_file = data_root() / ".env"

    if not browser_ui_ready():
        print("The built interface is missing from this installation; reinstall the app.", file=sys.stderr)
        return 2

    lan = not args.local_only
    password, created = ensure_credentials(env_file, required=lan) if not args.check else ("", False)
    addresses = lan_addresses() if lan else []
    if args.check:
        print(f"data   : {data_root()}")
        print(f"url    : {local_url(args.port)}")
        print(f"phone  : {lan_urls(args.port, addresses) or 'none found'}")
        print(f"port   : {'free' if port_is_free(args.port) else 'IN USE'}")
        return 0

    lock = InstanceLock(data_root() / "acq.lock")
    if not lock.acquire():
        _already_running(args.port)
        return 0

    server = None
    thread = None
    try:
        os.environ["APP_HOST"] = "0.0.0.0" if lan else "127.0.0.1"
        os.environ["APP_PORT"] = str(args.port)
        if password:
            os.environ["APP_ACCESS_PASSWORD"] = password

        try:
            server, thread = run_in_thread(os.environ["APP_HOST"], args.port)
        except Exception as error:  # port taken by something else, permissions, ...
            print(f"Could not start the local server: {error}", file=sys.stderr)
            return 3

        if not wait_until_healthy(args.port, timeout=90):
            print("The local server did not answer. Nothing was changed.", file=sys.stderr)
            stop(server, thread)
            return 4

        if args.no_window:
            try:
                while thread and thread.is_alive():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
            return 0

        open_window(local_url(args.port), password, lan_urls(args.port, addresses), lambda: None)
        return 0
    finally:
        stop(server, thread)
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
