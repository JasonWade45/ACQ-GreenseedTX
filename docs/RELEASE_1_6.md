# Acquisitions Assistant — 1.6.0 (call desk, local rules, reviewed CRM push)

**Released 2026-10-30.** 1.6.0 merges the call and automation work that existed only in the
separate `acquisition-crm-hub` project into this application, corrects documentation that
still said no CRM write existed, and keeps the zero-cost deployment path intact.

## What is new

### 1. Calls that already happened

- New **Calls** tab on every seller profile. Choose an outcome (Connected, Interested,
  Wants an Offer, No Answer, Left Voicemail, Call Back Later, Not Interested, Asked to Stop
  Contact, Wrong Number), optional duration, notes and the next step you promised.
- The outcome deterministically updates `contact_status`, `contact_outcome` and
  `last_contact_at`, writes one `activities` row and one `call_logs` row, and — when the
  outcome implies it — creates exactly one pending follow-up. A second call never stacks a
  duplicate pending follow-up.
- `Interested` / `Wants an Offer` move a new lead to **Qualified**; `Not Interested` and
  `Asked to Stop Contact` move it to **Dead** with a `stage_history` row and a local
  override. `Asked to Stop Contact` also adds a local suppression and sets
  `local_do_not_contact`.
- No call is dialled, recorded, transcribed or sent. This is a record of a conversation.

### 2. Live call script (local, no model call)

- `GET /api/leads/{id}/conversations/script` builds a five-step script (opening, situation,
  discovery, numbers, close), four likely objections and a next step from the lead's own
  name, address and recorded asking price.
- It never invents an ARV, repair number or offer. It is deterministic and costs nothing.
- The modal is available from the Calls tab and works offline.

### 3. Tags

- `lead_tags` table, add/list/remove endpoints and a profile panel. Unique per lead and
  limited to 60 characters. Tags are local labels; they are not sent to the CRM.

### 4. Assignment rules

- `assignment_rules` table and screen. Rules are state/city filters with a priority, an
  optional fallback, and a target owner. The lowest priority number wins; the fallback is
  last.
- `POST /api/assignment/apply` can fill only empty owners (default), so a manual assignment
  is never overwritten. The only column changed is `leads.assigned_manager`.

### 5. Automation engine

- `automation_rules` + `automation_logs` tables and an **Automation** screen.
- Three deterministic rule types: stale lead (no contact for N days → follow-up), warm lead
  (last outcome Interested/Wants an Offer → same-day follow-up), dead-lead archive (no
  contact for N days → Dead stage, disabled by default).
- Run manually from the screen. Every run records its rule, affected count, result and
  failure; one broken rule cannot stop the rest.
- No rule sends, dials or writes to the CRM.

### 6. CRM Push documented as it actually is

- The 1.5 tree already shipped `crm_push.py` and `resimpli_write.py`; README and
  PROJECT_STATUS still claimed no CRM write existed. Those claims are corrected.
- A push creates **one lead** at `/lead/add` only, after a phone/address duplicate search,
  with a typed `PUSH TO CRM` confirmation and `CRM_WRITES_ENABLED=true`. It never edits,
  deletes or changes a CRM status; REsimpli v6 documents no note endpoint, so notes stay in
  `crm_note_outbox`.

### 7. Zero-cost online, no credit card

- `render-free.yaml` deploys the Docker image on Render's free plan. For data that survives a
  restart, point `DATABASE_URL` at a free Neon PostgreSQL database (`?sslmode=require`).
  Neither step requires a credit card.
- The free SQLite-only path is ephemeral: export before you stop, import after a restart.
- Arabic step-by-step: `docs/FREE_HOSTING_AR.md`.

### 8. Documentation and tooling

- Version bumped in `backend/app/version.py`, `frontend/package.json` and the lockfile.
- New migration `k3l4m5n6o7p8` adds five tables, additive only; downgrade drops them.
- README test counts and CRM boundary corrected.
- Encoding damage found in the new screens during the browser pass was repaired (UTF-8, no
  BOM); the browser console reported no errors afterwards.

## Verified here

| Check | Result |
|---|---|
| Backend suite | **559 collected, 0 failed, 29 skipped** (174 s before the additions, full pass after) |
| New backend tests | 10 tests covering calls, DNC suppression, duplicate follow-ups, tags, assignment, automation and the local script |
| Frontend unit suite | **49 passed** (43 existing + 6 new) |
| `tsc -b` / `vite build` | clean |
| Local run | temp SQLite database, migrations to `k3l4m5n6o7p8`, login, lead profile, call, tag, script, assignment, automation, `/api/health`, `/` and hashed JS asset all answered |
| Browser | headless Chromium: dashboard, lead Calls tab, live script modal, Automation and Assignments screens; no page or console errors |
| Ruff | `ruff check backend scripts` clean |
| Docker | Dockerfile present; the local Docker daemon was not running, so the image was not rebuilt here |

## Limits (unchanged)

- No SMS, email, dialer, send control or automated seller contact exists.
- CRM sync is read-only; the create-one-lead push is the only CRM write and is off by default.
- One workspace password, one worker; no per-user roles.
- Automation runs manually; it is not a background outreach job.
- Render free sleeps after idle; the first request can take 30–60 s.
- Real REsimpli/Groq/Grok accounts were not called in this review.

## Upgrading

1. Stop the app.
2. Replace the program files (or run the updater, which backs up the database first).
3. Start it; migrations run automatically and are additive.
4. Open **Automation** and **Assignments** to review/seed the defaults.
5. Open a lead → **Calls** and record one real call as a smoke test.
6. For online: follow `docs/FREE_HOSTING_AR.md`; keep `CRM_WRITES_ENABLED=false` until you
   have tested a preview and one deliberate push.
