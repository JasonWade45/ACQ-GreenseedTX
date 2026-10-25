# Acquisitions Assistant — Unified 1.2.2 (documentation delivery)

**Released 2026-10-25 (Africa/Cairo).** This release ships the **same verified application code
as 1.2.1** together with the new consolidated Arabic handover and the Drive-versus-repository
audit. No application behaviour, schema, migration, fixture or dependency changed.

## Why this release exists

Release 1.2.1 was published before the consolidation documents existed. Rather than rewrite a
published tag and asset, 1.2.2 supersedes it as the latest download and 1.2.1 remains as a
historical record. Both contain identical application code.

## What is new compared with 1.2.1

- `docs/READY_SYSTEM_AR.md` — Arabic end-to-end handover: what was consolidated, what was
  actually verified, how to run on Windows, and the approved order for merging the two real
  company databases (`UPLOAD-DATABASES` → `UPDATE-WINDOWS` → `MERGE-WORKSPACES` → Import
  Center review).
- `docs/drive-audit-2026-10-25.json` — audit of the shared Drive folder against this
  repository: all **145** release-manifest hashes matched, the 1.2 documentation files were
  byte-identical (MD5) to their 1.2.1 counterparts, and the older snapshots added only build
  artifacts (`.venv`, one empty stale database with 17 tables and 0 leads, an initial npm
  audit log). No improvement from any folder was missing.
- `PROJECT_STATUS.md` records the re-verification of the consolidated build.

## Verification actually executed for this content

| Check | Observed outcome |
|---|---|
| Backend pytest | **167 passed**, 1 intentional live-account skip, 0 failures |
| Frontend Vitest | **20 passed**, 0 failures |
| TypeScript + Vite build | Passed, 1,649 modules; JS 467.12 kB, CSS 104.81 kB |
| Fresh database | **20 app tables**, head `0a6d91cf17b2`, `integrity ok`, 0 FK violations |
| Live boot | Automatic migration, workspace authentication required, 401 before sign-in, CSP and `no-store` present |
| Real CSV import through the API | 8 rows → 6 new leads + 1 duplicate + 1 invalid; stages, DNC and 5 properties preserved |
| Extracted archive smoke test | Passed: per-file hashes, a path containing spaces, fresh empty database, SPA and assets served, auth enforced, loopback rebinding refused |

Platform note: this pass ran on **Python 3.11.2 / Node 22.22.3**. Earlier 1.2 evidence was
recorded on Python 3.13 / Node 20. Both passed. Native Windows helpers, real company databases,
live REsimpli responses and real Groq completions remain **not** validated here.

## Contents

148 files: application source, tests, documentation, fictional fixtures/examples and the
prebuilt UI (`frontend/dist`, so **Node is not required** to run the release).

Excluded by design: every database, WAL/snapshot, `.env`/secret file, vendor key, dependency
folder and runtime log.

## Safety unchanged

No automatic seller communication, no CRM writes, no automatic cloud batch, no unverified
account action. REsimpli remains read-only and opt-in. DNC cannot be lifted locally. Cloud
output stays a reviewed proposal. The archive contains **no** company data and **no** keys.

## Verify before running

```powershell
Get-FileHash .\ACQ-GreenseedTX-v1.2.2.zip -Algorithm SHA256
```

Compare against the published `.sha256` asset. Then extract to a new folder and run
`START-WINDOWS.cmd`. Before merging real databases, run `UPLOAD-DATABASES.cmd` first.
