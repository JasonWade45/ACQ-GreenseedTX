# Project status — Acquisitions Assistant AI 1.2

**Updated 2026-10-25.** Unified local-first working seller-acquisitions application. Source comparison: GitHub `JasonWade45/ACQ-GreenseedTX` main **`f96bc3d25b4aea4def3e1122a2004c7bf56c04ad`** plus delivered 1.1. Both user workspaces contain important data; neither database is treated as expendable or interchangeable.

## Implemented

- Retained DB dashboard/drill-downs, seller search/filter/sort/page/export, source profiles, multiple properties, actual activities/appointments/offers/tasks, independent pipeline/contact/task states, observed history, audit, explained daily queues, zero-safe reports, saved views, indexed SQLite/Alembic data, backups and restore guards.
- Retained conservative documented read-only REsimpli sync: stable IDs, pagination, bounded retries, manual/optional schedule, truthful never/partial/failure/freshness. Real account response mapping still requires local verification. No CRM create/edit/delete/status/note write is enabled.
- Retained optional rules/loopback Ollama and manually reviewed/redacted Groq analysis/notes/drafts, meaningful cache, strict schemas, per-request approval/expiry/source/model/key gates, source-linked evidence, second review before notes are saved, editable copy-only drafts, DNC and unknown-eligibility guards. No automatic cloud import/sync/startup/batch requests.
- Added persistent editable local **call preparation**, recorded property talking points, reviewed-only checklist/notes and guardrails. No inferred contact; stale/restricted openers withheld; regeneration preserves old plans in the DB.
- Added grounded **property research brief**: exact subject selection, recorded financial references, suggested search criteria, copy address and legitimate portal home links. No MLS feed, scraping, invented comparable addresses/prices/dates or financial offer.
- Added richer explicit property facts and source provenance, compound-cell/address-only imports, magnitude suffixes, range-as-unknown handling, meaningful counts, optional explicitly linked **fill-empty-only** enrichment and unknown-owner presentation without invented names.
- Added an explicitly confirmed local rule-only refresh (at most 200 recent records per run), no Groq/Ollama request.
- Added backup-first **both-workspace migration**: private consistent SQLite snapshot, schema/integrity/FK guard, target recovery backup, pending candidate/conflict preview, explicit separate/link/skip, stable UUID mapping, per-row commits/resumption, stale-review refresh, preserved DNC, no settings/key activation, no automatic person merge. Historical AI/draft/preparation stays unverified source archive rather than becoming active output.
- Added native Windows `MERGE-WORKSPACES.cmd/.ps1`, updated prebuilt start/update helpers and Arabic guide. Run files, not CMD contents pasted into PowerShell. No Node/WSL required for the release UI.
- Preserved the professional responsive English interface, keyboard search/tabs/mobile navigation, loading/error/empty/success states, subtle motion and reduced-motion support; added preparation, research and database-migration review UI.

## Actual current verification

Current suite artifacts are regenerated for 1.2, not relabelled 1.1 results:

- Backend: **167 passed, 1 explicit live-account test skipped**; retained one benign upstream TestClient deprecation.
- Frontend unit: **20 passed**.
- Real-app browser: **17 passed** against a migrated isolated fixture DB, including four new unified workflows and separately guarded synthetic/no-network Groq cases.
- Ruff, ESLint, TypeScript and production build passed; locked-install npm audit reported **0 vulnerabilities**. The current 1.2 backup/restore and extracted ZIP boot/hash/empty-DB/SPA/asset/auth checks passed, including paths with spaces.
- Populated **1.1 → 1.2**: all **17 original application-table values exactly unchanged**, six fictional sellers/DNC/local overrides preserved, new head **`0a6d91cf17b2`**, 19 app tables, integrity `ok`, zero FK violations; automatic recovery backup verified.
- Exact pinned GitHub ORM-generated UUID database → upgraded target: seller/property/activity/task/appointment conversion, historical edited draft preservation, source main-file unchanged and target backup verified. No remote app/account or provider was run for this conversion.
- Additional migration tests exercise live-WAL source consistency, no automatic insertion, explicit choices, known-person/property conflicts, stable identity/reapproval/changed-source idempotency, current-target hashes, tampered snapshots, preservation of old artifacts, conservative contact/date handling and later verified event reconciliation.
- Sixteen actual/synthetic QA screenshots include the new preparation/research/database-review pages; no page exception, and all three new mobile flows fit a 390 px document/viewport.
- See `docs/VERIFICATION.md`, `docs/UNIFIED_MERGE.md`, `docs/unified-upgrade-check.json` and JUnit/JSON evidence. Native Windows helpers, actual company data and real vendor accounts are **not** validated here.

## Architecture / migrations

React 19 / TypeScript / Vite / React Router / React Query, bundled CSS and Lucide icons; single same-origin FastAPI/Pydantic server, SQLAlchemy/Alembic, SQLite WAL/FKs, APScheduler. HTTPX is used only in guarded integrations. Loopback by default; remote preview requires strong password authentication and relative `/api` URLs. No CDN, paid database, mandatory model or automatic download.

Migration chain: `daec27051e18` → `9e8b3c712f42` → **`0a6d91cf17b2`**. The new migration adds **call_plans** and **workspace_merges** only. 19 application tables plus Alembic's version table. Existing seller/source/import/task columns are not destructively transformed.

The GitHub UUID `backend/acquisitions.db` is **not** a compatible restore file for the unified integer-key `data/acquisitions.db`. The guard refuses applying our migrations to it. Use the reviewed bridge, not replacement SQL copies.

## Safety invariants

**ABSOLUTELY NO AUTOMATIC SELLER COMMUNICATION.** No SMS/email/calls/dialer/send endpoint, hidden outreach job or external-browser contact is implemented. Preparation/drafts never record contact. Human operators use an approved outside workflow.

REsimpli is intended primary truth; sync stays read-only. Source DNC cannot be lifted locally; unknown restrictions are not clearance; reviewed-clear is not legal consent certification. Failed/unknown/completed calls, internal notes/tasks and pipeline names cannot fabricate successful seller contact or dated history. Existing source values/originals remain preserved with local and AI provenance separate.

Previously pasted vendor keys were not reused, reproduced, inserted into source/frontend/release or tested against an account. Enter rotated replacements locally. Private settings and SQLite/snapshots are plaintext private files requiring OS permissions/disk encryption; not a secret vault.

## Gates / honest limits

1. Actual Windows runtime/helpers, both real company DB conversions, real REsimpli authentication/full field and response semantics, actual Groq completion/entitlements/billing and Ollama inference remain untested. Passing mocks/fixtures do not establish account readiness.
2. No CRM writes or automatic new-seller submission. Manual reviewed CSV handoff remains supported. An actually verified creation mechanism, confirmation/uncertain-outcome reconciliation and downstream-automation safety are separate future work.
3. Research supplies criteria, not sold comparables/appraisal. Quote matches/redaction do not guarantee semantic accuracy or complete privacy. Human review/company authorization remain mandatory.
4. Legacy import/template/sync/audit history, unassigned events and unsupported source fields remain in private whole-source snapshots/table inventory rather than being fabricated into active unified ledgers. Historical AI/drafts/plans are readable as unverified per-lead source archives, not active recommendations.
5. One workspace/password/worker, no per-user roles or individual actor identity; not a public multi-user security certification. One primary normalized phone/email, no geocoding/identity proof/revenue accounting, no .xls support. 2k-row regression coverage, not 50k-row or large migration/long scheduler/concurrency certification.
6. This unified tree is based directly on GitHub `f96bc3d25b4aea4def3e1122a2004c7bf56c04ad`; the complete original history remains intact. The old 1.1 bundle/publish kit is stale and must not be force-pushed. A local commit alone is not publication proof: verify the remote branch before reporting an upload. See `docs/GITHUB_UNIFICATION.md`.

## Exact next action for this user

Stop both old apps → extract 1.2 separately → run the new **UPDATE-WINDOWS.cmd**, selecting the old **delivered 1.1 root** → in that updated root run **MERGE-WORKSPACES.cmd** and choose the GitHub **backend/acquisitions.db** → run **START-WINDOWS.cmd** → **Import Center** → review each pending person and explicitly approve selected decisions. Keep both originals/backups. Do not upload customer DBs or keys to chat, copy one DB over the other, or paste CMD contents into PowerShell.
