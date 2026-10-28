# Acquisitions Assistant — Unified 1.2.8 (a range that is never a dead end)

**Released 2026-10-28 (Africa/Cairo).** A two-line follow-up to 1.2.7. The comparables worksheet
could compute a range only when the subject property had a living area, and a property that came
from REsimpli with an empty `propertyInfo.livingArea` — or from a CSV without a square-footage
column — had no way to get one. The panel then said "add this property's living area" with nowhere
to add it.

## What changed

| | |
|---|---|
| `PATCH /api/leads/{lead_id}/properties/{property_id}` | Accepts `square_feet` (100–100,000), `bedrooms`, `bathrooms`. |
| Fill-empty only | A field that already holds a value is **kept** and reported back in `kept_from_source`; the source is never overwritten. |
| Audited | Each fill writes `property_facts_entered` with the property id and the fields it actually set. |
| Wrong property | A property that does not belong to this seller returns 404 — no cross-lead writes. |
| UI | The comparables panel shows a one-field prompt while the subject has no living area, and disappears once a range can be computed. |
| Opener wording | The first-contact body no longer repeats `my name is Jason Wade and I am the acquisition manager`, which read like a form letter once the signature was appended. The name and title now appear exactly once, in the signature. |

Once the source starts sending its own living area, the sync's own value is what stays; this
endpoint cannot fight it.

## Verified

| Check | Result |
|---|---|
| Full backend suite | **250 passed**, 1 intentional live-account skip (2 new tests) |
| Frontend unit tests | **21 passed** |
| `ruff check .` | clean |
| `scripts/check_references.py` | 22 documents OK |
| `tsc -b` + `vite build` | clean; sidebar label carries `1.2.8` |
| Packaged ZIP booted from an extracted path | `passed: true`, release `1.2.8`, 191 files, SHA-256 `02b6a86cdd873e0dfed52cf9c79bec3597a869b6ab35cd7b15d967d3d6072749` |
| Live HTTP on a real server | login → import one CSV seller → add 2 comps at `$150.00` and `$145.96`/sq ft → `PATCH` living area 2000 sq ft → range `$281,162 – $310,758`; a second `PATCH` kept the first value |
| Live drafts on that server | callback lead → signed follow-up; brand-new lead after a permission review → `opener` introducing GreenSeedTX LLC; Do Not Contact and unknown restriction both refused with their own message |

## Not verified

Same as 1.2.7: a live REsimpli sync after the corrected adapter, a live Groq call, native Windows
`START-ACQ.cmd`, and a phone on a home LAN.

## Upgrading

Extract into a **new** folder, close the running app, then `UPDATE-ACQ.cmd` (Windows) or
`./update-acq.sh` (macOS/Linux). `data/`, `.env`, `.env.secrets` and `.venv/` are never touched.
