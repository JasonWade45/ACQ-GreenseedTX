# Project status — Acquisitions Assistant AI 1.6.0

**Updated 2026-10-30.** Unified local-first seller-acquisitions application. **Release:
`v1.6.0`** — see `docs/RELEASE_1_6.md`. Earlier releases (`v1.5.0`, `v1.3.1`, `v1.2.9`, `v1.2.8`,
`v1.2.3`, `v1.2.2`, `v1.2.1`) are retained unchanged; a published tag is never rewritten.

## What is new in 1.6.0

- **Call desk.** A lead profile has a **Calls** tab: record an outcome that already happened,
  see the next step it implies, and create the local follow-up. Outcomes are deterministic;
  a Do-Not-Contact outcome suppresses the phone locally and schedules nothing.
- **Live call script.** A deterministic five-step script and objection handling built from the
  lead's own property data. No model call and no invented ARV/repair numbers.
- **Tags.** Local labels per lead, with an API and a profile panel; they never leave the machine
  unless the operator exports them.
- **Assignment rules.** State/city priority rules (with an optional fallback) fill
  `leads.assigned_manager`. They never change a stage, restriction or contact permission.
- **Automation engine.** Reviewed local rules (stale lead, warm lead, dead-lead archive) create
  follow-ups, tags or a Dead stage change; every run is logged. No send, no dialer, no CRM write.
- **CRM Push documented and verified.** The 1.5 tree already contained `crm_push.py`; the stale
  "no CRM write" claims are replaced. Create-one-lead is off by default, searches for duplicates
  first and never edits/deletes/changes a CRM status.
- **Zero-cost, no-card deployment.** `render-free.yaml` + Neon PostgreSQL is the documented path;
  the local Docker-free run and the merged screens were exercised here.
- **Docs corrected:** test counts, version, CRM write boundary and the new screens.

## What the app is now

- **Data Syndicate intake, worked properly (1.5.0).** An address-only vendor export is
  imported with heat, sale likelihood, equity, flags, compatible offers, county, lead
  type and recorded date kept as *internal* context that never appears in a draft. A
  lead with no verified owner name or phone is flagged `NEEDS_SKIP_TRACE`, worked from
  its own queue section and blocked from drafting until the skip-trace loop gives it a
  contact.
- **A reviewed skip-trace loop (1.5.0).** Export address + lead key only, run it through
  your own provider, import the results, review matched/rejected/conflicting rows, then
  type `IMPORT LOCAL`. CRM-synced phone numbers are never replaced without an explicit
  per-row decision.
- **Cold outreach drafts (1.5.0).** `outreach_mode` cold keeps every gate except the
  relationship requirement. 13 template categories × 2 variants, a stored reason for
  the chosen template, and a hard validator (identity, street address, opt-out line, no
  emoji/URLs/dollar amounts/placeholders/false urgency, ≤320 characters). Bulk
  generation creates drafts only: `bulk_copy: false`, `bulk_send: false`.
- **Replies and cadence (1.5.0).** Rule-first classification with a confidence and a
  quoted evidence span; low confidence is flagged for a human read. Any reply pauses
  the cadence immediately; suppression, stage changes and follow-ups stay suggestions
  you confirm or dismiss. Cadence days are editable (default
  `0, 3, 7, 14, 30, 60, 90, 120`) and the runner only ever creates drafts and tasks.
- **Daily briefing (1.5.0).** Opt-outs first, then replies with evidence, follow-ups,
  drafts awaiting review, drafts failing validation, skip-trace leads, stalled leads
  (14 days), sync conflicts and the last backup — with a second verified backup folder.
- **A program you run on your own computer.** `START-ACQ.cmd` (Windows) or `./start-acq.sh`
  (Linux/macOS) creates the private environment, generates a strong password, prints the
  local and LAN addresses plus a QR code, and opens the browser. Any phone or laptop on the
  same network opens it with that password. Nothing is exposed to the internet.
- **One-click updates.** `UPDATE-ACQ.cmd` (Windows) or `./update-acq.sh` (Linux/macOS) copies
  a newer release over an existing installation: it backs up the database, keeps every file it
  is about to replace, never touches `data/`, `.env` or `.venv`, upgrades the schema, starts the
  updated copy once to prove `/api/health` answers, and restores the previous version
  automatically if any step fails.
- **Verified backups by default.** A nightly copy goes to `data/backups/` through SQLite's
  online-backup API against a read-only connection, is checked with `integrity_check` and
  `foreign_key_check`, is folded out of WAL mode, and is only renamed into place after it
  passes. Seven scheduled copies are kept; manual copies are never pruned. The same actions
  are available in **Settings → Runtime & backups** and over `/api/backups`.
- **Sessions that can actually be cancelled.** `POST /api/auth/logout` revokes the calling
  token on the server; `/api/auth/logout-all` revokes every token with a cutoff persisted in
  the database, so a restart cannot resurrect an old session. Sign-ins and sign-outs are
  audited without ever storing the password.
- Retained: dashboard and drill-downs, seller search/filter/sort/page/export, source
  profiles, multiple properties, activities/appointments/offers/tasks, independent pipeline
  and contact states, audit trail, explained daily queues, zero-safe reports, local
  preparation plans, grounded property research, compound/address-only imports with
  reviewed fill-empty-only enrichment, and a reviewed backup-first bridge for the two legacy
  company databases.
- **Drafts that can actually be sent (1.2.7).** One decision function picks **follow-up** when
  a conversation is on record, **opener** when there is none, and every body ends with the fixed
  signature `Jason Wade / Acquisition Manager, GreenSeedTX LLC`, appended locally after validation.
- **Sold comparables worksheet (1.2.7).** Your own researched sold prices, `$/sq ft` per comp,
  a median-based range over the subject's living area, audit rows on add/remove. No MLS, no
  scraping, no invented sales.
- **The stage table is real (1.2.7).** Sync records every `mainStatusTitle` it sees with a count;
  Settings shows them with a stage selector, and anything unrecognised stays visibly unmapped.
- **The comparables range is never a dead end (1.2.8).** A property the CRM never gave a living
  area used to make the range impossible. `PATCH /api/leads/{id}/properties/{pid}` fills only an
  empty `square_feet`/`bedrooms`/`bathrooms`, is audited, and never replaces a source value.
- **An installed Windows program (since 1.3.1).** `ACQ.exe` + `ACQ-Setup-1.6.0.exe` built by PyInstaller and
  Inno Setup on a free GitHub Windows runner: no Python, no PowerShell, no console, a Desktop and
  Start Menu shortcut, one copy at a time, and a data folder (`%LOCALAPPDATA%\AcquisitionsAssistant`)
  that survives upgrade and uninstall. Running from source keeps the old layout and adopts an
  existing database, so an older ZIP still opens with its sellers.
- **The status table sees CSV imports too (1.2.9).** `create_local_lead` records the status title
  it was given, so `Settings → Pipeline & priorities` is populated after a CSV import as well as
  after a CRM sync — previously a local import left the table empty and looked like a broken sync.
- Retained: conservative read-only REsimpli sync (stable IDs, pagination, bounded retries,
  truthful never/partial/failure/freshness) and optional, manually approved, redacted Groq
  analysis. **No seller communication. CRM sync is read-only; the separate reviewed
  create-one-lead push is off by default and never edits/deletes/changes status.**

## Current verification

| Check | Result |
|---|---|
| Backend suite | **559 collected, 0 failed, 29 skipped** |
| Lint | `ruff check backend scripts` clean |
| Frontend | **49 passed**, `tsc -b` + `vite build` clean |
| Browser suite | **20 passed** in GitHub Actions; a local headless Chromium pass over the merged screens had no page/console errors |
| Docker image | Dockerfile inspected; the local Docker daemon was not running, so the image was not rebuilt here. CI builds and smoke-tests it. |
| Release archive | `acq-1.6.0.zip` to be rebuilt by the release job (version and schema bumped; `frontend/dist` rebuilt here) |
| Windows program | built by the Windows release job; not rebuilt here |
| Desktop program | `scripts/smoke_desktop_app.py`: first start creates password + database in the data folder, a second copy stands down, one seller imported through the API, restart reuses the password and keeps the seller |
| Frozen layout | `scripts/test_frozen_layout.py`: bundle boots with `sys._MEIPASS`, migrations reach `k3l4m5n6o7p8`, interface served from the bundle, database written outside it |
| Deploy scripts | `install.sh --help` works through a pipe, `--dry-run` complete, `--no-https` publishes the port without Caddy |
| SQLite schema | 34 application tables, head `k3l4m5n6o7p8`, integrity `ok` (verified on a temporary migrated database) |

CI (`.github/workflows/ci.yml`) runs the five jobs above on every push and pull request;
`scripts/check_references.py` additionally fails the build if a guide points at a file that
no longer exists.

## Not verified

1. Native Windows execution of `START-ACQ.cmd` and the archived helpers; opening the LAN port
   from a real phone on a real home network.
2. A real Linux VPS with a real domain and Let's Encrypt issuance; Render/Oracle deployment.
3. Both real company databases; real REsimpli, Groq and Ollama accounts.
4. Multi-user roles: there is **one** workspace password and one worker. No per-user actor
   identity.
5. Scale: a 2,000-row import was exercised, not the 50,000-row maximum, and not long
   scheduler soaks or high concurrency.

## Where the old Windows workflow went

Deployment is Linux-only by decision. The tunnel, updater and merge helpers now live in
[`legacy/windows`](legacy/windows/README.md) and are archived, **not supported**. The one
supported Windows entry point is `START-ACQ.cmd`, which runs the app locally; it is not a
deployment target. Merging the two legacy databases is still documented in
[`docs/UNIFIED_MERGE.md`](docs/UNIFIED_MERGE.md) using those archived tools.

## Exact next action

Extract the release → run `START-ACQ.cmd` (Windows) or `./start-acq.sh` → open the printed
address → create a backup in **Settings → Runtime & backups** → import a reviewed CSV in
**Import Center** and approve only explicit decisions. Configure rotated keys locally in
**Settings → Connections & AI** if you need Groq or REsimpli. Keep seller communication off;
enable `CRM_WRITES_ENABLED` only for the reviewed create-one-lead push.
