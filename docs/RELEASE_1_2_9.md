# Acquisitions Assistant — Unified 1.2.9 (the status table sees CSV imports too)

**Released 2026-10-28 (Africa/Cairo).** One-line follow-up to 1.2.8. The new stage table was
filled only by a CRM sync, so an installation whose sellers arrived through **CSV import** showed
"no source status has been seen yet" even though it had hundreds of leads. That reads like a broken
sync, not like a missing hook.

## What changed

`create_local_lead` — the one function every import path goes through — now records the status
title it was given, in the same `source_status_counts` table the sync writes to.

| Before | After |
|---|---|
| CSV import → `Settings → Pipeline & priorities` empty | CSV import → every distinct status with its lead count and a stage selector |
| A CSV status not in the default table landed silently in `unmapped` and was invisible | It appears in the table, flagged `unmapped`, and one click fixes it |

The counts are additive: importing the same file twice counts twice, exactly as the sync does when
it re-reads a lead. They are a record of what was seen, not a de-duplicated census.

## Verified

| Check | Result |
|---|---|
| Full backend suite | **251 passed**, 1 intentional live-account skip (1 new test) |
| Frontend unit tests | **21 passed** |
| `ruff check .` | clean |
| `scripts/check_references.py` | 23 documents OK |
| `tsc -b` + `vite build` | clean; the built bundle carries `1.2.9` |
| Live server, real DB | imported 4 CSV sellers with 4 different status titles → `source_statuses` went from `[]` to 4 rows, `Hot Prospect` flagged `unmapped`; a one-click PATCH made it `qualified` |
| Live comps on that server | two comps (`$159.07` and `$156.13`/sq ft) + 2,100 sq ft → median `$157.60`, range **$314,412 – $347,508** |
| Live drafts on that server | both new imported sellers produced a signed `opener` after a permission review |
| Packaged ZIP booted from an extracted path | `passed: true`, release `1.2.9`, 192 files, SHA-256 `1ac9527d61aa9adef22aae407bdc9bb0dfe2ff04e28dc7d947435595ff8a6332` |

## Not verified

Unchanged from 1.2.7/1.2.8: a live REsimpli sync after the corrected adapter, a live Groq call,
native Windows `START-ACQ.cmd`, and a phone on a home LAN.

## Upgrading

Extract into a **new** folder, close the running app, then `UPDATE-ACQ.cmd` (Windows) or
`./update-acq.sh` (macOS/Linux). `data/`, `.env`, `.env.secrets` and `.venv/` are never touched.
