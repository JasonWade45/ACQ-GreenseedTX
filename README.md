# Acquisitions Assistant AI

A local-first CRM layer for a US residential real-estate **acquisitions** team: seller-lead
management, REsimpli Open API v6 synchronisation, legacy lead import, a prioritised daily
follow-up queue, local AI analysis/drafting, pre-call plans (opener + tickable question
checklist built from the lead's records) and a comps search brief for the subject property.

> **This application never contacts sellers.** It does not send SMS, email, or calls —
> automatically or otherwise. Message drafts are stored for a human to review and copy into
> whatever approved outreach tool you use. Pipeline stage, contact outcome and follow-up
> status are separate concepts, and completing a follow-up only records what *you* did.

---

## 1. Requirements

| Component | Version used | Notes |
|-----------|--------------|-------|
| Python    | 3.12+        | virtual env at `backend/.venv` |
| Node.js   | 18+ (tested on 24) | `frontend/node_modules` already installed |
| SQLite    | bundled      | `backend/acquisitions.db` |
| Ollama *(optional)* | 0.34+ | local model; rule-based fallback works without it |
| REsimpli API key *(optional)* | v6 | without it the app runs in **mock mode** |

## 2. Run it

**Terminal 1 — backend (port 8000):**

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

(or simply `backend\run_backend.cmd`, which logs to `backend\uvicorn.log`)

**Terminal 2 — frontend (port 3000):**

```powershell
cd frontend
npm run dev
```

(or `frontend\run_frontend.cmd`, which logs to `frontend\next.log`)

Open <http://localhost:3000>. The API is at <http://127.0.0.1:8000> and interactive docs
are at <http://127.0.0.1:8000/docs> (53 routes).

Migrations run automatically on startup (Alembic → `backend/alembic`).

### Verify a fresh install

```powershell
cd backend
.\.venv\Scripts\python.exe -m ruff check .     # lint
.\.venv\Scripts\python.exe -m pytest           # 68 tests
cd ..\frontend
npm run lint                                   # eslint (next/core-web-vitals)
npm run typecheck                              # tsc --noEmit
npm run build                                  # production build
```

## 3. Configure

Copy `backend/.env.example` → `backend/.env` (a working local `.env` is already present).
Secrets live **only** there; `.env` is git-ignored.

```ini
# REsimpli -> Settings -> "Webhook - API Token" -> API Token tab
# -> "Generate Open API Token" (NOT the Zapier token, NOT the Webhook tab)
RESIMPLI_API_KEY=

# Force the built-in sample-data client even if a key exists:
RESIMPLI_MOCK=false

# Client-side throttle (help centre: 500 req/min since 1 Oct 2026; conservative default 100)
RESIMPLI_RATE_LIMIT_PER_MINUTE=400

# Groq cloud AI (see section 3.1) — primary engine when set:
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b
GROQ_BATCH_SPACING_SECONDS=16

# Local AI (see section 3.1)
AI_ENABLED=true
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.1:8b
OLLAMA_NUM_CTX=2048
OLLAMA_TIMEOUT_SECONDS=90

TIMEZONE=America/New_York
```

Restart the backend after editing. `Settings → Runtime configuration` shows what was
actually loaded (never the key itself).

### Getting data in

1. **REsimpli sync** — *Sync* page → **Sync now**. With a key this pulls the whole
   account (verified here: 704 leads / 10,289 activities); in mock mode it returns 5
   sample leads. Sync is **read-only**: reading never changes REsimpli (the only
   outbound write anywhere in the app is the optional `lead/add` push below).
2. **Legacy CSV/XLSX** — *Import* page → upload → **AI column mapping** (rules first,
   then Groq fills only the headers you left blank — engine shown as a badge; edit any
   mapping by hand), preview with duplicate detection (**in-file + against the CRM**,
   exact / same-address / same-seller-name) and a **missing-info report**
   (phone / email / address / name), then commit. Sample files:
   `backend/sample_data/sample_seller_leads.csv` (and `.xlsx`).
   A rejected-rows CSV and a REsimpli-shaped template CSV are downloadable per batch.
3. **External CRM push (opt-in per batch)** — the commit panel can also create every
   new lead in **REsimpli itself** via the official `/lead/add` (live account IDs are
   pre-filled and editable under *External CRM*; rows without a 10-digit phone are
   skipped there but kept locally). Local stays authoritative: a failed push never
   rolls back your imported rows and each error is listed in the **import report**
   (imported / duplicates / rejected / pushed / failed). No message of any kind is
   ever sent — creation only.

### 3.1 AI: Groq (fast, recommended) → Ollama (local) → rules

Analysis and message drafts work with whatever engine is available — nothing is
blocked when no model is configured:

* **`GROQ_API_KEY` set** → `engine: "groq"`: cloud analysis/drafts in ~1–2 s
  (key: <https://console.groq.com/keys>). The free tier allows ~8000 tokens/min,
  so batch runs pace themselves (`GROQ_BATCH_SPACING_SECONDS`, default 16 s between
  calls) and retry on HTTP 429. The *Insights* page shows live batch progress.
* **Ollama available** → `engine: "ollama"` plus the model name, and results are
  still advisory text a person must review.
* **Neither** → `engine: "rules"`: deterministic, instant, evidence-linked analysis
  and draft templates.

**Batch organisation:** *AI insights* → **Analyze / upgrade leads** processes up to
200 leads **in the background** per run (you can leave the page) and automatically
upgrades older rule-based insights to the live model. Re-run to continue through
the full list. Do Not Contact leads are never drafted for.

Ollama is the local fallback (`ollama pull llama3.1:8b` to enable). Settings that
matter on a CPU-only box:

| Setting | Why |
|---------|-----|
| `OLLAMA_NUM_CTX=2048` | Ollama's 8192 default makes llama-server fail with HTTP 500 `failed to allocate buffer of size 8589934592` (KV-cache OOM). |
| `OLLAMA_TIMEOUT_SECONDS` | Ceiling for one generation; a timeout puts the model in cooldown instead of stalling every request. |
| `OLLAMA_FAILURE_COOLDOWN_SECONDS` | After a failed generation the model is skipped for this long so the UI stays responsive. |
| `AI_ENABLED=false` | Turn local model execution off entirely and run on rules. |

Measured on the delivery machine (CPU only, no GPU):

* `llama3.2:3b` — ~265 s for one analysis (valid JSON, but not interactive)
* `llama3.1:8b` — >290 s / HTTP 500 at Ollama's default 8k context

so `backend/.env` keeps `AI_ENABLED=false` for the **local** model on this machine
— **Groq is the active engine**. Enable Ollama (`AI_ENABLED=true`) on a GPU box if
you want a local fallback.

## 4. Pages

| Route | Purpose |
|-------|---------|
| `/`           | Dashboard — tiles with click-through filters, stage/contact breakdown, open work |
| `/leads`      | Search, filter (stage, source, manager, state, follow-up state, missing data), export |
| `/leads/[id]` | Full profile: property facts, timeline, follow-ups, appointments, AI analysis, drafts, **call plan** (script + question checkboxes) and **comps brief** |
| `/followups`  | Daily work queue — overdue first, callbacks at the top, outcome-based completion |
| `/appointments` | Scheduled walkthroughs and outcomes |
| `/import`     | Upload → AI column map (Groq badge, editable) → preview with missing-info tiles + dedupe → commit → import report, with optional push to REsimpli |
| `/sync`       | Sync health, run history, scheduler, connection test, reference data |
| `/insights`   | AI status, batch analysis of changed leads |
| `/reports`    | Conversion funnel with explicit denominators, aging, volume, by-source, CSV export |
| `/settings`   | Follow-up rules, source-status → stage mapping, runtime config, audit log |

## 5. REsimpli Open API v6 — what is documented

Captured in `docs/resimpli-openapi-endpoints.json`.

* Base URL `https://api.resimpli.com/api/v6/openapi`, header `Authorization: <API_KEY>`
  (raw key, **no** `Bearer`).
* All endpoints are `POST` with JSON bodies; pagination is `{page, limit}` (`limit ≤ 100`).
* Rate limit: HTTP `429`; the help centre documents 500 req/min (raised 1 Oct 2026).
  The client throttles to a conservative configurable value
  (`RESIMPLI_RATE_LIMIT_PER_MINUTE`, default 100) and retries with exponential backoff.
* Used here: `getUserInfo`, `userList`, `lead/list`, `lead/details`, `activityList`,
  `callLogList`, `appointmentList`, plus `lead/add` when an import commit opts into
  the external push (live account IDs built in, overridable per account).

**Documented limitations that shape this app:**

* No update-existing-lead endpoint at launch → sync is read-only locally.
* No “modified since” filter on `/lead/list` → each sync is a full reconciliation of the
  lead list, with per-lead detail enrichment budgeted (`SYNC_DETAIL_BUDGET`) to the most
  relevant leads.
* Response body shapes are unpublished → every extractor is tolerant, the raw payload is
  stored, and no undocumented fields are invented.
* `/lead/add` needs account-specific `pipelineId` / `mainStatusId` / `marketId` /
  `marketingCampignId` [sic]; this app ships the values extracted from the live
  account as defaults (`KNOWN_LEAD_IDS`) and accepts your own through
  `GET/POST /api/imports/external-config` (Import page → *External CRM* panel).
  Verified live: a pushed test lead came back with `createdVia: "OPENAPI"` and the
  full contact record.

Verified operational against this machine's account (2026-10-21): **Test connection**
returned `ok: true, mock: false`, and a full sync ingested 704 leads and 10,289
activities with 0 failures. Every extractor is pinned to the captured response shapes in
`backend/tests/test_resimpli_shapes.py`, the raw payload of each record is stored for
offline re-derivation, and no undocumented fields are invented.

## 6. Project layout

```
acquisitions-assistant/
├── backend/
│   ├── app/
│   │   ├── api/           # routes_* modules mounted under /api
│   │   ├── services/      # resimpli_client, sync, import, workqueue, ai, metrics, ...
│   │   ├── config.py      # pydantic-settings (.env)
│   │   ├── db.py          # SQLAlchemy engine / sessions
│   │   ├── main.py        # FastAPI app, lifespan migrations, CORS
│   │   ├── models.py      # leads, properties, activities, followups, audits, ...
│   │   └── scheduler.py   # optional periodic sync (APScheduler)
│   ├── alembic/           # migrations
│   ├── sample_data/       # sample CSV + XLSX to try the importer
│   ├── tests/             # 68 pytest tests (isolated temp DB, mock client, live-shape pins)
│   ├── pyproject.toml     # ruff + pytest config
│   └── .env               # local secrets (git-ignored)
├── frontend/
│   ├── app/               # Next.js App Router pages
│   ├── components/        # Sidebar, UI primitives
│   └── lib/api.ts         # typed API client
├── docs/resimpli-openapi-endpoints.json
├── PROJECT_STATUS.md      # milestone status, verification evidence, known gaps
└── .gitignore
```

## 7. Safety rules encoded in the product

* No endpoint in the API sends, schedules or queues a message to a seller.
* Do Not Contact blocks drafts, cancels open follow-ups, and removes the lead from
  outreach queues.
* Completing a follow-up requires an explicit outcome and returns
  *“Recorded locally. No message was sent by this application.”*
* AI refusals are explicit (DNC, insufficient context) instead of generic replies.
* CSV exports neutralise spreadsheet formula injection (`csv_safe`).
* The server binds `127.0.0.1` by default — add authentication before exposing it.
