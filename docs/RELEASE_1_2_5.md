# Acquisitions Assistant — Unified 1.2.5 (defect fixes)

**Released 2026-10-27 (Africa/Cairo).** A correctness release: it fixes defects that made
documented commands fail, made some backups invisible, and let stale guides point at files
that no longer exist. No schema change; an existing database opens without migration.

## Defects fixed

| # | Defect | Effect before | Fix |
|---|---|---|---|
| 1 | `deploy/install.sh --help` read its own file with `sed -n '2,30p' "$0"` | The documented `curl … \| sudo bash -s -- --help` printed `sed: can't read bash` and showed nothing, because `$0` is `bash` under a pipe | Embedded usage text that works from a file and from a pipe |
| 2 | `--no-https` set a flag nothing used | The stack always started Caddy, which can never issue a certificate for an IP, so an IP-only VPS produced a broken site | New `deploy/docker-compose-http.yml` publishes the app port directly; the installer picks it, opens that port in ufw, prints the real URL, and warns that traffic is unencrypted |
| 3 | The installer accepted an IP with `--no-https` but never special-cased it | A bare IP passed the domain regex and then failed inside Caddy | Explicit validation: an IP with HTTPS is refused with an explanation; the IP is accepted only with `--no-https` |
| 4 | Backup filenames were matched with a hard-coded `acquisitions-` prefix | A database called `acq.db` produced backups that existed on disk but were **invisible to listing, impossible to download, and never rotated** | The pattern is derived from the database filename; a regression test uses `acq.db` |
| 5 | The create-backup endpoint searched the listing for the file it had just written | Any naming mismatch turned a successful backup into `500 Internal Server Error` | The response describes the file that was written, instead of re-finding it |
| 6 | The audit write ran before the token was returned | A failure to store the audit row would have broken sign-in entirely | `record_audit()` never raises; a test forces it to fail and asserts sign-in still succeeds |
| 7 | Revoked tokens were dropped wholesale at the 500-entry cap | Earlier "sign out" decisions became reversible | Bounded FIFO that drops the oldest entry only |
| 8 | `FORWARDED_ALLOW_IPS` was pinned to `127.0.0.1` | Behind Caddy in Docker every client looked like one address, so eight failed logins locked out everyone | Configurable; the HTTPS stack trusts only its own proxy network |
| 9 | The desktop launcher printed the saved password on **every** start | A shared or recorded screen leaked the workspace password | Printed once at creation; afterwards `--show-password` is required |
| 10 | Rotation could delete any file ending in `-scheduled.db` | A user file with that suffix could be removed | Only files matching this module's own naming pattern are candidates |
| 11 | README, `PROJECT_STATUS.md`, `READY_SYSTEM_AR.md`, `DEPLOY_SERVER_AR.md` and three merge guides told people to double-click Windows helpers that had moved | Following the docs produced "file not found" | Every active guide now points at `legacy/windows/…`, and `scripts/check_references.py` fails CI if this ever recurs |
| 12 | Release notes in `VERIFICATION.md` were presented as current results | Stale numbers described as live checks | Marked as a historical log with a pointer to this file |

## Added

- `backend/app/version.py` — one source of truth (`APP_VERSION`) for the API version.
- `scripts/check_references.py` — verifies every relative Markdown link resolves, every active
  guide points at the current location of a moved file, and every file the packager lists exists.
- `backend/tests/test_deployment_files.py` — actually executes the installer: `--help` through a
  pipe, the missing-domain error, the IP rejection under HTTPS, a full dry run, `--no-https`
  selecting the HTTP compose file, plus compose invariants (shared `app-data` volume, no
  published port behind Caddy, `header_up Host {host}`, explicit Dockerfile).
- `backend/tests/test_backups.py` — WAL-with-uncheckpointed-writes, foreign-file safety,
  navigation attempts, and a database named `acq.db`.
- `backend/tests/test_desktop_launcher.py` — password lifecycle, `.env` preservation, bounded
  output, QR generation, port probing.
- CI now parses every shell script and runs the reference checker before the suite.

## Verified here

| Check | Outcome |
|---|---|
| Backend pytest | **224 passed**, 1 intentional live-account skip, 0 failures |
| Ruff | Clean |
| `install.sh` | `bash -n` clean; `--help` works from a pipe; `--dry-run` complete for both modes; IP + HTTPS refused with a clear message; `--no-https` prints `http://203.0.113.10:8099` and `docker-compose-http.yml` |
| Running server (port 8412, database `/tmp/acqrun2/acq.db`) | health 200, unauthenticated `/api/leads` 401, login 200, backup create 200, list 200, download 200 (`SQLite format 3`), delete without confirmation 400, with confirmation 200, sign-out 200 then 401, zero tracebacks in the log |
| Backups | A copy of a WAL database with uncommitted-to-main writes contains the newest row and leaves no `-wal`/`-shm`/`partial` files |
| Documentation | `check_references.py`: 18 documents, no broken links, no stale paths |
| Frontend | 20 tests passed, `tsc -b` + `vite build` clean |

## Not verified

Windows execution of `START-ACQ.cmd`, a real VPS with a domain and Let's Encrypt, Render/Oracle
deployment, and both real company databases. The Docker image is built and smoke-tested in
GitHub Actions, not on a production host.

## Upgrade

Nothing to migrate. Extract over your existing folder keeping `data/`, `.env` and
`.env.secrets`, then start as before: `START-ACQ.cmd` or `./start-acq.sh`.
