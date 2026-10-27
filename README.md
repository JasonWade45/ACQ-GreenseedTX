# Acquisitions Assistant AI · 1.2.6

A working **local-first US residential seller-acquisitions workspace**: React/TypeScript, FastAPI and SQLite. REsimpli is the intended primary CRM. This is an actual database-backed app, not a frontend mockup.

**Retained from 1.1:** optional Groq analysis/organized notes/drafts with **redaction + your explicit approval before each request**, private backend key settings, a refreshed responsive interface, Ctrl+K search, page/card/modal/loading animation, reduced-motion support and easier native Windows start/update helpers.

**New in unified 1.2:** saved local call preparation/checklists, grounded property research (not invented sold comps), richer property facts, smarter compound/address-only imports, reviewed fill-empty-only enrichment, local rule refresh and a **backup-first, per-person reviewed bridge for both existing databases**. Source compared: GitHub `f96bc3d25b4aea4def3e1122a2004c7bf56c04ad`. The unified tree is published to GitHub `main`; see [publication proof](docs/github-publication.json).

> **BOTH workspaces have important data.** The GitHub `backend/acquisitions.db` (UUID schema) is not interchangeable with this app's `data/acquisitions.db` (integer/Alembic schema). Never replace one with the other. Stop both apps, update the **old delivered 1.1 root** with `legacy/windows/UPDATE-WINDOWS.cmd`, then run `legacy/windows/MERGE-WORKSPACES.cmd` there to prepare a local review. Start the app and review separate/link/skip decisions in **Import Center** before approving. Keep originals/backups; do not upload customer DBs to chat. [Full both-database workflow and exact limits](docs/UNIFIED_MERGE.md).

**GitHub unified tree:** the original Next/UUID implementation remains available in the parent history at `f96bc3d25b4aea4def3e1122a2004c7bf56c04ad`. The active tree is the reviewed single-server unified application; its prebuilt UI is included. No company DB, source secrets, automatic cloud batch or unverified CRM-write mechanism is published. [Unification notes](docs/GITHUB_UNIFICATION.md).

**Private database backups (1.2.1, archived helpers):** `legacy/windows/UPLOAD-DATABASES.cmd` and `legacy/windows/RESTORE-DATABASES.cmd` prepare encrypted, integrity-checked backups of both original company DBs and push only ciphertext to a separate PRIVATE repository. Everyday protection is now built in: a verified nightly copy in `data/backups/` plus list/create/download/delete from **Settings → Runtime & backups**. The password is never uploaded. Raw DBs, WAL files, `.env` files and keys must never be attached to the public repo or a chat. [Instructions](docs/PRIVATE_DATABASE_BACKUP.md).

Current release verification: **240 backend passed + 1 explicit live-account skip; 20 frontend unit passed**; `ruff`, `tsc -b` and the production build clean. The Docker image is built and smoke-tested in GitHub Actions on every push (it must refuse a weak password, answer 401 without a token and 200 after sign-in), and the release archive is rebuilt with its checksum. The 17 browser workflows and the 1.1 migration evidence remain recorded in [docs/VERIFICATION.md](docs/VERIFICATION.md) as a 1.2 log; they were not re-run for this release. These are synthetic/local checks, not verification of your real databases, vendor accounts or a native Windows runtime.

> **ABSOLUTELY NO SELLER COMMUNICATION.** No SMS, email, calls, dialer, send controls, hidden outreach jobs or automated seller contact exists. Drafts are review/edit/copy only. CRM sync is strictly read-only. External lead creation, record edits/deletes, notes/status writes and public-form automation remain disabled.

Keys previously pasted into chat were **not copied into source, used against an account, put in the ZIP or configured in the preview**. Rotate exposed keys, then enter replacements locally in **Settings → Connections & AI**. Real Groq and REsimpli account access has not been verified here; provider requests were tested with synthetic mocks.

## Run it on this computer, and open it from any device at home

No server, no cloud account and no extra download. Extraction and one start file are enough.

1. Download and extract the **complete release ZIP**.
2. Open the inner `acquisitions-assistant` folder — the one containing `backend`, `frontend`, `scripts` and this README.
3. **Windows:** double-click `START-ACQ.cmd`. **Linux/macOS:** run `./start-acq.sh`.
4. The first run creates `.venv`, installs the locked dependencies, generates a strong password and prints:

```
  On this computer : http://127.0.0.1:8010
  From your phone  : http://192.168.1.24:8010

  Password (save it): Acq-xxxxxxxxxxxxxxxxxxxx

  Scan to open http://192.168.1.24:8010
  ████ ▄▄▄▄▄ █ ▄▄██▄▀█▄█ ▄▄▄▄▄ ████
```

5. Type the **From your phone** address on a phone or another laptop on the same Wi-Fi, or scan the QR code. Keep the window open; `Ctrl+C` stops the app.

The password is stored in `.env` (mode 600 on Linux/macOS) and asked once per device. Run `scripts/acq_desktop.py --show-password` to read it again, `--new-password` to rotate it, and `--local-only` to run without a password on this machine alone.

**If another device cannot connect**, the operating system firewall is blocking the port, not the app:

```powershell
# Windows, Administrator window, once
netsh advfirewall firewall add rule name="Acquisitions Assistant" dir=in action=allow protocol=TCP localport=8010
```

```bash
sudo ufw allow 8010/tcp     # Linux
```

Everything stays on your own network: no port is opened on the internet, nothing is uploaded, and the app still refuses unauthenticated requests. Full Arabic guide: [docs/DESKTOP_LAN_AR.md](docs/DESKTOP_LAN_AR.md).

### Windows scripts moved to `legacy/windows`

Deployment is Linux-only by decision ([docs/DEPLOY_SERVER_AR.md](docs/DEPLOY_SERVER_AR.md)). The old tunnel, updater and merge helpers now live in [legacy/windows](legacy/windows/README.md) and are **archived, not supported**; `START-ACQ.cmd` replaced `START-WINDOWS.cmd`. The merge of two legacy databases is documented in [docs/UNIFIED_MERGE.md](docs/UNIFIED_MERGE.md).

## Linux / macOS and developer build

Python 3.11+, `venv`, pip; Node 20.19+ or 22.12+ for rebuilding (prefer a supported Node LTS). Linux was tested with Python 3.13.16 / Node 20.20.2. macOS runtime was not exercised.

```bash
# Optional backend configuration; preserve any existing .env
[ -e .env ] || cp .env.example .env
bash scripts/setup.sh
.venv/bin/python scripts/run.py
```

Open **http://127.0.0.1:8000**. Setup installs locked Python dependencies, runs `npm ci`, type-checks/builds the frontend, migrates SQLite and initializes defaults. It **does not add sellers, enable integrations, contact anyone or download an AI model**. Startup also runs pending migrations; back up before upgrades.

The equivalent source rebuild on Windows uses `bash scripts/setup.sh` inside WSL/Git Bash and needs Node; the simpler prebuilt path above does not.

## First-use workflow

A new company database is **empty**—no hidden demo counts or seller seeds.

1. Import a reviewed seller CSV/XLSX in **Import Center**, or configure and verify read-only REsimpli access.
2. Map source statuses explicitly; unknown non-empty statuses stay **Unmapped source status**, not silently New.
3. Review source dates, contact history and contact restrictions. Unknown restrictions are **not permission to contact**.
4. Use **Daily Follow-ups** and profiles to record local notes, already-occurred call/offer/appointment outcomes, schedules and actual task completion.
5. Use local evidence rules freely. Optionally configure Groq and approve individual redacted requests.
6. Review every AI proposal against its evidence. Save organized notes only as a **separate local note** after confirming the output. Edit/copy drafts manually and use the approved company communication workflow **outside this app**.

## Connections & private keys

Go to **Settings → Connections & AI**. Business pipeline/priorities and runtime/backups have separate tabs.

- Enter a **replacement** Groq or REsimpli key in the corresponding password field and explicitly approve private backend storage.
- The key is transmitted to the local/authenticated backend once, saved in ignored **`.env.secrets`**, cleared from the form, and **never returned by an API, audited as a value, stored in browser storage or bundled**.
- Test statuses are separate from “key saved.” A saved key is not proof that an account works. The Groq key test requests the model list only; no seller context is included.
- Keys can be rotated or removed. Process environment variables take precedence and may override saved values; the UI warns when an override is active.
- `.env.secrets` is **plaintext**, not an encrypted vault. POSIX writes use mode 0600. Restrict Windows ACLs and use full-disk encryption. Back it up securely **separately** from SQLite.
- Only one private workspace/password is supported. Do not expose an unauthenticated backend or store keys in frontend files, logs, notes, URLs, Git or shared CSVs.

The `.env` file remains supported. No actual key belongs in `.env.example`.

## Groq: redaction → review → approval → human review

Groq is an **external cloud provider**. Optional local/rule features continue to work without it or any paid service. Groq availability, quotas and billing depend on your account; this app cannot promise zero provider charges. REsimpli API access may also depend on your existing vendor account/plan.

### Configure

1. Save a rotated/replacement Groq key locally.
2. Click **Test key · no seller data** to check documented model-list access.
3. Choose an available supported structured-output model; default `openai/gpt-oss-20b`. The supported alternative is `openai/gpt-oss-120b`. The app does **not** enable compound agents, browsing, code execution or tools.
4. Set a **UTC daily request cap** (default 30) and maximum output tokens (default 3,000). Failed/uncertain attempts count; matching cached local results do not consume a new call. This is a request/token cap, not an exact dollar budget.
5. Enable **manually approved Groq requests**. Enabling it is **not blanket approval to upload leads**.

Backend environment equivalents:

```dotenv
GROQ_ENABLED=false
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-20b
GROQ_DAILY_REQUEST_LIMIT=30
GROQ_MAX_OUTPUT_TOKENS=3000
```

### Per-lead workflow

Open **Seller profile → Analysis & drafts → Your reviewed AI workspace**:

- **Analyze with Groq:** structured facts, unknowns/conflicts and grounded lead summary. Original lead/property/CRM fields are not overwritten.
- **Organize notes:** a grounded proposal with evidence. A second human verification is required before **Save as a separate local note**. Original notes remain unchanged; saving is idempotent and does not imply contact or CRM writeback.
- **Draft with Groq:** a natural American English proposal based on an actual callback or source motivation. Current DNC/unknown restrictions and insufficient relationship context block it. No generic filler, company offer or invented prior conversation is created as a fallback.

Each click first creates a **local-only preview**, not a provider call:

1. Known names/contact details/addresses and credential-like tokens are masked, structured name/phone/address records are omitted, and outbound references become anonymous `E001`-style IDs.
2. Review all selected text. Add extra literal redactions or exclude whole records. **Automatic masking is not a guarantee**—third-party names, unusual identifiers or sensitive context can remain.
3. Inspect the non-identifying constraints too (restriction status, explicit callback and placeholder flags). These are shown in the preview and accompany selected records.
4. Check the explicit approval checkbox, then **Approve & analyze/organize/draft with Groq**. Only then is the selected payload submitted over HTTPS to the fixed Groq endpoint.
5. A preview expires after 15 minutes and is invalidated by source/restriction/model/key changes. Duplicate approvals do not make duplicate calls. Edits while a provider request is running mark its result stale rather than silently applying it.
6. Review the **output**, not only the input. Exact quote/reference/numeric checks help grounding but **cannot prove semantic entailment or truth**. Unknowns remain unknown; model/source disagreements remain conflicts.

For drafts, name/address placeholders are filled **locally after validation**, not sent as personal fields to Groq. Raw model drafts cannot introduce digits, prices, calendar dates, unsupported names/placeholders, prior-conversation claims or purchase/closing commitments. The normal editable draft panel remains available. Changed context marks drafts stale and disables copy; DNC cannot be cleared locally. Copying is not sending and does not establish legal consent.

No Groq processing happens during CRM sync, import, startup, periodic jobs or normal rule analysis. There is no automatic batch upload. Provider errors/timeouts are sanitized; no automatic retry can silently duplicate costs. A timeout may have been processed by the provider and is labelled uncertain. Cached results can be reused; asking for a fresh result is an explicit quota-consuming choice.

### Official Groq references inspected

- [OpenAI compatibility / base URL](https://console.groq.com/docs/openai): `https://api.groq.com/openai/v1`, Bearer key header.
- [Structured outputs](https://console.groq.com/docs/structured-outputs): strict JSON schema on supported GPT-OSS models; required object fields and `additionalProperties:false`.
- [GPT-OSS 20B](https://console.groq.com/docs/model/openai/gpt-oss-20b) and [reasoning parameters](https://console.groq.com/docs/reasoning).

The client uses `GET /models` and `POST /chat/completions` only, one bounded request, strict schemas, no streaming/tools, low reasoning effort and no returned reasoning traces. The account/real model were **not called here**; mocks validate the implementation, not vendor operational readiness.

## REsimpli: primary CRM, documented read-only access

Official references: [developer documentation](https://developer.resimpli.com/) and [endpoint catalog](https://developer.resimpli.com/openapi-endpoints.json); reference copy `docs/resimpli-catalog.json`.

Base: `https://api.resimpli.com/api/v6/openapi`. Documented reads use **POST** and raw **`Authorization: <API_KEY>`**, not an invented Bearer prefix. Documented rate limit is 100 requests/key/minute; default app pacing is 90.

Read allowlist:

| Endpoint | Purpose |
|---|---|
| `/getUserInfo` | Account read/permission check |
| `/lead/list` | Page/limit 1–100; no invented modified-since filter |
| `/lead/details` | Stable `leadId` detail reconciliation |
| `/activityList`, `/callLogList` | Seller moduleId 1, lead subModuleId, type 1, page/limit |
| `/appointmentList` | Seller type 0 and documented seller subtypes only |
| `/getPipelineList` | Seller moduleType 1, page/limit |

### Live activation gate

A key alone is insufficient. The public catalog documents requests, **not your response envelope/paths or field semantics**. The included `backend/fixtures/response-adapter.json` is an unverified **fictional fixture contract** and cannot be saved as a verified live adapter.

1. Obtain authorized company API access and inspect real responses in your approved workflow. Do not paste actual keys or full seller payloads into chat.
2. Verify success-envelope semantics, stable IDs/relationships, pagination/end conditions, source dates/timezones, actual contact versus attempted contact, source DNC, status/outcome mapping and notes versus full transcripts.
3. Prepare the response-adapter JSON using those actual verified fields. In Connections, expand **Configure a verified private response adapter**, paste mapping JSON only, and explicitly assert account verification. The private file is stored under ignored `data/`.
4. **Check read access** calls only documented `/getUserInfo` through the configured adapter. A passing read check is **not full seller-sync verification**.
5. Type **ENABLE READ ONLY**, enable live reads, then perform/reconcile a **manual seller sync** against the actual CRM.
6. Only afterward enable periodic sync in Sync Status/Settings. Default target interval is 30 minutes; it runs only while this one-worker app is open.

Environment alternative:

```dotenv
RESIMPLI_API_KEY=
RESIMPLI_MODE=disabled
RESIMPLI_ADAPTER_PATH=
RESIMPLI_ADAPTER_VERIFIED=false
SYNC_ENABLED=false
SYNC_INTERVAL_MINUTES=30
SYNC_REQUESTS_PER_MINUTE=90
SYNC_MAX_PAGES=1000
SYNC_DEEP_REFRESH_HOURS=24
```

Saved scheduler settings in SQLite take precedence over initial environment defaults. Sync uses stable-ID upserts, list hashes and periodic deep detail refresh; activities/calls are read even if lead details are unchanged. Missing optional fields do not erase known values, local stage overrides persist, source property changes retain bounded history, and original import provenance remains separate. Source DNC is sticky—including older mapped call restrictions—and an older source call cannot replace a newer recorded outcome.

Four total attempts are allowed only for appropriate transient read failures; auth errors do not retry. `Retry-After` over 120 seconds stops rather than retrying early. Repeated pages, malformed totals/records, max-page exhaustion and resource failures are visible. Partial per-record commits are retained and re-reconciled by stable ID. Absence never deletes a record. Last attempt is separate from last **complete success**; failed/partial runs do not fake freshness. Full reconciliation can exceed 30 minutes on large accounts under vendor limits; freshness/capacity are not guaranteed without measurement.

### External creation / public links

**No CRM write is operational**, including `/lead/add`, edits/deletes or status/note changes. New seller creation requires further verified supported implementation, exact account IDs/fields, downstream automation safety, explicit selected approval, creation confirmation and uncertain-timeout reconciliation—not blind retries. There is no hidden enable-write switch.

No company public lead URL was supplied/inspected. It is not assumed to be an API, auth-free, bulk-suitable or automatable; no access-control/CAPTCHA bypass is implemented.

For now, use local import plus the reviewed **manual seller CSV handoff**. An authorized operator must use the company's approved REsimpli Leads import/mapping workflow/support and verify creation. The app does not upload/email the CSV; external status stays pending. [Official seller migration guidance](https://resimpli.com/blog/how-to-migrate-from-podio-to-resimpli-without-losing-data/) is a reference, not account verification. **List Stacking bulk upload is not represented as creating active seller leads.**

## Screens and UI/UX

| Screen | Implemented work |
|---|---|
| Dashboard | Actual DB counts, current stage/contact/follow-up/appointment cohorts, source/state/manager breakdowns, recent activity, honest sync health, empty state and clickable filters |
| Seller Leads | Name/formatted-phone/email/address/external-ID search, sorting/pagination, source/state/manager/stage/date/follow-up filters, safe CSV export, confirmed local bulk stage changes and browser-saved views |
| Seller profile | Primary contacts, multiple properties, restrictions, source/local dates/statuses, activity/call summaries, tasks, appointments, actual local outcomes/notes, analysis/drafts/source evidence/audit/history |
| Daily Follow-ups | Overdue/today/new uncontacted/callbacks/appointments today/offers response review/negotiations/upcoming/unscheduled/missing-info sections; explained deterministic priority and actual completion/reschedule/cancel |
| Appointments | Available source/local appointments and independent local results; no invitations or reminders sent |
| Import Center | Real CSV/XLSX mapping, inspection, normalized validation/duplicate review/selected approval, retry/history, rejection/report/handoff downloads |
| Reports | Recorded volume/funnel/contact/task/appointment/offer/contract/closing/age/observed-stage intervals, explicit cohorts, denominators, unknown/stale distinctions and zero-safe unavailable values |
| AI Insights | Source-grounded local rules/Ollama and individually approved Groq results; no background cloud calls |
| Sync Status | Real run states/counters/errors/last full success and one-worker periodic read settings |
| Settings | Connections & AI, Pipeline & priorities, Runtime & backups; private replacement keys, consent/caps, verified adapter and read-only controls |

Refreshed typography/spacing, forest-green navigation, responsive cards/tables, clearer hierarchy/states, contextual AI workbench and step-by-step privacy review. **Ctrl+K** opens real workspace search/quick navigation. Profile/settings tabs support arrow/Home/End keyboard navigation. Mobile navigation has focus management/Escape/closed-state inertness. Page/card/bar/modal/toast/hover/loading motion is bundled CSS; **prefers-reduced-motion disables it**. No CDN, remote fonts or generated UI screenshots are required.

## Import Center and preservation

CSV (UTF-8/BOM with Windows-1252 fallback and common delimiters) and `.xlsx`; not legacy `.xls`. Sheet names, first-row headers and counts are inspected. Limits default to 25 MB / 50,000 records / 150 columns. These are safety caps, not maximum-scale benchmarks. Formulas are not evaluated; decompression/sparse-row/header checks reject malformed workbooks. Populated XLSX cells without headers are rejected rather than silently lost.

Map name, primary phone/email, property address/type, source, original creation/last-contact dates/outcome/status, manager, seller motivation, asking/value/repair amounts, appointment/follow-up dates, notes, existing external ID, DNC and optional beds/baths/square feet/year. Required: name plus at least one phone/email/property/external ID. Missing data stays unknown, not invented. Original rows/meaningful original dates remain separate from normalized values and upload/recorded times.

Phones use E.164; emails lowercase; US states/territories normalize; ZIP leading zeroes are preserved; numeric/date errors are explicit. Full year/month/day and a four-digit year are required. Partial dates are rejected. Ambiguous dates require MDY/DMY choice. Naive values use the business timezone; ambiguous/nonexistent DST times require an offset. Date-only local midnight is a storage convention, not a proven original contact time. A timestamp beside No Answer/Voicemail/Wrong Number does **not** establish a connection.

Upload → select sheets/map columns/date order → preview originals/normalized/errors/candidates → select rows and explicit duplicate decisions → type **IMPORT LOCAL** → inspect per-row results. Mapping templates are reusable. **One mapping applies per selected-sheet preview**; different header schemas need separate passes/templates.

External lead ID is strongest; normalized contacts/full address support conservative exact/likely/same-seller-different-property/same-property-different-seller/existing-CRM/within-batch/new classifications. Uncertain matches require explicit skip/separate/link review. Linking adds a reviewed local relationship, not an overwrite of existing seller/CRM fields. No autonomous uncertain merge or geocoding/identity proof is claimed.

Checksums identify repeat files; per-row commits and unique linkage prevent reapproval duplication. Selected subsets stay partial while unresolved valid rows remain. Failed/interrupted rows are reviewable/retryable; changed files create a new batch and still undergo deduplication. If data changed after preview, new candidates are retained for review.

CSV exports protect formula-control prefixes, including unusual headers/values. This can prepend an apostrophe to `+`-prefixed phones; review destination phone formatting/mapping. Keep originals. Examples under `examples/` are fictional; nothing seeds the company DB automatically.

## Operational rules and analytics

- Pipeline stage, contact outcome/status and task status are independent. Default stages cover New through Closed/Nurture/Dead plus Unmapped safety state; labels/order/active flags/mapping are configurable without rewriting original source status.
- Contact requires actual explicit connection evidence/verified historical metadata. Unanswered calls, internal notes, pipeline names and administrative completion never prove contact. A later no-answer does not erase a prior actual connection.
- Source OR local DNC blocks ordinary outreach queues and drafts. Source DNC cannot be cleared locally. Unknown restrictions require evidence-based review, not automatic clearance. Reviewed-clear is not legal consent certification.
- Overdue means an explicit pending due time before business-local midnight. No due date means **unscheduled**, not overdue. Today is not overdue. DST day boundaries can be 23/25 hours; overdue priority counts local calendar dates.
- Queue priorities show base/manual score and bounded explicit callback/negotiation/appointment/overdue factors; cap 100. Known accepted/rejected offers leave the awaiting-response queue without automatically changing CRM/local stages.
- Dashboard task tiles count distinct eligible **leads**; queue sections may contain multiple tasks per seller. DNC is excluded from ordinary due-date outreach cohorts.
- Report date filters select the lead's **original creation-date cohort**; related task/appointment numerators are all dates on those leads, not a separately filtered event cohort. Unknown source dates are excluded only when filtering by date.
- Contact attempts use canonical non-note outcomes or verified last-contact dates. “No recorded attempt” is the exact complement; “never verified contact” is lack of connection evidence, not proof of never having contacted the seller.
- Conversion rates use recorded/current/observed stages and never infer missing historical intermediate stages. Offer/contract/closing stages are not revenue/transaction accounting. Offers/negotiations are stage plus actual notes/outcomes, not a formal offer ledger or automated valuation.
- Follow-up completion = completed / non-cancelled tasks on filtered leads. Scheduled appointments require actual scheduled status; imported date-only appointments remain unknown status pending confirmation.
- Age uses known original timestamps; future/unknown values stay separate. Stage-duration averages use completed locally observed intervals, not invented pre-import entries/current open intervals.
- Known stale activity requires a latest known contact/activity timestamp older than 30 elapsed days; unknown recency is separate. “No recent dated activity” includes both, not proof of no contact.
- Multi-state sellers can appear in several state buckets; do not sum as unique leads. Monthly volume groups stored original UTC months; daily filters/queues use the business timezone. Zero-denominator rates are **Unavailable**, not fabricated 0%.

## Local rules / optional Ollama

Rules, dashboard, imports and prioritization work without any AI model. Rules label unknowns/conflicts and meaningful-context hashes avoid reanalysis for timestamp-only sync changes. Local context uses at most 100 recent activities/20 appointments; older history remains stored but outside that extraction window.

Optional already-installed loopback Ollama:

```dotenv
OLLAMA_ENABLED=false
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=
```

No automatic model download or arbitrary external Ollama URL is allowed. Local model output is validated with references/quotes and falls back to rules on failure. Actual Ollama inference was not exercised; mocks covered its paths. Conservative local template drafts remain labelled **not AI**, distinct from `groq:<model>` drafts. Stale analyses/drafts are visible. Imported CRM/spreadsheet/note/model text is untrusted data, never executable instructions.

## Configuration / local security

**Sessions.** A signed-in browser receives a 12-hour signed token. **Sign out** cancels that token on the server immediately (the interface calls `POST /api/auth/logout`), not just in the browser. `POST /api/auth/logout-all` cancels every session on every device and persists the cutoff, so a restart cannot resurrect an old token. Successful and failed sign-ins and sign-outs are written to the audit log — never with the password itself.


Important variables in `.env.example`: `DATABASE_URL`, `APP_TIMEZONE` (default America/New_York, explicitly the company business timezone), `APP_HOST`/`APP_PORT` (127.0.0.1/8000), `APP_ACCESS_PASSWORD`, `SESSION_SECRET`, integration/AI flags and limits.

Backend settings precedence: process environment > private `.env.secrets` > `.env` > defaults. Normal users use the default private file; the test runner may supply a private-file location within its disposable DB directory. No credentials are placed in the release.

For deliberate remote preview/network exposure only:

```bash
# First configure APP_ACCESS_PASSWORD with at least 12 characters privately.
.venv/bin/python scripts/run.py --host 0.0.0.0 --port 8000
```

Use trusted HTTPS/VPN/tunnel. The launcher rejects remote binds without a strong password; API middleware rejects unauthenticated remote access. Loopback Host/DNS-rebinding protection, same-origin mutations, HMAC 12-hour sessions, no-store API responses and sessionStorage tokens are used. Logout clears the browser token; restart/secret rotation expires sessions. One workspace/password and **one worker** only; no roles/individual audit identities. SQLite is not encrypted. This is not a public multi-tenant deployment.

The Arena preview is explicitly authenticated, **fictional CRM data only**, Groq disabled/no account keys. Its generated ignored `.preview-password` is not in the download. Default company DB remains empty. No integration is represented as verified by that preview.

## Maintenance / backup / restore

**Automatic backups are on by default.** A verified copy is written every night at `BACKUP_HOUR_UTC` (default 02:00) into `data/backups/`, and the last `BACKUP_KEEP` (default 7) scheduled copies are kept. Manual copies are never pruned. Each copy is taken through SQLite's online-backup API against a read-only connection, checked with `integrity_check` and `foreign_key_check`, folded out of WAL mode, and only renamed into place after it passes — a failed copy is discarded, never left behind.

Manage them in **Settings → Runtime & backups**: create one now, download it, or delete it (with an explicit confirmation). The same endpoints are available to the interface:

```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8010/api/backups
curl -X POST -H "Authorization: Bearer <token>" http://127.0.0.1:8010/api/backups
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8010/api/backups/<name> -o copy.db
```

Disable with `BACKUP_ENABLED=false`, change the hour with `BACKUP_HOUR_UTC`, keep more with `BACKUP_KEEP` (1–90).

Run from project root; on Windows use `.\.venv\Scripts\python.exe` instead of `.venv/bin/python`.

```bash
.venv/bin/python scripts/run.py --port 8010
.venv/bin/python scripts/manage.py migrate
.venv/bin/python scripts/manage.py check
.venv/bin/python scripts/manage.py backup --output backups/acquisitions-2026-10-21.db
```

Backup uses SQLite's consistent backup API, checks integrity and refuses to overwrite. Do not raw-copy a running WAL database. Treat imports, exports and backups as confidential seller data; use restricted OS permissions, full-disk encryption and encrypted offline backups.

**Stop all app/scheduler instances before restoring** a trusted backup:

```bash
.venv/bin/python scripts/manage.py restore --input backups/acquisitions-2026-10-21.db --confirm "RESTORE LOCAL DATABASE"
.venv/bin/python scripts/manage.py migrate
.venv/bin/python scripts/manage.py check
.venv/bin/python scripts/run.py
```

Restore validates expected schema/integrity/FKs, keeps the input untouched and creates a dated pre-restore recovery backup of an existing destination. It cannot detect every external DB user; stop them yourself. Restore old backups then migrate before starting 1.2. Private `.env`/`.env.secrets` require a separate secure backup. Never restore synthetic preview data into a real company workspace.

### Explicit synthetic fixture workspace

```bash
RESIMPLI_MODE=fixture DATABASE_URL=sqlite:///./data/demo.db .venv/bin/python scripts/manage.py migrate
RESIMPLI_MODE=fixture DATABASE_URL=sqlite:///./data/demo.db .venv/bin/python scripts/manage.py fixture-sync --confirm "LOAD SYNTHETIC"
RESIMPLI_MODE=fixture DATABASE_URL=sqlite:///./data/demo.db .venv/bin/python scripts/run.py
```

This explicitly loads six fictional sellers with fixed source dates. The fixture banner stays visible. PowerShell can set the equivalent `$env:` values; remove overrides before returning to company use. No synthetic account success is a real CRM/Groq verification.

## Architecture / directory / schema

React 19/TypeScript/Router/Query, bundled CSS/lucide icons, Vite; FastAPI/Pydantic, SQLAlchemy 2, SQLite WAL/FKs, Alembic and APScheduler. HTTPX already handles the limited Groq API, so no paid SDK/cloud DB/model is required. A single FastAPI process serves the compiled SPA and relative `/api`; Vite rather than a second Next.js server keeps local deployment simple. No browser code calls a remote user's localhost service.

```text
backend/app/                  API, config, security, models, local scheduler
  routes_intelligence.py      private settings + approved cloud routes
  services/                   imports, leads, operations, reports, read-only CRM/sync, rules/Ollama
  services/cloud_ai.py         redaction, review digest/expiry/approval, limits, validation, local results
  services/groq_client.py      fixed-host strict-schema, no-tools, no-auto-retry client
  services/private_settings.py atomic private backend settings/adapter storage
backend/migrations/           initial schema + additive reviewed-cloud migration
backend/tests/                synthetic API/business/import/integration/privacy/maintenance tests
frontend/src/                 all pages, reviewed AI/settings UI, command palette, shared controls
frontend/e2e/                 actual-app browser workflows
scripts/                      startup, desktop launcher, maintenance and QA helpers
  acq_desktop.py              local app: password, LAN addresses, QR, browser
examples/                     fictional CSV/XLSX
START-ACQ.cmd                 native prebuilt launch (Windows)
start-acq.sh                  same launcher for Linux/macOS
.github/workflows/ci.yml      backend, interface, Docker and packaging checks
legacy/windows/               archived Windows helpers, not supported
docs/                         verification, Arabic guides, official references, licenses
data/                        generated private DB/adapter; excluded from the release
.env.secrets                  generated private keys/settings; excluded from the release
```

There are **19 application tables**, plus `alembic_version`: `leads`, `properties`, `lead_properties`, `activities`, `appointments`, `followups`, `ai_insights`, `drafts`, `import_batches`, `import_rows`, `mapping_templates`, `sync_runs`, `audit_log`, `stage_history`, `pipeline_stages`, `app_settings`, **`cloud_requests`**, **`call_plans`**, **`workspace_merges`**. External identities/checksums/row identities have uniqueness constraints; contacts/states/dates/activity/task lookups are indexed; relationships enforce FKs. Original/recorded/synced times and source/local/AI provenance remain separate.

Revisions: `daec27051e18` → `9e8b3c712f42` → **`0a6d91cf17b2`**. The middle migration adds the reviewed cloud-request ledger; the latest adds local preparation and workspace migration ledgers. Existing seller/source columns are not destructively changed. Cloud ledger stores redacted reviewed excerpts/state/usage and local result links, **not API key values**. It is not a communication queue.

Unknown-owner property-only prospects are counted as local lead records, not asserted to be distinct verified people. Their stored owner name stays blank; no marketing draft is prepared without actual identity and restriction evidence.

## Executed verification

See [docs/VERIFICATION.md](docs/VERIFICATION.md), JUnit files, `qa-summary.json` and `unified-upgrade-check.json` for current results and scope. Tests are executed before delivery, not merely proposed. Real account/Groq generation and native Windows runtime are **not** certified by mocks/Linux checks.

Repeat after installing dev dependencies/browser:

```bash
.venv/bin/ruff check backend scripts
.venv/bin/pytest --junitxml=docs/backend-test-results.xml
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test -- --reporter=default --reporter=junit --outputFile=../docs/frontend-test-results.xml
npm --prefix frontend run build
npm --prefix frontend audit
cd frontend
npx playwright install chromium
# Linux browser QA only if system libraries are missing:
npx playwright install-deps chromium
cd ..
.venv/bin/python scripts/test_browser.py --cloud-fixture
```

The browser runner uses a fresh temporary authenticated loopback DB and only fictional CRM records. `--cloud-fixture` invokes a separately guarded **synthetic no-network Groq harness**, not the product entry point. There is no real provider key or seller-data transfer. Without that flag the cloud-specific browser tests skip; normal local workflows remain testable. `--skip-build` reuses a compiled build. Never rerun raw Playwright against an old mutated DB and mistake expected state changes for failures.

## Troubleshooting / boundaries

- **Missing folder:** download/extract first, then use the inner root containing `scripts/run.py`; files do not appear automatically in `C:\Users\...`.
- **Returned PowerShell prompt after migrations:** not a successful running server. The logging defect in old archives is fixed (`disable_existing_loggers=False`), and Windows ANSI colors are disabled. Inspect the actual ERROR; try `--port 8010` for a busy port. See `docs/STARTUP_LOGGING_FIX.md`. No DB deletion/reinstall is indicated merely by a port conflict.
- **Groq disabled/not configured:** save a replacement key locally and explicitly enable approved requests. Preview/approval is still required. Model-list access is not a complete generation/account test.
- **Unknown/DNC draft blocked:** preserve source DNC; unknown permission needs company-approved evidence review, not legal-consent inference. A real callback/source motivation is also required.
- **Cloud output rejected/stale:** no primary data was overwritten. Inspect the result/error, source context, token/model availability and caps; prepare a new reviewed request if appropriate. No automatic retries.
- **No live adapter / partial sync:** correct safety gates or real mapping/resource errors. Last full-success time intentionally stays unchanged. Never use the fixture adapter to assert a real account contract.
- **Partial import:** unresolved selected/unselected valid or failed rows remain; review and retry. Correct invalid source values in a revised file. Different sheet headers need separate mapping passes.
- **Locked DB:** stop duplicate processes/workers and use the backup tools. Single worker only. No long scheduler soak or high-concurrency guarantee.
- **Clipboard unavailable:** iframe/browser policy may block Clipboard API; manually select/copy reviewed text. This never sends anything.
- **No Ollama/model:** expected; rules/local operations work. No automatic downloads.
- **Scale:** 2,000-row import was exercised, not the 50,000-row maximum or large-account 30-minute freshness. Queue/report cohorts are materialized in memory.
- **Data limits:** one normalized primary phone/email, selected mapped CRM fields rather than every unknown payload/secondary-contact roster, no formal financial offer ledger or pre-import stage/revenue reconstruction. Source summaries are not full transcripts.
- **Security/AI limits:** private plaintext local store, single-workspace auth, automatic redaction/quote checks not semantic/privacy certification, real account verification and human approval still necessary.

**Exact next action:** extract this release into a new folder → run `START-ACQ.cmd` (Windows) or `./start-acq.sh` → open the printed address on your computer → create a backup from **Settings → Runtime & backups** before importing anything → import a reviewed seller CSV in **Import Center** and approve only explicit decisions. Configure rotated keys locally in **Settings → Connections & AI** if you need Groq or REsimpli. Keep seller communication and CRM writes disabled.

## License

Project source: MIT (`LICENSE`). Third-party libraries and public REsimpli/Groq documentation retain their own rights; frontend runtime notices are in `docs/THIRD_PARTY_LICENSES.txt`. This project is not endorsed by those vendors.


## Rebuild and verify this release archive

After rebuilding/testing the UI, `python scripts/package_release.py` creates the public source + prebuilt UI ZIP and a SHA-256 checksum. It intentionally excludes every DB/snapshot/private environment/password file, dependencies and old logs. `python scripts/test_release.py --report docs/release-smoke-results.json` verifies the included file hashes and boots the extracted code in a path with spaces against a fresh, isolated, authenticated zero-seller DB. Both commands use the installed backend interpreter (`.venv\Scripts\python.exe` on Windows); no company source DB is used. Use `--replace` only when deliberately rebuilding an existing release ZIP. See [executed verification and remaining limits](docs/VERIFICATION.md).
