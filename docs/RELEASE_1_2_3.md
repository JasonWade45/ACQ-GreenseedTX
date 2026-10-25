# Acquisitions Assistant — Unified 1.2.3

**Released 2026-10-25 (Africa/Cairo).** Fixes the gap that made online access look broken on
Windows, and finally ships the deployment files inside the release package.

## Why this release exists

Release `v1.2.2` was tagged **before** the deployment work was merged, so the downloadable
package contained no `Dockerfile`, no `deploy/` and no online guide. Anyone extracting it and
looking for "how do I put this online" found nothing. 1.2.3 corrects that.

It also fixes a real failure mode discovered while testing tunnels:

| Configuration | Page `/` | API `/api/leads` |
|---|---|---|
| No password + public Host header | 200 | **403** `Loopback mode rejects non-local Host headers` |
| Password set + public Host header | 200 | 401, then works after sign-in |

With no `APP_ACCESS_PASSWORD` the app runs in loopback mode and refuses every API request whose
`Host` header is not local. A tunnel therefore loads the interface and then fails all data,
which looks like a broken app instead of a missing password. There was no warning at startup.

## Fixed

- **Startup warning** (`backend/app/main.py`): when the password is empty the server now logs
  and prints a single explicit warning explaining the 403, the tunnel/proxy/LAN cause and the
  fix, instead of leaving the operator to discover it from a JSON error in the browser.
  Covered by two new backend tests (warning present when empty, silence when configured).
- **Release package completeness**: `Dockerfile`, `.dockerignore`, `deploy/` and
  `docs/DEPLOY_SERVER_AR.md` are now included by `scripts/package_release.py`.

## Added (Windows online access)

- `START-ONLINE-WINDOWS.cmd` + `scripts/start_online_windows.ps1` — generates a random
  `APP_ACCESS_PASSWORD` and `SESSION_SECRET` into a local `.env` on first run, prints the
  password once, validates the 12-character minimum, creates the virtual environment, then
  starts the server on `127.0.0.1:8010` and prints ready-to-paste tunnel commands.
  An existing `.env` with a valid password is never overwritten.
- `SETUP-TUNNEL-WINDOWS.cmd` + `scripts/setup_tunnel_windows.ps1` — one-time Cloudflare
  Tunnel setup: verifies `cloudflared`, verifies the local app answers, logs in, creates the
  named tunnel, backs up any existing `config.yml` before rewriting it, routes DNS, installs
  the Windows service, then prints the verification command.
- `docs/DEPLOY_SERVER_AR.md` rewritten with a tested Windows path, the 403 trap explained in
  a table, automatic-start options and an explicit verified / not-verified list.

## Verified here

| Check | Outcome |
|---|---|
| Backend pytest | **169 passed**, 1 intentional live-account skip (167 + the 2 new warning tests) |
| Warning behaviour | Prints when the password is empty, silent when configured — both asserted |
| `.env` with Windows CRLF line endings | Password read correctly; page 200, login 200 with token, authenticated API 200 through a public `Host` header |
| Password guard | `0.0.0.0` with fewer than 12 characters is refused; 12+ starts |
| Secret exclusion | `.env` and `deploy/.env` never enter the package; `compose.env.example` does |
| Package build | Passes with the new `.cmd` wrappers and deployment files included |

## Not verified here

- **PowerShell script execution**: no PowerShell in the build environment. Logic and syntax
  were reviewed; nothing was run on Windows.
- **Docker image build**: no Docker available.
- **Real domain / real server**: needs a domain and a server owned by the operator.
- Live REsimpli responses, real Groq completions and the two company databases remain
  unvalidated, as in every previous release.

## Contents

Source, tests, documentation, fictional fixtures and the prebuilt UI (Node is **not** required
to run it). No databases, no `.env`/secret files, no vendor keys, no dependencies, no logs.

## Safety unchanged

No automatic seller communication, no CRM writes, no automatic cloud batch. REsimpli stays
read-only and opt-in. The release contains no company data and no credentials.
