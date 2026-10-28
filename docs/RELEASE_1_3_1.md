# Acquisitions Assistant — 1.3.1 (the release that installs)

**Released 2026-10-28 (Africa/Cairo).** `v1.3.0` published the source and the notes, but
its Windows build failed on the runner, so no `.exe` was ever attached to it. 1.3.1 is
that same program, built and **smoke-tested on a real Windows machine** before anything
was published:

| | |
|---|---|
| `ACQ.exe` | the program, one file, no console, icon and version info, no Python needed |
| `ACQ-Setup-1.3.1.exe` | double-click installer, per user, no UAC, Desktop + Start Menu shortcuts |

Both are attached to this release. Nothing below costs anything: no subscription, no
server, no account, no card.

## What the Windows runner proved before publishing

`.github/workflows/windows-app.yml` (workflow run
[40762533356](https://github.com/JasonWade45/ACQ-GreenseedTX/actions/runs/40762533356))
built both files on a GitHub-hosted Windows machine and then **ran the packaged
program**:

| Check | Result |
|---|---|
| `python scripts/smoke_desktop_app.py` (source, two runs) | password and database created in the data folder, second copy stood down, a seller imported, restart kept it |
| PyInstaller build | `dist\ACQ.exe` produced |
| Inno Setup build | `dist\ACQ-Setup-1.3.1.exe` produced |
| Packaged `ACQ.exe` started | answered `/api/health` on port 8099 |
| Packaged interface | `/` served `<div id="root">` from inside the executable |
| Data folder | `data\acquisitions.db` and `.env` created in `%TEMP%`, not inside the bundle |
| Second copy | exited without opening a second server |
| Artifact | both `.exe` files uploaded |

## What was fixed to get there

Three defects, each found by the runner rather than by a description:

1. **The interface never compiled in the build script** — `run()` passed `cwd` twice and
   raised `TypeError` before npm started. Found by 1.3.0's tag build.
2. **The installer was handed a relative path** — Inno resolves `/DSourceExe` from the
   folder holding the `.iss`, so it looked for `desktop\dist\ACQ.exe`. Found by the
   branch build.
3. **The windowed program had no console and no guard** — PyInstaller gives a windowed
   build `sys.stdout = None`; uvicorn's first banner write raised and killed the
   program before the window appeared. `acq_app.py` now installs a stand-in stream.
   Found because the workflow rebuilds a console copy of the same program and prints
   its traceback when the packaged smoke test fails.
4. **`alembic.ini` landed in a folder named after itself** — PyInstaller treats the
   second element of a `datas` pair as a *folder*, so `fileConfig` saw a zero-byte
   directory and raised `alembic.ini is an empty file`. `bundle_datas()` is now one
   list shared by the spec and `scripts/test_frozen_layout.py`, which builds the bundle
   with PyInstaller's own semantics.

None of the four could be reproduced in this Linux environment, which is why the
earlier release notes said the `.exe` was unverified. It is verified now.

## Verified here as well

| Check | Result |
|---|---|
| Backend suite | **278 passed**, 2 explicit live-account skips |
| Frontend | **21 passed**, `tsc -b` + production build clean |
| `ruff check .` | clean |
| `check_references.py` | 27 documents, no broken links |
| `scripts/test_frozen_layout.py` | bundle boots, migrations reach `0a6d91cf17b2`, interface served from the bundle, database outside it |
| `scripts/smoke_desktop_app.py` | two runs of the real entry point, data kept, restart reuses the password |
| Release archive | integrity `ok`, 0 foreign-key violations, every included file hash verified, `frontend/dist` included |

## Upgrading

Nothing to copy by hand. Install 1.3.1; on the first start it finds an old ZIP folder,
copies its database and `.env` into `%LOCALAPPDATA%\AcquisitionsAssistant` once, and
leaves the old folder exactly as it was. The Arabic guide is
[docs/INSTALL_WINDOWS_AR.md](INSTALL_WINDOWS_AR.md).

Because the files are unsigned, Windows shows **Windows protected your PC → More info →
Run anyway** once per download. A certificate costs money every year and this project is
meant to stay free; that prompt cannot be removed in code.
