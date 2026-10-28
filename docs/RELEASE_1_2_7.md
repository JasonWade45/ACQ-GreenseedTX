# Acquisitions Assistant — Unified 1.2.7 (signed drafts, comparables, real stage mapping)

**Released 2026-10-28 (Africa/Cairo).** Everything in this release answers one question the
previous version could not: *what do I actually send this seller, and what is the property worth
from the numbers I already have?* No schema change; an existing database opens without migration.

## 1. A draft you can send, signed

`generate_draft()` used to refuse any seller without a callback request or a recorded motivation,
so most of the 851 synced leads produced nothing.

| Situation | What you get now |
|---|---|
| Stored activities or calls exist | **follow-up**: refers to the last conversation in general terms — callback, no answer, left a voicemail, connected |
| No history, but a callback request or motivation is recorded | **follow-up** built from that fact |
| No history at all | **opener**: a warm first contact that introduces the acquisition manager and invites a reply — instead of an error |

Every draft ends with the fixed signature, appended locally:

```
Jason Wade
Acquisition Manager, GreenSeedTX LLC
```

The signature is added **after** validation, so the model can never rewrite it, and a draft that
appears to invent one is rejected. The model is told not to produce a signature, a company name or
a title at all.

Also fixed: a seller with no name previously produced `Hi ,`. It now falls back to `Hello,`, and an
address placeholder is never left visible when the property has no street address.

### Groq mode gets the same behaviour

The reviewed cloud path and the local template path now share one decision function
(`ai.draft_plan`), so `ensure_draft_allowed` accepts exactly the same sellers in both. A first
contact with no source history is grounded on the pipeline stage and lead source only — no seller
detail — so an opener is possible without sending anything personal. Do Not Contact and an unknown
restriction status still block, in both paths.

## 2. Sold comparables worksheet

The research page used to show an empty panel that said "no comparables connected". It is now a
worksheet you fill in yourself:

- enter address, sold price, living area, sold date, source and a note;
- the table computes **$/sq ft** per comp;
- the panel computes the **median $/sq ft**, multiplies it by this property's living area, and
  widens it by 5% either way for a range;
- the note says plainly that this is arithmetic on your own inputs, not an appraisal and not an offer;
- a comp without an address or a sold price is refused; living area is bounded 100–100,000 sq ft;
  25 comps per property;
- `DELETE /api/leads/{id}/comps/{comp_id}` removes one, and both add and remove write an audit row.

Nothing is fetched, scraped or generated. The range is only as good as the comps you type.

## 3. The stage table is built from what your CRM really sends

`mainStatusTitle` values were mapped through a static default table, so an unrecognised title
silently became `unmapped`. Sync now records every title it sees with a count
(`source_status_counts`), and `/api/settings` returns them:

```json
[{"title": "Dead Lead", "leads": 851, "stage": "dead", "mapped": true}]
```

Settings → Pipeline & priorities shows that table with a stage selector per row, so unmapped values
are visible and fixable instead of guessed. Sensible defaults were added for common titles
(`Dead Lead → dead`, `Attempted Contact → attempting_contact`, …), but an existing user choice is
never overwritten.

## 4. Room for the fix to be caught

`attempts` → `python scripts/manage.py adapter-check` samples live leads and prints, per mapped
field, how many filled in. This exists because a wrong JSON path returns nothing **without
raising**: `contactData.0.phoneNumbers.0.number` looked exactly like a seller with no phone. The
corrected path (`…0.phoneNumber`) ships as `examples/resimpli-adapter-greenTX.json`, and a test
pins it against a REsimpli-shaped record.

## 5. Version label

The sidebar said `Private · Unified 1.2` while the package said 1.2.6. The label is now injected at
build time from `frontend/package.json`, and the release smoke asserts the built JavaScript carries
the same version as `backend/app/version.py`.

## Verified

| Check | Result |
|---|---|
| Full backend suite | **248 passed**, 1 intentional live-account skip |
| Frontend unit tests | **21 passed** (3 files) |
| `ruff check .` | clean |
| `scripts/check_references.py` | 20 documents, no broken links or stale paths |
| Packaged ZIP boots its real app | `passed: true`, release `1.2.7`, fresh DB, 19 tables, revision `0a6d91cf17b2` |
| New surfaces inside the archive | `/api/leads/{lead_id}/comps`, signature lines, `source_statuses`, built version all asserted from the extracted ZIP |
| Release ZIP | 188 files, SHA-256 `d9472ad5c7bccc6f8984e198d4205cfa346a9ce115a75460e2ff9b05b70d7202` |

## Not verified

- A live REsimpli sync **after** the corrected adapter: that needs your machine and your key.
  `adapter-check` is the command that proves it in one step.
- A live Groq call: no key exists here, and the key must stay in `.env` on your PC.
- Windows execution of `START-ACQ.cmd`, and a phone on a home LAN.

## Upgrading

Extract into a **new** folder, close the running app, then double-click `UPDATE-ACQ.cmd`
(Windows) or run `./update-acq.sh` (macOS/Linux). `data/`, `.env`, `.env.secrets` and `.venv/` are
never touched.
