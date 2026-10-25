# Acquisitions Assistant — Unified 1.2.4 (Linux deployment)

**Released 2026-10-25 (Africa/Cairo).** Makes Linux the first-class deployment target and
removes the need for Windows to put the app online. Application behaviour and schema are
unchanged from 1.2.3.

## Why this release exists

1.2.3 shipped a Windows-first online path (Cloudflare Tunnel scripts). Deploying business data
from a Windows desktop is not a good default: no container isolation, manual backups and manual
updates. 1.2.4 provides the Linux paths instead, with the container entrypoint hardened.

## Added

| File | Purpose |
|---|---|
| `deploy/install.sh` | One-command Linux VPS setup: installs Docker when missing, clones/updates `/opt/acq`, generates a strong password and session secret, writes `deploy/.env` with mode 600, opens ufw, starts the stack, waits for `/api/health`. Supports `--dry-run`, `--force`, `--port`, `--timezone`, `--dir`. Re-running preserves an existing valid password. |
| `deploy/docker-entrypoint.sh` | Honours `$PORT` (Render/Railway/Fly/Cloud Run), fails fast with `FATAL` when the password is missing or shorter than 12 characters, and refuses to start when the data directory is not writable. |
| `render.yaml` | Render Blueprint for one-click deployment from GitHub: Docker runtime, `/api/health` check, 1 GB persistent disk at `/app/data`, `APP_ACCESS_PASSWORD` left `sync: false`, `SESSION_SECRET` auto-generated. |
| `deploy/acq.service` | Hardened systemd unit for a bare-metal install without Docker (`ProtectSystem=strict`, `NoNewPrivileges`, non-root user, writes only `/var/lib/acq`). |
| `deploy/acq.env.example` | Template for `/etc/acq/acq.env` with the database outside the checkout. |

`Dockerfile` now uses the entrypoint instead of a hard-coded port, so one image runs locally and
on every managed platform.

## Changed

- `docs/DEPLOY_SERVER_AR.md` rewritten Linux-first: Render Blueprint, one-command VPS, and
  bare-metal systemd with Caddy. Windows reduced to a short, clearly optional appendix.
- `scripts/package_release.py` ships `render.yaml` and the new `deploy/` files.

## Verified here

| Check | Outcome |
|---|---|
| Backend pytest | **169 passed**, 1 intentional live-account skip, 0 failures |
| Ruff | Clean |
| `deploy/install.sh` | `bash -n` clean; `--dry-run` prints every step without changing anything; `.env` logic exercised for real: fresh generation, password preserved on rerun, rotated with `--force`, custom keys kept, mode 600 |
| `deploy/docker-entrypoint.sh` | `sh -n` clean; **actually executed**: honoured `$PORT=8100` instead of 8000, created the database in `DATA_DIR` (20 tables, head `0a6d91cf17b2`, `integrity ok`), and exited 1 with `FATAL` for empty and 5-character passwords |
| `render.yaml` | Parses as YAML; docker runtime, health check, disk, no literal secrets |
| Release archive | **165 files**, all manifest hashes verified; `install.sh` and `docker-entrypoint.sh` keep their executable bit inside the ZIP |
| Extracted archive end-to-end | Unzipped into a path containing a space, started through the real entrypoint: health 200, page 200, login 200 with a 106-character token, authenticated API 200, database created with the expected schema |

## Not verified here

- **Docker image build** — no Docker in the build environment.
- **Anything on Render or a real VPS** — no outbound access to hosting providers, and no domain.
- **systemd unit execution** — no systemd here; the unit is written to the documented interfaces.
- Live REsimpli responses, real Groq completions and both company databases remain unvalidated.

## Safety

No seller communication, no CRM writes, no automatic cloud batch. Guarded integrations stay
disabled by default in every deployment file. The archive contains no database, no `.env`, no
vendor key and no password.
