# Project status — Acquisitions Assistant AI 1.2.6

**Updated 2026-10-28.** Unified local-first seller-acquisitions application. **Published
release: `v1.2.6`** — see `docs/RELEASE_1_2_6.md`. Earlier releases (`v1.2.5`, `v1.2.4`,
`v1.2.3`, `v1.2.2`, `v1.2.1`) are retained unchanged; a published tag is never rewritten.

## What the app is now

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
- Retained: conservative read-only REsimpli sync (stable IDs, pagination, bounded retries,
  truthful never/partial/failure/freshness) and optional, manually approved, redacted Groq
  analysis. **No seller communication, no CRM writes, no automatic cloud batches.**

## Current verification

| Check | Result |
|---|---|
| Backend suite | **240 passed, 1 explicit live-account skip** |
| Lint | `ruff check .` clean |
| Frontend | **20 passed**, `tsc -b` + `vite build` clean |
| Docker image | **built and run in GitHub Actions**: refuses a weak password, `/api/leads` 401 then 200 after login |
| Release archive | built, checksummed, extracted and booted from a path containing a space |
| Deploy scripts | `install.sh --help` works through a pipe, `--dry-run` complete, `--no-https` publishes the port without Caddy |
| SQLite schema | 20 tables, head `0a6d91cf17b2`, integrity `ok` |

CI (`.github/workflows/ci.yml`) runs the four jobs above on every push and pull request;
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
**Settings → Connections & AI** if you need Groq or REsimpli. Keep seller communication and
CRM writes disabled.
