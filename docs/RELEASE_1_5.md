# Acquisitions Assistant — 1.5.0 (Data Syndicate intake, cold outreach, replies)

**Released 2026-10-29.** Version 1.5.0 completes the Data Syndicate development line
(1.4.0 was never published) and adds the work that makes an address-only vendor list
usable: a reviewed skip-trace loop, explained priority, cold drafts built from a
template library, reply classification, a configurable cadence, a daily briefing and a
second verified backup location.

The safety boundary is unchanged and is asserted in code and in the route table: **no
SMS, no email, no calls, no dialer, no send control and no automated seller contact
anywhere.** Drafts are review/edit/copy only, the CRM stays read-only, and every write
stays on this computer.

## What is new

### 1. One draft route, one reachable backups route

- `/api/leads/{id}/draft` was registered twice: the relationship-draft handler was
  served first and the template handler was dead code. It is now a **single**
  handler that chooses relationship or cold drafting from the lead, the request and
  `outreach_mode`.
- `GET /api/backups/config` was declared after `GET /api/backups/{name}` and was
  therefore unreachable. The static route is declared first and the parameter route
  is constrained to `.db` names.
- `app/route_audit.py` plus `backend/tests/test_routes.py` now fail the build on a
  duplicate registration, a shadowed static path, or any route that looks like a send
  control.

### 2. Data Syndicate imports (address-only, internal context)

- A dedicated **address-only import profile** (`profile=address_only`, or detected from
  the vendor's headers). A row needs a real property address; name and phone are
  allowed to be empty.
- Every vendor column with a meaning is read: property address, city, state, ZIP,
  county, lead type, sale likelihood, estimated equity, flags, compatible offers and
  recorded date, plus the extended property block (APN, lot size, tax values,
  mortgage balance, occupancy, condition). `Expand details` is ignored rather than stored as a field.
- Flags are parsed into a structured set (`free_and_clear`, `high_equity`,
  `senior_owner`, `absentee_out_of_state`, …). Unknown flags are kept verbatim and
  never dropped.
- The external key is `ds:<normalized address + ZIP>`, so re-importing the same list
  matches the existing lead instead of creating a duplicate.
- A lead with no verified owner name or phone is marked `needs_skip_trace`, reports
  `outreach_status = NEEDS_SKIP_TRACE`, never appears as a "call this seller" task, and
  cannot receive a draft.

### 3. Skip-trace loop (export → provider → import → review)

- `GET /api/skip-trace/export` writes only the address fields and the local lead key.
  The app never contacts a provider itself and stores no provider credentials.
- `POST /api/skip-trace/upload` matches every result row by lead key **or** normalized
  address, then shows matched, rejected and conflicting rows before anything changes.
- Invalid phone numbers, unknown addresses and invalid emails are rejected with a
  reason; a rejected row never creates a lead.
- Applying results requires typing `IMPORT LOCAL`. A phone number that came from the
  CRM is never replaced without an explicit per-row overwrite decision; skip-trace
  numbers are added instead.
- The matched lead keeps its stage when it has a local override, and moves to
  "not contacted" only when it was still new/unmapped.

### 4. Priority that can be explained

- The daily queue score is the recorded task priority plus: overdue days, explicit
  callback, negotiation stage, appointment stage, vendor heat, sale likelihood and a
  **negative-equity penalty**, clamped to 0–100. Every addition is listed under
  **Why this priority?**
- A new **Needs skip trace** queue section holds address-only leads, sorted by score.
- DNC/suppressed leads are still excluded from every ordinary section.
- Weights are edited in **Settings → Pipeline & priorities**; the lead profile shows
  the same score with its individual factors.

### 5. Cold outreach drafts

- `outreach_mode` is `relationship` (default) or `cold`. Cold mode skips only the
  relationship gate; the license check, DNC/suppression, restriction evidence,
  skip-trace and duplicate-draft gates all still apply.
- 13 template categories with two variants each (opener, probate, tax lien/lis
  pendens/HOA, divorce, absentee/corporate/trust, senior owner, owner-occupied,
  failed/expired listing, day 3/7/14 follow-ups, day 30 check-in, monthly touch).
- Category selection follows the lead's recorded flags, lead type and stage; the
  reasons are stored on the message and shown in the draft queue.
- The hard validator rejects: missing sender identity, missing company, missing
  street address, missing `Reply STOP to opt out`, emoji, URLs, dollar amounts,
  unfilled placeholders, false urgency words, duplicate opt-out text and anything
  over 320 characters. A draft that fails is saved as a draft **with its reasons**
  and cannot be approved.
- Sender name and company come from Settings and are written to the private `.env`
  block, not to the database.
- `POST /api/drafts/bulk` generates drafts for a reviewed tier or an explicit
  selection, requires `confirm: true`, and returns `bulk_copy: false` and
  `bulk_send: false`. There is no bulk copy and no send button.
- Template editor (`/templates`) validates a rendered sample before saving; **Restore
  defaults** is an explicit, audited action.

### 6. Replies and cadence

- Paste a reply on the lead profile. Rules run first and always win for a literal
  opt-out; the classifier labels it `INTERESTED`, `WANTS_PRICE`, `NOT_NOW`,
  `NOT_INTERESTED`, `WRONG_NUMBER`, `STOP`, `QUESTION` or `OTHER` with a confidence
  and the quoted evidence.
- Below 0.7 confidence the reply is flagged for a human read and the suggestion
  carries that note.
- A reply pauses the lead's cadence immediately — preparing another message for
  someone who just answered would be wrong. Suppression, stage changes and follow-ups
  are **suggestions** you confirm or dismiss; nothing is applied silently.
- Cadence days are editable in Settings (`[0, 3, 7, 14, 30, 60, 90, 120]` by default,
  1–24 ascending steps). The runner creates drafts and tasks and never sends.
- Scanning already-synced activity text for replies is a **manual** action
  (`POST /api/replies/scan`). Scheduled sync never classifies or writes anything.

### 7. Briefing, backups and restore

- The daily briefing shows, in this order: opt-outs needing human confirmation,
  replies needing action with confidence and evidence, follow-ups due, drafts
  awaiting review, drafts failing validation, leads needing a skip trace, stalled
  leads (14 days), sync conflicts and the last backup.
- A second backup folder can be configured (`PATCH /api/backups/config`), must be an
  existing writable absolute path, and every mirrored copy is verified with SQLite's
  `integrity_check`. A failed mirror reports `ok: false` with the reason and never
  deletes or replaces a good copy.
- Restore verifies the chosen file, copies it aside first, and rolls back to that
  safety copy if the restored database fails its own check.

### 8. Schema that cannot claim a send

`messages.sent_at` was never written by any code path. It is dropped
(`i1j2k3l4m5n6`), so the database schema itself cannot record that a message left the
machine. `test_release_smoke.py` asserts both the route table and the columns.

### 9. What this build adds on top of the plan

These are the gaps that a walk-through of the running app found after the features above
were written:

- **The cadence actually runs.** `[0, 3, 7, 14, 30, 60, 90, 120]` was editable but nothing
  ever advanced a sequence. A daily job (`12:15 UTC` by default, `CADENCE_ENABLED`,
  `CADENCE_HOUR_UTC`) now prepares the drafts that are due and stops itself on a reply, a
  suppression, an appointment, a closed stage, an out-of-licence county or a lead that
  still needs a skip trace. `GET /api/sequences/{id}` and `POST /api/sequences/{id}/pause`
  make the state visible, and the draft queue shows active cadences and what is due.
- **Two routes were reachable but had no caller.** `POST /api/replies/scan` reported a
  single number; it now returns scanned / classified / needs_human / skipped_empty /
  already_seen, is audited, and has a panel on the sync page. `GET
  /api/leads/{id}/template-selection` now explains the match (the flags that fired), says
  whether the lead is draftable, lists the blockers when it is not, and previews the
  wording — which immediately exposed a real bug: a lead with no first name rendered
  **"Hi Hello, this is …"**. The greeting is now grammatical in both cases.
- **Contact-permission review can be done in a batch.** Fifty imported leads used to mean
  fifty profile visits before the first draft could exist. `GET
  /api/leads/restrictions/pending` shows the queue, and `POST
  /api/leads/restrictions/bulk` records the same evidence on each selected lead — but
  demands the typed phrase `REVIEW RESTRICTIONS`, never clears a source Do Not Contact,
  reports already-reviewed leads instead of overwriting their evidence, writes one audit
  row per lead, and relaxes no other gate.
- **The browser suite runs in CI.** It existed and nothing ran it. It now covers every
  sidebar screen on desktop and mobile and three end-to-end flows, and the first run found
  a stale assertion and a real WCAG AA contrast failure (dashboard section numbers at
  2.6:1). Both are fixed.

### 10. Interface

New pages: **Draft Queue** (`/drafts`), **Templates** (`/templates`), **Skip Trace**
(`/skip-trace`), and a rebuilt **Briefing**. The lead profile gained a vendor-context
panel (heat, score, equity, tier, flags, compatible offers, recorded date, manual-edit
list) and a reply recorder. Seller leads gained Data Syndicate filters (heat, tier,
lead type, county, minimum score, minimum equity, outreach context, skip-trace state)
and a DS context column. Settings gained sender identity, cadence and the second
backup folder.

The three new heavy routes are lazy-loaded, so the index still ships one script and
one stylesheet.

## Verified here

| Check | Result |
|---|---|
| Backend suite | **392 passed**, 2 explicit live-account skips |
| Frontend unit suite | **27 passed** |
| `ruff check backend scripts` | clean |
| Browser suite | **20 passed** in GitHub Actions against a throwaway database: all 14 screens on desktop and mobile, plus STOP → suppression, batch review → tier drafts, and skip-trace apply |
| `tsc -b` | clean |
| Production build | clean; 1 JS + 1 CSS in `index.html`, 3 lazy route chunks |
| Upgrade test | previous release schema → head keeps leads, activities, drafts, stages; adds the new columns and merges the new priority weights without overwriting an explicit value |
| Route test | no duplicate routes, no shadowed static paths, no send-shaped route |
| `scripts/test_release.py` on the packaged ZIP | passed — release `1.5.0`, schema head `i1j2k3l4m5n6`, 29 application tables, 2 built assets served, `integrity ok`, 0 foreign-key violations, every included file hash verified, no database or private file in the archive |

These are synthetic, local checks. They do not verify your real database, a vendor
account, a provider account or a native Windows runtime.

## Upgrading

1. Stop the app.
2. Replace the program files with this release (or run `UPDATE-ACQ.cmd` /
   `./update-acq.sh`, which backs up the database first and restores the previous
   version if the new one fails to start).
3. Start it. The schema upgrade runs automatically and is idempotent; `data/`, `.env`
   and `.env.secrets` are never touched by an update.
4. Open **Settings → Runtime & backups** and set a second backup folder if you have a
   second drive or a synced folder.
5. Open **Settings → Pipeline & priorities** to review the new context weights — the
   defaults are `+30` (very hot), `+15` (hot), `+20` (maximum sale-likelihood share),
   `+5` (equity) and `-15` (negative equity).

Nothing in this release sends a message, calls a seller, writes to the CRM or uploads
a database.
