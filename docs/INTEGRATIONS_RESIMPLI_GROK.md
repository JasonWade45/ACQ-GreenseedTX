# REsimpli and Grok: what this build does, and what is verified

This document is the honest companion to the REsimpli and Grok integration added on
`arena/8ccac04b-acq-greenseedtx`. It says what the
code does, which facts it rests on, and — with equal care — what nobody has been able to
check yet. Everything below was verified against documentation and against mocked servers.
**No request in this build has ever reached a real REsimpli account or a real xAI account.**

Last reviewed: 2026-10-29.

---

## 1. The shape of the thing

Four parts, one rule.

| Part | What it adds | What it is allowed to do |
| --- | --- | --- |
| Push | A mapping table, an eligibility gate, a dry run, and one create | Create a lead in REsimpli. Nothing else. |
| Notes | A `[GreenSeed]` note that travels in the create's `comment`, and a local outbox for leads that already exist | Write a note **once**, at creation. Copy otherwise. |
| Grok | Follow-up drafts, checklist suggestions, an advisor note | Ask xAI for text a person reviews. |
| UI | Six lead cards, five dashboard counters, one CRM & AI page | Show state. Type the confirmation. |

The rule: **nothing here sends anything to a seller.** There is no SMS, no email, no dialer,
no send button, and `messages.sent_at` stays dropped. A draft can be edited and copied. A
push creates a CRM record for a person to work from. The two ideas are not connected.

### Where the code lives

| File | Lines | What it holds |
| --- | --- | --- |
| `backend/app/services/resimpli_write.py` | 467 | `WRITE_PATHS`, `CrmDefaults`, `ten_digit_phone`, `lead_phones`, `lead_address`, `lead_apn`, `property_type_for`, `contact_flags`, `build_lead_payload`, `candidate_lead_ids`, `ResimpliWriter` |
| `backend/app/services/crm_push.py` | 571 | `PushSettings`, `queue`, `plan_push`, `search_existing`, `execute_push`, `push_batch`, `link_existing`, `sync_status`, `payload_hash` |
| `backend/app/services/crm_notes.py` | 188 | `note_for_new_lead`, `note_for_existing_lead`, `notes_for_lead`, `NOTE_PREFIX` |
| `backend/app/services/ai_grok.py` | 428 | `GrokClient`, `ADAPTERS`, `record_run`, `strip_pii`, `sanitize`, `cap_status`, `monthly_estimate`, `model_for`, `AI_FIELDS` |
| `backend/app/services/ai_features.py` | 510 | `draft_followup`, `suggest_checklist`, `advise`, `prompt_for`, `preview_for`, `latest_advice` |
| `backend/app/services/checklists.py` | 277 | Two templates, `apply_to_lead`, `progress`, `set_item`, `add_item`, `open_items` |
| `backend/app/routes_crm.py` | 539 | 25 routes, all behind the existing auth |
| `backend/app/route_allowlist.py` | 104 | Every route that may leave this machine, in one place |

Tests: 134 new backend tests across seven files (`test_crm_write` 27, `test_crm_push` 16,
`test_crm_notes` 14, `test_ai_grok` 16, `test_ai_features` 16, `test_checklists` 13,
`test_routes_crm` 22), plus 10 in `test_routes` guarding the audit and the allowlist, plus
14 frontend tests in `frontend/src/crm.test.tsx`. All mocked: `httpx.MockTransport` for
REsimpli, `httpx.MockTransport` for xAI, a temporary SQLite file for the database. Full
backend suite at this revision: **526 passed, 15 skipped**; frontend: **41 passed**.

---

## 2. REsimpli v6: what the API actually documents

Sources, both read on 2026-10-29:

1. The live endpoint catalogue: `https://developer.resimpli.com/openapi-endpoints.json`.
2. The help-centre article on the Open API:
   `https://help.resimpli.com/en/articles/16915306-open-api-and-integrations` (updated 1 Oct 2026).

Base URL `https://api.resimpli.com/api/v6/openapi`. Every endpoint is a `POST` with a JSON
body and the header `Authorization: <API key>` — the raw key, no `Bearer` prefix.

### 2.1 The Leads section, read in full

Eleven endpoints, all `POST`:

| Path | Title |
| --- | --- |
| `/lead/add` | Create lead |
| `/lead/delete` | Delete lead (soft) |
| `/lead/details` | Lead details |
| `/lead/list` | List leads |
| `/lead/addContact` | Link an existing contact to a lead |
| `/lead/addContactDetails` | Create a contact from details and link it |
| `/lead/removeContact` | Unlink a contact |
| `/lead/changePrimaryContact` | Change the primary contact |
| `/lead/statusUpdate` | Move a lead to another pipeline status |
| `/lead/addTag` | Add tags |
| `/lead/removeTag` | Remove tags |

**There is no endpoint that adds a note or comment to an existing lead.** The word `comment`
appears exactly once in this section: as an optional body field of `/lead/add`, described as
"Optional comment".

Two consequences for this build:

- **A note for an existing lead cannot be written through the API.** The local outbox
  (`crm_note_outbox`) records it with `state = "blocked"` and the reason "REsimpli has no
  note endpoint (v6)"; the Notes card offers Copy. That is the whole Part B design, and it
  remains correct against the current catalogue.
- **The help-centre article is now stale.** It says the Open API does "create, delete and
  read leads" and that notes, statuses and tags are "planned for a future update". The
  catalogue contradicts it: status changes and tag changes are documented today. Where the
  two disagree, **the catalogue wins**, and the article should not be quoted as an inventory.

### 2.2 `/lead/add`, field by field

Required: `contactDetails.phoneNumbers` (1–10 entries, each `phoneNumber` a 10-digit number),
`propertyType` (`land` or `residential`), `marketingCampignId`, `marketId`, `pipelineId`,
`mainStatusId`. `apn` becomes required when `propertyType` is `land`.

Optional and used here: `contactDetails.firstName`, `contactDetails.lastName`,
`contactDetails.emails`, `address` (the property address), `comment`.

Optional and deliberately not used: `tagIds`, `isHotLead`, `referenceId`, `preferenceAnswers`,
`leadCreated`, `mailingAddress`, the eight social-URL fields, `birthDate`, `anniversaryDate`,
`company`, `companyIds`.

Three details worth stating because they are easy to get wrong:

- **`marketingCampignId` is misspelled in the API and is sent exactly as spelled.** The
  setting is called `marketing_campign_id` for the same reason. "Fixing" either would send
  the wrong field name.
- **`firstName` is optional.** The code sends a first name only when the lead has one. No
  placeholder, no `"Unknown"`, no `"Owner"` — nothing is fabricated to fill the field.
- **There is no `doNotCall`, `doNotText` or `doNotEmail` field on `/lead/add`.** The approved
  plan said to pass those flags when a restriction exists. The live schema does not have
  them, and inventing undocumented fields in someone's CRM is exactly the kind of thing this
  build refuses to do. So a restricted lead is **blocked**, never pushed
  (`contact_flags()` still computes the flags and `build_lead_payload()` carries them
  defensively if such a lead ever reaches that line, but the eligibility gate always fires
  first). Blocking is stricter than flag-passing, and it is what the code actually does.

### 2.3 `/lead/list`, the search used before every create

Body: `searchStr` ("Search string (lowercase). Allows empty or null"), `filterData.mainStatusId`,
`filterData.pipelineId`, `page`, `limit` (1–100).

What the catalogue does **not** say is how `searchStr` matches — against a name, an address,
a phone number, all three, or only as a prefix. This build therefore never trusts the search
to be the decision. It sends at most three queries (`MAX_SEARCHES`): the first two phone
numbers, then the street name. Whatever comes back is compared **locally** against a
normalized address key and against exact 10-digit phone digits, and **any plausible match on
either blocks the create**. If a search cannot be run at all, the push is blocked with
`crm_search_failed` rather than attempted blind.

---

## 3. The write boundary

`WRITE_PATHS = frozenset({"/lead/add"})`.

That is not a comment; it is enforced. The writer refuses any other path before a socket is
opened, and `backend/tests/test_crm_write.py` asserts that `/lead/delete`, `/lead/statusUpdate`,
`/lead/addTag` and a handful of invented paths are all rejected client-side. It is the same
pattern the read-only sync client already uses with its 7-path `READ_PATHS` allow-list.

The status and tag endpoints now exist. **This build still does not call them.** Refusing a
capability is a product decision, not a technical one: a person manages the CRM, and this
application creates a lead and stops. Deleting a lead is not offered anywhere.

### 3.1 Eligibility gates, in order

`build_lead_payload()` is a pure function: it reads the lead, the account IDs and nothing
else. A lead that fails a gate is *blocked*, with a reason code the UI translates.

| Reason | When | What unblocks it |
| --- | --- | --- |
| `needs_phone` | No phone at all | Run skip trace, review a phone |
| `invalid_phone` | Phones exist, none is a valid 10-digit US number | Fix the number |
| `missing_address` | No property address | Add an address |
| `land_without_apn` | `propertyType = land` and no APN | Add the APN (none is invented) |
| `do_not_contact` | Lead is marked do-not-contact | Never. Restricted leads stay local. |
| `missing_crm_defaults` | The four ObjectIds are not configured | Settings → CRM push settings |
| `already_pushed` | A mapping with `state = pushed` exists | Nothing; it is done |
| `exists_in_crm` | The duplicate search found a plausible match | Link it (`/crm/link`) |
| `crm_search_failed` | The duplicate search could not run | Retry when the CRM answers |
| `writes_disabled` | `CRM_WRITES_ENABLED` is false | Turn it on deliberately |
| `confirmation_required` | Review mode and no typed confirmation | Type `PUSH TO CRM` |
| `outcome_unknown` | Timeout or 5xx after the body was sent | Check the CRM by hand |
| `rejected_credentials` | 401/403 | Fix the key |
| `rejected_payload` | Any other 4xx | Read the message and fix the data |
| `rate_limited` | 429 with a wait longer than 120 s | Retry later |

An address-only lead is queued as `blocked: needs phone (run skip trace)` and becomes
eligible automatically once a reviewed phone exists.

### 3.2 Duplicate prevention

Three layers, in the order they run:

1. **The mapping table.** `crm_pushes` holds one row per lead: the REsimpli id, the hash of
   exactly what was sent, the state, the last error, the attempt count and the timestamps.
   A lead with `state = pushed` is never pushed twice.
2. **The live search.** Immediately before any create, the writer asks `/lead/list` about the
   address and each phone number. A plausible match writes a `SyncConflict` row, returns
   `exists_in_crm`, and creates nothing. This is what survives a database restore: the
   mapping is local and can be lost, the CRM's contents cannot.
3. **Never retrying an unknown outcome.** A connect failure is retried (nothing was sent). A
   read timeout or a 5xx is not: the lead may exist. The state becomes `outcome_unknown` and
   a person checks. Retrying would be the one bug that fills a CRM with duplicates.

`/crm/link` is the escape hatch: when the match *is* the same seller, a person records that
fact, the conflict is resolved, and the mapping flips to `pushed` without a second create.

### 3.3 Not overwriting, ever

There is no update path in the writer, so "never overwrite" is a property of the shape of the
code rather than a check that could be forgotten. The only fields sent are the ones the
catalogue documents for creation.

### 3.4 Rate limits, retries, isolation

- Pacing reuses `SYNC_REQUESTS_PER_MINUTE` (clamped to 1–100) between calls.
- `ConnectError` is retried up to four attempts with exponential backoff and jitter.
- `429` honours `Retry-After`; a wait longer than 120 s becomes `rate_limited` rather than a
  silent stall.
- One audit row per attempt, and one `crm_pushes` row per lead, so a batch failure is always
  attributable.
- `push_batch` isolates failures: one lead's error is recorded and the next lead proceeds.
  The response counts pushed, failed and blocked; it never rolls back the local data.

### 3.5 Modes

`review` (the default) requires the typed phrase `PUSH TO CRM` for a single push and for a
batch. `auto` exists as a setting and is off by default. A single-lead push in review mode is
the route the UI uses first, so one record can be tested before any batch.

---

## 4. Notes: once, at creation, or not at all

`crm_notes.note_for_new_lead()` builds a plain-text note prefixed `[GreenSeed]` from the
fields enabled in `NOTE_FIELDS`, hashes it (`note_hash`, SHA-256), and stores a
`crm_note_outbox` row. Two outcomes:

- **New lead** → the same text travels as `comment` on `/lead/add`, and the row is marked
  `delivered` with `delivered_via = "lead_add_comment"`.
- **Lead already in the CRM** → the row is marked `blocked`, with the reason. The Notes card
  shows the text and a Copy button.

Notes are deduplicated on `(lead_id, note_hash)`, so re-opening a profile does not pile up
copies. Nothing polls, nothing retries, and no third-party bridge is used (Cotlet and similar
were explicitly rejected).

---

## 5. Grok: drafts, suggestions, advice

### 5.1 The surface, and the one-file switch

`ai_grok.ADAPTERS` holds two adapters:

| `GROK_API` | Endpoint | Body |
| --- | --- | --- |
| `responses` (default) | `POST /v1/responses` | `input`, `instructions`, `text.format = {type: "json_schema", name, schema, strict: true}` |
| `chat_completions` | `POST /v1/chat/completions` | `messages`, `response_format = {type: "json_schema", ...}` |

Both send `store: false` — xAI's Responses API stores by default, and a lead's situation has no
business being retained server-side for this use. Because the two shapes live behind one
adapter, switching is a single setting, not a refactor.

### 5.2 Models and money

Model names are settings, never constants: `GROK_FOLLOWUP_MODEL`, `GROK_CHECKLIST_MODEL` and
`GROK_ADVISOR_MODEL`, all defaulting to `grok-4.3`. `grok-4.7` is selectable for the advisor.

Documented list prices used by `monthly_estimate()` (per million tokens, from
`https://docs.x.ai/developers/pricing`):

| Model | Context | Input | Output |
| --- | --- | --- | --- |
| `grok-4.3` | 1M | $1.25 | $2.50 |
| `grok-4.7` | 500k | $2.00 | $6.00 (cached input $0.50; ≥200k context $4/$12) |
| `grok-4.6`, `grok-4.5` | — | $2.00 | $6.00 |

The Settings panel shows an estimate with its basis stated: `planned_volume` (expected calls
per day × expected tokens × list price) or, when there is any history, `observed_last_30_days`
(priced from the runs actually recorded). It is labelled an estimate because that is what it is.

### 5.3 Cost control and graceful degradation

- `GROK_DAILY_REQUEST_LIMIT` defaults to **20** and is enforced before every call; the counter
  is the `grok_runs` table, counted from midnight UTC. The cap is on by default, not opt-in.
- Timeouts (`GROK_TIMEOUT_SECONDS`, default 45) and bounded retries with exponential backoff.
- A `429` from xAI backs off rather than hammering; a spent cap, a missing key or a disabled
  switch returns a clear message and the application keeps working. No screen depends on xAI
  being reachable: the cards render, with the AI parts simply absent.

### 5.4 What leaves this machine

- `AI_FIELDS` lists eight candidate fields (address, property facts, lead type, priority,
  equity, flags, contact history, recent conversation). `GROK_AI_FIELDS` chooses the subset —
  by default everything except the conversation text.
- Every string is passed through `strip_pii()` before it is sent: emails become
  `[EMAIL REDACTED]`, phone numbers become `[PHONE REDACTED]`, and anything shaped like a
  credential (`sk-…`, `xai-…`, `gsk-…`) becomes `[CREDENTIAL REDACTED]`.
- `POST /api/leads/{id}/grok/preview` returns exactly the instructions and payload that would
  be sent, after stripping, without calling anyone. The preview and the real call share one
  function (`prompt_for`), so they cannot drift apart.
- Logs never contain the prompt, the response body, or a key. Only the id, model, purpose,
  token counts, duration and state are written to `grok_runs`; the sanitized payload and the
  parsed output are stored in the database for the "what was sent" record, not in the log.

### 5.5 The three features

**Follow-up draft.** Grok writes one message; it goes through the existing
`templates.validate_message` and `draft_gates` — the same validator every other draft path
uses, cold-mode rules included. The result is a draft in the existing queue, copy-only.

**Checklist suggestions.** Two templates are created automatically on first use (Lead Manager,
Acquisition) and copied onto every lead. A suggestion run proposes items one at a time; each
is `pending` until a person accepts or rejects it. Accepting creates a `lead_checklist_items`
row with `source = "ai"`; rejecting keeps the record but puts nothing on the lead. Nothing is
ticked automatically.

**Advisor.** One call returns strict JSON: `situation_summary`, `next_steps`, `do_not`,
`risks`, `exit_strategy {name, reasoning, missing_information}`, `confidence`. The schema is
validated as a Pydantic model with `extra = "forbid"` and a `Literal` confidence, the call is
retried **once** on invalid JSON, and then it fails safely with a readable message. Every
response is stored with its timestamp, model id and an input hash; the card shows the model
and the time next to the reasoning, and carries a "decision support only" label plus the
compliance reminder. It is presented as an opinion with stated confidence, not a verdict.

---

## 6. Verified, and not verified

### 6.1 Verified

| Claim | How |
| --- | --- |
| The catalogue documents no note endpoint for existing leads | Read the whole Leads section, 2026-10-29 |
| `comment` is an optional field of `/lead/add` | Catalogue, `bodyFields` |
| `firstName` is optional; `propertyType` is `land`\|`residential`; `apn` is required for land | Catalogue |
| `marketingCampignId` really is spelled that way | Catalogue |
| `/lead/list` takes `searchStr`, `page`, `limit ≤ 100` | Catalogue |
| Read-only sync paths, base URL and raw-key auth | Catalogue + existing client |
| xAI supports `json_schema` with `strict` on both surfaces; `store` defaults to true | `docs.x.ai` |
| List prices per million tokens | `docs.x.ai/developers/pricing` |
| 429 means back off; per-model rate limits exist | `docs.x.ai/developers/rate-limits` |
| Every write, every read and every AI call in this build is mocked in tests | The suite |
| The route audit sees inside included routers and fails on send-shaped routes | `test_routes.py` |
| No route outside the allowlist can reach the network | `route_allowlist.undeclared()` |

### 6.2 Not verified — read this before switching anything on

1. **The success payload of `/lead/add` is undocumented.** The writer records the new lead's
   id if it can find one (`_id`, `id`, `leadId`, `lead_id`, a bare string), and stores the
   mapping with no id when it cannot. Duplicate safety does **not** depend on that id: it
   depends on the search that runs before every create. A live smoke test should confirm the
   shape and, ideally, let the id be captured.
2. **How `searchStr` matches is undocumented.** If it does not match addresses or phone
   digits the way we assume, the local comparison still runs on whatever comes back, but a
   match could be missed. The mitigation is that a miss leads to a create, not to data loss.
   A live test should search for a known lead by address and by phone and read what returns.
3. **Whether `comment` renders as a note in the CRM UI.** The field is documented; where it
   appears in the interface is not. Someone should create one test lead and look.
4. **Whether a given account accepts your four ObjectIds** (campaign, market, pipeline,
   status). Only a live attempt answers that; that is exactly why review mode exists and why
   the first push is one lead with a typed confirmation.
5. **Race conditions.** A lead created by someone else between the search and the create is
   still possible. The window is one request wide, and the search is the last thing that runs
   before the create; it cannot be closed without an idempotency key the API does not offer.
6. **No xAI call has ever been made from this repository.** Token counts, durations and costs
   are documented figures and mocked responses.
7. **`docs/resimpli-catalog.json` in this repo is stale.** It predates the six newer lead
   endpoints (`addContact`, `addContactDetails`, `removeContact`, `changePrimaryContact`,
   `statusUpdate`, `addTag`, `removeTag`) and omits the `max: 10` bounds. The live catalogue
   is the source of truth; the checked-in copy should be refreshed with a new capture.
8. **The APN never reaches the CRM, because it is never stored.** `property_facts.EXTRA_FACTS`
   has no `apn` key, so an imported APN is dropped and every land lead blocks as
   `land_without_apn` until someone types one. This is a gap, not a bug in the push: adding
   `"apn"` to `EXTRA_FACTS` is a one-line change plus a test, and it has been deliberately
   left for a decision rather than slipped in.

---

## 7. Settings, and how to turn it on

Push settings are stored in `app_settings` under the key `crm_push`:
`mode`, `marketing_campign_id`, `market_id`, `pipeline_id`, `main_status_id` and `note_fields`.
"Load from my account" reads three documented lists (`marketingCampaignList`, `marketList`,
`getPipelineList`) and prints them; it copies nothing automatically, because the first entry in
a list is not necessarily the right one.

Environment and private settings:

| Variable | Default | Meaning |
| --- | --- | --- |
| `CRM_WRITES_ENABLED` | `false` | The master switch for any create |
| `RESIMPLI_MODE` | `disabled` | `live` is required before a create is attempted |
| `RESIMPLI_API_KEY` | — | Never logged, never returned, never echoed |
| `GROK_ENABLED` | `false` | Enables the three AI features |
| `GROK_API_KEY` | — | Same handling as above |
| `GROK_API` | `responses` | `responses` or `chat_completions` |
| `GROK_FOLLOWUP_MODEL` / `GROK_CHECKLIST_MODEL` / `GROK_ADVISOR_MODEL` | `grok-4.3` | Model per purpose |
| `GROK_DAILY_REQUEST_LIMIT` | `20` | The cap, counted per UTC day |
| `GROK_AI_FIELDS` | seven of eight | Which fields may be sent |

`GROK_AI_FIELDS` is a configuration value: the CRM & AI page shows the current subset, and it
is changed in the environment or the private settings file. There is no checkbox editor for it
in the interface yet; the read-only list is deliberate until someone asks for the editor,
because a per-field switch that silently fails to save is worse than no switch.

### A safe first live test

1. Leave `CRM_WRITES_ENABLED=false`; confirm the Push Queue lists leads with reasons.
2. Fill the four ObjectIds from the "load from my account" output.
3. Preview one lead. Read the body. Confirm the note and the hash.
4. Set `CRM_WRITES_ENABLED=true` and `RESIMPLI_MODE=live`. Push **that one lead** with the typed
   confirmation. Look at it in REsimpli: the address, the phone digits, the comment.
5. Preview the same lead again. It should now say `already_pushed` — no second create.
6. Only then consider a batch, and only then consider `auto`.

---

## 8. What this deliberately does not do

- No SMS, email, call, dialer, send control or automated seller contact of any kind.
- No CRM update, stage change, tag change, task or appointment write, and no delete.
- No fabricated data: no invented first names, no invented APNs, no invented ObjectIds.
- No third-party bridge for notes.
- No secrets in code, logs or responses.
- No live keys, no live calls, and `data/acquisitions.db` is never touched by the tests.

The Arabic documentation in this repository covers deployment and operation. This build has no
translation layer, so the interface stays in English; the new components use logical CSS
properties and mark seller-supplied text `dir="auto"`, which means the layout mirrors correctly
under right-to-left text without pretending the product is localised.
