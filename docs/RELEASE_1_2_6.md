# Acquisitions Assistant — Unified 1.2.6 (one-click update)

**Released 2026-10-28 (Africa/Cairo).** A convenience release: it adds the update tool that was
missing. Until now, moving to a new version meant extracting a ZIP, copying `data/` and `.env`
by hand, and hoping nothing was missed. Now it is one double-click, with a backup taken before
anything changes and an automatic rollback if a step fails. No schema change; an existing
database opens without migration.

## What is new

| File | What it does |
|---|---|
| `UPDATE-ACQ.cmd` | Windows entry point. Double-click it from the **new** release folder. |
| `update-acq.sh` | Same thing on macOS and Linux (`./update-acq.sh`). |
| `scripts/update_acq.py` | The logic: plan, back up, snapshot, copy, migrate, verify, roll back. |
| `backend/tests/test_updater.py` | 16 tests that build a real old installation and update it. |

## What a single double-click does

1. Refuses to run while the app is still listening on its port, so no file is replaced under a
   running process.
2. Copies the live database to `backups/before-update-<version>-<stamp>.db` and validates it
   (`integrity_check` + `foreign_key_check`). If the copy is missing or empty, nothing else happens.
3. Keeps every file it is about to overwrite in `backups/code-before-<stamp>/`.
4. Copies the release files only. `data/`, `.env`, `.env.secrets`, `.venv/` and `backups/` are
   never read from the archive and never replaced — the filter is by path, not by luck.
5. Installs the locked dependencies and runs `manage.py migrate` (`alembic upgrade head`).
6. Starts the updated copy once on a spare port and waits for `/api/health` to answer 200.
7. On any failure after copying: restores the previous files, deletes the files this run created,
   prunes directories it created, and reports the original error. The database is untouched
   because it was never in the copy list.
8. Remembers the installation folder in `%LOCALAPPDATA%\AcquisitionsAssistant\install.txt`
   (or `~/.local/state/...`), so later updates need no path at all.

## Verified

| Check | Result |
|---|---|
| `backend/tests/test_updater.py` | **16 passed** |
| Full backend suite | **240 passed**, 1 intentional live-account skip |
| Real upgrade, 1.2.5 → 1.2.6 | 183 files replaced, 3 added, schema migrated, temporary start answered 200 |
| The same update run from inside the published ZIP | identical result, exit 0 |
| `.env` after the upgrade | `md5` identical to before, byte for byte |
| Database content after the upgrade | every table and row identical (`iterdump` compared); the only addition is the default `scheduler` row a first start writes |
| Arabic record in the old database | still listed through `/api/leads` after the upgrade |
| Old password after the upgrade | sign-in returned 200 |
| App running during the update | refused, exited 1, nothing changed |
| Server log during the real upgrade | 0 tracebacks |

## Not verified

A real Windows run (no PowerShell or Windows host here), and a real phone on a home LAN. The
first update on your machine is the first real-Windows execution — which is exactly why the
backup and the rollback exist.

## Upgrading

Extract this ZIP into a **new** folder, close the running app, then:

- Windows: double-click `UPDATE-ACQ.cmd`
- macOS/Linux: `./update-acq.sh`

Dry run first if you prefer to see the plan: `--dry-run` changes nothing.

## Unchanged

Database schema (`0a6d91cf17b2`), the join between the two company databases, vendor
integrations, and every API route. 1.2.5 remains published and untouched.
