# Acquisitions Assistant — 1.3.0 (a program you install, not a folder you open)

**Released 2026-10-28 (Africa/Cairo).** Until now, using this meant extracting a ZIP, keeping a
black console window open, and having Python installed. That is not a program. 1.3.0 turns it into
one: `ACQ-Setup-1.3.0.exe`, double-click, Next, Install, Finish — and an icon on the Desktop.

Everything stays free and local: no subscription, no server, no account, no card.

## What is new

| | |
|---|---|
| **Installer** | `ACQ-Setup-<version>.exe` (Inno Setup). Per user, no administrator prompt, no UAC. |
| **The program** | `ACQ.exe` (PyInstaller). No Python on the machine, no console window, no PowerShell. |
| **Its own window** | A WebView2 window titled *Acquisitions Assistant*, not a browser tab. |
| **Shortcuts** | Desktop and Start Menu, plus *Open data folder* and *Uninstall*. |
| **One copy only** | A real OS file lock; a second launch focuses the running one instead of starting a second server. |
| **Start with Windows** | Optional checkbox in the installer; removable from the Start Menu like any app. |
| **Your data, kept apart** | `%LOCALAPPDATA%\AcquisitionsAssistant\` — database, password, backups. Updating or uninstalling never touches it; the uninstaller asks before deleting anything. |
| **Old folders keep working** | Running from source uses the same folder as before, and an installed copy **adopts** an existing database from an old ZIP folder once, without deleting it. |

Nothing that existed before was removed: `START-ACQ.cmd` still works for anyone who prefers it
(and now stores credentials in the same place for the installed app), and the web deployment is
unchanged.

## How it is built (free)

`.github/workflows/windows-app.yml` runs on GitHub's free Windows runner: compiles the interface,
builds `ACQ.exe`, builds the installer with Inno Setup, then **runs the packaged program** and
checks it before attaching the files to the release. No paid service is involved at any point.

## Verified

| Check | Result |
|---|---|
| Full backend suite | **274 passed**, 2 explicit skips |
| Frontend unit tests | **21 passed** |
| `ruff check .` | clean |
| `check_references.py` | 27 documents, no broken links |
| Frozen layout (`scripts/test_frozen_layout.py`) | bundle boots, migrations reach `0a6d91cf17b2`, interface served from the bundle, database written **outside** it |
| Live launcher run | server answered `/api/health` on a real port; `data/acquisitions.db`, `.env`, `logs/` created in the data folder |
| Second launch with the same data folder | exited 0 in 4 s, port never opened, first server unaffected |
| Icon | `desktop/acq.ico`, 7 sizes (16–256), 32-bit entries, drawn by `scripts/make_icon.py` with no image library |
| Desktop lifecycle (real process, twice) | `scripts/smoke_desktop_app.py`: boots, imports a seller through the API, refuses a second copy, closes, reopens with the same password and the seller still listed |
| Release archive (`acquisitions-assistant-v1.3.0.zip`) | 206 files, 7.5 MB, integrity `ok`, 0 foreign-key violations, every included file hash verified; it now carries `frontend/dist` so the ZIP still runs without Node |
| New tests for this release | 23 in `backend/tests/test_desktop_app.py`: folder split, portable mode, adoption of an old database, instance lock, stale lock, window logic with a stub webview, installer and spec contents |

## Not verified (needs Windows)

- `ACQ.exe` itself and the WebView2 window: no Windows host and no display here. The GitHub
  Windows runner builds it and smoke-tests it on the tag; until that run exists, this is the one
  claim in this release I cannot make myself.
- The Inno Setup installer's screens and the uninstall prompt.
- The unsigned-download SmartScreen prompt (**More info → Run anyway**, once per version).

## Upgrading from 1.2.x

Nothing to copy by hand. Install 1.3.0; on first start it finds the old folder, copies the
database and `.env` into `%LOCALAPPDATA%\AcquisitionsAssistant`, and leaves the old folder exactly
as it was. The disk copy stays as your fallback.
