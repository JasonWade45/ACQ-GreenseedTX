# PROJECT STATUS — Acquisitions Assistant AI

**Last updated:** 2026-10-22 · **Overall state:** complete and verified locally (all ten
milestones delivered, all automated checks green; REsimpli integration **live-verified**
against the real account, including live lead creation via `/lead/add`)

Core promise enforced throughout: **the application never sends SMS, email or calls to
sellers — automatically or otherwise.**

---

## 1. Milestone status

| # | Milestone | State | Evidence |
|---|-----------|-------|----------|
| M1 | Environment discovery + REsimpli Open API v6 research | ✅ done | `docs/resimpli-openapi-endpoints.json`; Python 3.12.10, Node 24.19.0, npm 11.17.0, git 2.55.0, Ollama 0.34.4 (`llama3.1:8b`, `nomic-embed-text`) confirmed on the machine |
| M2 | Backend scaffold, config, schema, migrations | ✅ done | `backend/.venv` with all deps; Alembic migration `5009170ba90b_initial_schema` applied; `/api/health` → ok |
| M3 | Lead list / detail / search / filters / export / edit | ✅ done | `app/api/routes_leads.py`, `app/services/querying.py`; covered by `tests/test_leads.py` |
| M4 | REsimpli v6 client + read-only synchronisation | ✅ done | `app/services/resimpli_client.py` (real + mock), `sync_service.py`; **live run against the real account**: `test-connection` → `ok:true, mock:false`; full sync `result=success`, 704 leads fetched/created, 10,289 activities, 0 failed |
| M5 | Legacy CSV/XLSX import (inspect → auto-map → preview → commit) | ✅ done | `app/services/import_service.py`, sample files in `backend/sample_data/`; covered by `tests/test_sync_import.py` |
| M6 | Daily work queue, follow-ups, appointments | ✅ done | `app/services/workqueue.py`, `app/api/routes_work.py`; 10 ordered sections; outcome-driven completion |
| M7 | Local AI analysis + reviewed drafting (no-send) | ✅ done | `app/services/ai_service.py`; **Groq live-verified** (`engine: "groq"`, `openai/gpt-oss-120b`): analysis + follow-up drafts from real records, DNC/context refusals intact; background batch with paced 8k-TPM-safe runs; Ollama verified but disabled locally (CPU too slow), rules fallback otherwise |
| M8 | Dashboard metrics, reports, exports, settings, audit | ✅ done | `app/services/metrics.py`, `routes_reports.py`, `routes_settings.py`; funnel denominators documented; CSV export kinds: leads/aging/followups/activities |
| M9 | Next.js frontend + full verification pass | ✅ done | 10 routes render, `npm run lint` / `typecheck` / `build` all clean; backend tests green (59 at M9, **71** after M11/M12); `ruff check` clean |
| M10 | Property-fact extraction, pre-call plans, comps brief | ✅ done | `property_extract.py` lifts `propertyInfo`/`valuation`/`taxInfo`/`mortgageInfo` out of stored payloads (672/677 properties now have beds/baths/sqft/value/county/lat-lot); `call_plans` table + `GET/POST/PATCH /ai/call-plan/{id}` (Groq opener + tickable questions/points, persisted checkboxes, DNC/no-phone/thin refusals); `GET /leads/{id}/comps` = subject facts + ±20% criteria + Zillow/Redfin/Realtor links, comps array always empty (no MLS feed → never fabricated) |
| M11 | AI column mapping, missing-info report, name dedupe, external REsimpli push | ✅ done | `ai_service.ai_map_columns` (Groq fills only unmapped targets against real headers, rules win first) + `POST /imports/ai-map`; missing-info stats (`phone/email/address/name`) in the preview response and as amber tiles; name-level dedupe (`_norm_name` punctuation-free + SQL first-name / Python last-name fallback) marking `likely_duplicate`; commit optionally pushes each new lead to `/lead/add` (live account IDs in `KNOWN_LEAD_IDS`, overridable via `GET/POST /imports/external-config`) with keep-local-on-failure, phone guard and per-row error report; structured import report in the UI |
| M12 | Relaxed import rules, compound property parsing, CRM push report, git/GitHub delivery | ✅ done | any row with phone / email / name / address imports (address-only → warning + `never`, nothing invented); `extract_property_details` reads `4 & 2`, `3 & 1 and half`, `3 beds 3 baths 2,007 sqft`; `normalize_money` reads `$133,916 Redfin` / `200k` and **leaves ranges blank** instead of guessing; no-phone pushes reported as `skipped_no_phone` (not `failed`); **Upload list** button on `/leads`; first commit `10aff38` pushed to github.com/JasonWade45/ACQ-GreenseedTX |
| M13 | Camp Leads import completion: header fix, fill-only update path, smart targets, no-dup push | ✅ done | the owner's real 175-row `Camp Leads - Form responses 1.csv` now imports with every column (trailing-space headers `Seller's name ` / `Phone number ` were silently unmapped → 167 nameless/phoneless leads); `update_matched` commit fills only empty fields on the lead that owns the row's **property** (address target wins over the contact match); within-file phone duplicates on a *different* property flow into the DB dedupe instead of being hard-skipped; commit-time `person_already_in_crm()` guard + preview `person_in_crm` flag → a seller is pushed to REsimpli at most once across properties. **Real run:** 175 rows → first pass `imported 1 / updated 154 / pushed 30 / failed 0 / skipped_existing_crm 124`, second pass `updated 12 / pushed 0` → nameless import leads **167 → 2** (the 2 leftover rows have no name/phone in the source file: addresses `New Month`, `Enzo`); `ImportBatch.updated_count` column + migration `8d4f1a6c2b93`; frontend update checkbox / `updated` badge / report lines |

## 2. Verification evidence (run for this delivery)

| Check | Command | Result |
|-------|---------|--------|
| Backend lint | `backend> .venv\Scripts\python -m ruff check .` | **All checks passed** (0 errors) |
| Backend tests | `backend> .venv\Scripts\python -m pytest` | **76 passed** |
| Frontend lint | `frontend> npm run lint` (next/core-web-vitals) | **No ESLint warnings or errors** |
| Frontend types | `frontend> npm run typecheck` | **OK** (`tsc --noEmit`) |
| Frontend build | `frontend> npm run build` | **Compiled successfully**, 12/12 static pages |
| API live | `GET http://127.0.0.1:8000/api/health` | `{"status":"ok", ... "never contacts sellers"}` |
| API surface | `GET /openapi.json` | **53 paths**; `/docs` returns 200 |
| Pages live | `GET http://localhost:3000{/, /leads, /followups, /appointments, /import, /insights, /reports, /settings, /sync}` | **all 200** |
| REsimpli connection (live) | `POST /api/sync/test-connection` | `ok:true`, `mock:false` — real token accepted by `api.resimpli.com` |
| REsimpli sync (live) | `POST /api/sync/run` | `result=success`, fetched 704, created 704, failed 0 (8 pages, detail budget 800); health → **healthy**, `data_is_live:true` |
| Dashboard (live data) | `GET /api/dashboard/metrics` | `total_leads=704`, not-contacted 81, stage tiles populated (new 491 / dead 155 / follow_up 46 / offer_made 7 / under_contract 5) |
| Reports (live data) | `GET /api/reports/summary` | contacted 277 (connected-type), contact attempts 556, stages/funnel populated |
| Work queue (live data) | `GET /api/work-queue` | 200, sections populated from 704 real leads |
| Lead search (live data) | `GET /api/leads?q=peter%20vale` | 1 hit — `Peter Vale`, `(214) 636-1338`, source `Cold Calling` |
| AI engine (live) | `GET /api/ai/status` | `engine:"groq"`, `available:true`, model `openai/gpt-oss-120b` (key verified against `api.groq.com`) |
| AI analysis (live) | `POST /api/ai/analyze/{id}` | `engine=groq`, grounded summary (pulled the $60k/$80k offer from activity records); refusals still fire for thin / dead / DNC leads |
| AI draft (live) | `POST /api/ai/draft/{id}` | `engine=groq`, real draft referencing `230 N Seed Farm Rd`; explicit refusal when context is insufficient |
| AI background batch | `POST /api/ai/analyze-batch?background=true` + `GET /api/ai/analyze-progress` | worker thread + live progress; paced 16 s/call under the 8000 tokens/min free-tier ceiling, HTTP 429 retried with `Retry-After` |
| Property extraction (live) | offline backfill over stored payloads | 704 payloads parsed, 672 properties filled (beds/baths/sqft/year/lot/lat/value/county), `extra` blocks merged block-wise — 0 errors |
| Call plan (live) | `POST /api/ai/call-plan/{id}` | `engine=groq`, 4 s: opener with address, 8 questions (3 required: motivation/timeline/price), 5 talking points citing extracted facts (equity, mortgage, build year); `PATCH` persists `asked`/`used` flags; DNC + no-phone + thin-lead refusals verified |
| Comps brief (live) | `GET /api/leads/{id}/comps` | subject 4bd/2.5ba/2522 sqft + criteria (beds 3–5, sqft ±20%, price ±20% of estimate, same ZIP, sold ≤12 mo) + 5 sourced value refs + portal links; `comps: []` always |
| Relaxed import + parser (live) | upload → preview → commit (4-row property list mimicking the owner's 175-row file) | `rejected: 0` (was 175/175 before), address-only warnings fire, `4 & 2`→4/2, `3 beds 3 baths 2,007 sqft`→3/3/2007, `3 & 1 and half`→3/1.5, `$133,916 Redfin`→133916, both ranges left blank with warnings; commit `imported 4, pushed 0, failed 0, skipped_no_phone 4, errors []`; smoke leads removed after verification |
| AI column map (live) | `POST /api/imports/ai-map` (weird-header CSV: `Owner`, `Prop Addr`, `Call This Number`, `Mailbox`, `Why They Selling`, `What Is It Worth`) | `engine:"groq"` — mapped phone/email/address/motivation/estimated_value correctly, rules mapping (`Owner` → manager) preserved, 0 unmapped headers |
| `/lead/add` auth probe (live) | `ResimpliClient.add_lead({})` with the real key | **HTTP 400** (validation rejection, not 401) — token accepted, endpoint reachable, no lead created |
| External lead push (live) | upload → preview → commit with `external.enabled` (1 clearly-labelled test row) | local `imported: 1`, `external: {pushed: 1, failed: 0}`; created lead `6ad959c494b0f7730e7b11ae` verified back via `/lead/details`: `createdVia:"OPENAPI"`, pipeline `Active Leads`, status `New Leads`, `contactData` = `ZZ Test Lead` / `+12145550142` / email ✓ (kept as a visible test record — see next steps) |
| Camp file, real run (live) | upload `uploads/65a454c570fa6d95_Camp Leads - Form responses 1.csv` → auto-map (0 unmapped essential headers) → preview → commit `update_matched + external.enabled` → repeat | pass 1: `imported 1 / updated 154 / skipped 20 / failed 0`, `external: pushed 30, skipped_no_phone 1, skipped_existing_crm 124, errors []` (30 real `/lead/add` calls, every id read back); pass 2: `updated 12 / pushed 0`; nameless import leads **167 → 2** (source rows without any name/phone); both passes re-verified from the DB (targets = the address twins, CRM leads untouched) |

Test suites: `tests/test_leads.py`, `tests/test_sync_import.py`,
`tests/test_import_ai_ext.py`, `tests/test_work_ai.py`,
`tests/test_callplan_comps.py`, `tests/test_reports_settings.py`, and
`tests/test_resimpli_shapes.py` (pins the live `/lead/list`, `/lead/details`,
`/activityList` and `callLogList` payload shapes captured from the real account),
with `tests/conftest.py` (isolated temp SQLite DB, mock REsimpli client, unreachable
Ollama → deterministic rules, Groq key blanked).

## 3. Bugs found and fixed during verification

| Bug | Where | Fix |
|-----|-------|-----|
| `Query.outerjoin(..., isouter=True)` raised `TypeError` — address/keyword search was broken | `app/services/querying.py:126` | use `outerjoin()` (LEFT OUTER by default in SQLAlchemy 2) |
| `refresh_lead_rollups` ran with `autoflush=False`, so a just-created follow-up was invisible → `next_followup_at` never set and “overdue”/“due today” stayed empty | `app/services/leads.py:59` | `db.flush()` before recomputing rollups |
| `local_today()` annotated with undefined `date` (`F821`) | `app/services/pipeline.py:276` | imported `date` from `datetime` |
| Disabling the scheduler reported the old cadence | `app/scheduler.py` | `configure_scheduler()` stores the requested interval even when stopped |
| Sync status always reported the env interval, ignoring the interval saved in Settings | `app/services/sync_service.py:sync_state` | reads `sync_interval_minutes` / `sync_enabled` from stored settings |
| `ai_status()` lacked the `disclaimer` key the Insights page renders | `app/services/ai_service.py` | added explicit advisory/no-send disclaimer |
| Unused imports/variables, ambiguous `l` names (55 lint errors) | 15 files | `ruff --fix` + targeted renames (`l` → `lead` / `last_name`) |
| Structured note collections were stored as a Python `repr` string and leaked into AI summaries ("Notes on file: `[{'text': ...}]`") | `app/services/sync_service.py:upsert_lead_from_api` | `_looks_stringified_collection()` clears/repairs legacy garbage; notes collections stay as timeline activities |
| `full_name` stayed NULL when the API only returned first/last → blank names in export/sort | `sync_service.py:upsert_lead_from_api` | composes `first + last` when no display name is supplied |
| Ollama ran every analysis into HTTP 500 (`failed to allocate buffer of size 8589934592`) and then fell back after a ~40 s stall | `app/services/ai_service.py`, `app/config.py` | send `OLLAMA_NUM_CTX=2048` with each generation, record the failure, and put the model in a cooldown so the UI stays instant; prompts are truncated to fit the context window |
| Local model inference measured unusable on this CPU-only box (3B ≈265 s, 8B >290 s / OOM) | `backend/.env` | `AI_ENABLED=false` with an explanatory comment; rules engine runs in ~120 ms and the Insights page states why |
| Frontend type errors (unknown-as-ReactNode, wrong `apiPost` arity, null-unsafe access) | import/reports/sync/lead pages | typed row accessors, query-string in path, null guards |
| First live sync dropped names, phones, source status and created dates: the real `/lead/list` rows carry no names (they live in `/lead/details` under `contactData[]`), status/title fields are `mainStatusTitle`/`crmQuestionTitle`, and `leadCreated` is epoch **milliseconds** parsed as a date | `app/services/resimpli_client.py:normalize_lead_payload`, `app/services/normalization.py` | unwrap `leadData`, read the primary/seller contact record, title fallbacks, `_epoch_to_datetime()` (ms/s/µs with a sanity range); user map from `/userList` → assigned manager |
| Lead `raw_payload` was never persisted, so extractor bugs could only be caught by re-hitting the API | `sync_service.py:upsert_lead_from_api` | stores the normalized raw payload (JSON column); local repair scripts re-derive everything offline |
| Activities lost their type/direction/comment: `comment` is HTML, `direction` is `outgoingCall`/`incomingSms` (not `inbound`/`outbound`), `activityType` is a numeric code (1/8/9/10/11/14/16), `status` is sometimes an object `{_id,name,color}` that stringified into `outcome`, and call/SMS logs arrive with no comment at all | `resimpli_client.py:normalize_activity_payload` | direction-derived types + numeric-code map, `strip_html()`, outcome scalarized to the status name, comment-less call/SMS logs labelled from their own `to`/`from` fields (e.g. `Outgoing call to +1214…`); 10,289 activities re-derived offline, 0 errors |
| Reports counted DNC and no-answer-only leads as “contacted” (`total − never_contacted` = 623) while the stated definition promised connected-type statuses (277) — funnel rates inflated | `app/api/routes_reports.py:summary` | `contacted` now counts `is_contact` statuses from `CONTACT_OUTCOMES`, matching the definition; contact_rate 0.8849 → 0.3935 on live data |
| Groq output occasionally arrived as UTF-8 decoded latin-1 (`What’s` → `Whatâ\x80\x99s`, C1 controls) — non-deterministic, corrupted stored plans/insights (one row was double-encoded again by a round-trip) | `app/services/ai_service.py` (model output path) | `_repair_mojibake()` sanitizer on every Groq/Ollama/JSON extract (C1-control tell, 4-pass for stored double-encoding) + one-off DB repair across insights/drafts/call_plans; verified `U+2019` intact, 0 C1 cells remain; unit-tested |
| First test file with no fixtures failed at setup: `clean_db` purged tables before the session-scoped `client` ran migrations — alphabetical file order made it look random | `tests/conftest.py` | `init_db()` (idempotent `create_all`) at conftest import; alembic-in-tests falls back cleanly |
| Name-level dedupe missed identical sellers like `O'Brien` vs `obrien`: the normalizer stripped punctuation **and** re-inserted spaces into glued runs | `dedupe.py:_norm_name` | punctuation removed without space insertion (SQLite never tokenises on it anyway) + Jr/Sr/II/III/IV suffixes dropped; name match runs before the address fallback |
| Commit rolled the whole batch back when a REsimpli push failed, silently losing the already-clean local rows | `import_service.py:commit_import` | pushes are per-row with no transaction rollback: local lead is always kept, failure recorded under `external.errors`, auth failure sets a sticky `auth_dead` flag that stops further pushes in the batch |
| A clean property list (175 rows, address + facts only, no contact data) was rejected 175/175 by the contact requirement — unusable for owners who import raw list pulls | `import_service.py:normalize_row` | reject only rows with **nothing** (no phone/email/name/address); address-only rows import with a warning and `contact_status: never` |
| Compound cells (`4 & 2`, `3 beds 3 baths 2,007 sqft`, `$133,916 Redfin`) all failed numeric parsing, and ranges like `200k to 250k` would have needed a guess | `normalization.py` | `extract_property_details()` fills beds/baths/sqft from compound text (multi-unit ambiguity left blank with a warning); `normalize_money()` takes a single embedded number and refuses multi-number strings — never invents a figure |
| CSV headers with a **trailing space** (`Seller's name `, `Phone number `) matched nothing: the mapper strips headers but DictReader kept the raw key → the real Camp file mapped address/MV/Zillow but silently lost every seller name and phone (167 leads imported nameless and never pushable) | `import_service.py:_read_rows` | each DictReader row key is stripped before matching; aliases added (`sellersname`, `killernameputyournamehere`, `mv`, `bedsbath…`) |
| Duplicate rows in a preview carried no target, so the commit skipped them instead of filling the matched lead — and the same seller's *second property* was hard-skipped as a within-file duplicate, leaving its property lead nameless forever | `import_service.py:preview_import` / `FileSeenIndex` | preview stores `matched_lead_id` (address match preferred over contact match) + `person_in_crm`; a within-file phone/email duplicate **on a different address** now falls through to the DB dedupe (`check()` reports which key matched and `by_row` compares addresses) |
| A phone repeated on a second property in the same commit could be pushed to REsimpli twice: the preview-time `person_in_crm` flag cannot see a lead pushed moments earlier in the same batch | `import_service.py:commit_import` | `person_already_in_crm()` re-checks the DB immediately before every push (phone → any lead with an `external_id`, excluding the row's own target); counted as `skipped_existing_crm` |

## 4. Known limitations / deliberately unfinished

1. **Source-data gaps in the real account (not app bugs)**: 25/704 leads have no name
   in REsimpli (the list view shows `(no name)`), only 24/704 leads carry an email
   address at all, `/appointmentList` returned zero appointments (unverified whether
   the account has any), and 73 activities arrive with no `direction` (kept as unknown;
   151 activities have unmapped codes → type `other`).
   Mock mode remains available as a sample-data fallback (`RESIMPLI_MOCK=true`); the
   local `.env` runs live. Key location (verified in UI): **Settings → "Webhook - API
   Token" → API Token tab → Generate Open API Token** — not the Zapier token, not the
   Webhook tab. Live rate limit is documented as 500 req/min (raised 1 Oct 2026);
   the client throttles to `RESIMPLI_RATE_LIMIT_PER_MINUTE` (default 100, set to 400
   locally).
2. **External push skips rows without a valid 10-digit phone**: REsimpli's `/lead/add`
   requires one, so phone-less rows are imported locally only (counted as
   `skipped_no_phone` in the commit report — not a failure). Account IDs now ship as
   live-extracted defaults
   (`KNOWN_LEAD_IDS`) and are overridable per account through
   `GET/POST /api/imports/external-config` / Settings; `/lead/add` itself is
   live-verified. One test lead (`ZZ Test Lead`) remains in the account as proof —
   delete it in REsimpli when convenient.
3. **No REsimpli write-back of local edits** (stage changes, notes, follow-ups) — the
   documented v6 surface has no lead-update endpoint at launch. Local is the working copy;
   REsimpli stays the source of truth for what it knows.
4. **No “modified since” filter** → each sync is a full lead-list reconciliation with a
   bounded per-lead detail budget (`SYNC_DETAIL_BUDGET`, default 250).
5. **No authentication** — the server binds `127.0.0.1`; add auth before any network
   exposure.
6. **Two address-key formats coexist**: import writes pipe keys
   (`2203 cripple creek drive|arlington|tx|76014`) while the REsimpli sync writes
   space keys (`3736 hyde park drive mesquite tx 75150`), so a CRM lead and its
   import twin for the *same* address never match each other on address (phone
   matching carries the dedupe; the import twin's pipe key always resolves to
   the twin). Unifying `sync_service` onto `address_key()` would let address
   matching collapse those pairs — deliberately deferred. Likewise 2 Camp rows
   (addresses `New Month`, `Enzo`) carry no name/phone in the source file and
   stay as `(no name)` leads — nothing was invented for them.
7. **Groq free tier = 8000 tokens/min** → sustained throughput ≈ 3–4 analyses/min;
   batch runs self-pace (`GROQ_BATCH_SPACING_SECONDS=16`) and a full 704-lead
   upgrade happens across repeated 200-lead background runs. Single-lead analysis
   and drafts are instant. Local Ollama remains **disabled** on this CPU-only
   machine (`AI_ENABLED=false`: measured ~265 s/analysis with `llama3.2:3b`,
   >290 s / HTTP 500 with `llama3.1:8b`); flipping `AI_ENABLED=true` re-enables it
   as the fallback (integration verified: valid structured JSON at context 2048).
   The rules engine (~120 ms) still backs everything up.
8. **Comps are criteria + portal links, not a comps feed**: no documented REsimpli comps
   endpoint exists and no MLS/ATTOM/Realtor key was provided, so the comps card shows
   subject facts, sourced value references (AVM/tax/equity from the lead payload) and
   deterministic search bands with one-click Zillow/Redfin/Realtor openings — the
   `comps` array stays empty by design (fabricated sold prices would be worse than none).
   Plugging in a comps API later only replaces the `links` block (`app/services/comps.py`).
9. Python `datetime.utcnow()` deprecation warnings remain (suppressed in pytest config);
   harmless on 3.12, worth migrating to timezone-aware helpers later.

## 5. Suggested next steps

1. **Field-fidelity spot-check** (key already configured and verified): open a handful
   of leads side by side in REsimpli and in this app — name, phone, source status,
   stage mapping, timeline dates — and watch REsimpli's **View Logs** tab during a sync
   to confirm request arrival. Re-run **Sync now** any time (`backend/.env` →
   `SYNC_DETAIL_BUDGET` controls per-lead detail enrichment; 800 covered all 704 leads).
2. Delete the `ZZ Test Lead` test record in REsimpli (created during live push
   verification), or ask for a delete button backed by the documented `/lead/delete`.
3. Decide on a comps data source (ATTOM / PropStream / Realtor feed key) — the comps
   card is ready to swap `links` for a real feed.
4. `git init` + first commit (`.gitignore` and docs are ready).
5. Optional: author-side auth (single user, local) before sharing the port beyond localhost.
6. Optional: timezone-aware datetimes and an ESLint CI hook.

## 6. Live processes currently running

| Process | Command | Log |
|---------|---------|-----|
| Backend API | `backend\run_backend.cmd` → `.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` | `backend\uvicorn.log` |
| Frontend dev | `frontend\run_frontend.cmd` → `npm run dev` (Next 15.1.6, port 3000) | `frontend\next.log` |

## 7. Delivery checklist

| Requirement | Status |
|-------------|--------|
| Seller-lead management (list, filter, detail, edit, export) | ✅ |
| REsimpli Open API v6 integration (documented contract, read-only sync, throttling, mock fallback) | ✅ **live-verified** against the real account — 704 leads / 10,289 activities, 0 failures, `ok:true, mock:false` |
| Legacy lead import (CSV/XLSX, rules + AI column mapping, missing-info report, preview, name/address dedupe, rejected rows) | ✅ **Groq mapping live-verified** on odd headers |
| External CRM creation on commit (`/lead/add` push with live account IDs, per-row error report, keep-local-on-failure) | ✅ **live-verified** — 1 test row created and read back from REsimpli |
| Daily follow-up queue (overdue first, callbacks top, outcome-driven completion) | ✅ |
| AI analysis + message drafting | ✅ **Groq live-verified** (analysis, drafts, background batch); rules fallback; Ollama verified but disabled on this CPU box |
| **No automatic seller communication of any kind** | ✅ enforced in code, tests and UI copy |
| Lint + typecheck + tests green | ✅ ruff / eslint / tsc / 76 pytest |
| `PROJECT_STATUS.md` + `README.md` maintained | ✅ this file + `README.md` |
