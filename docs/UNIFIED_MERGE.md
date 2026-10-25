# Unified 1.2 — integration and both-database migration

**Source compared:** `JasonWade45/ACQ-GreenseedTX`, main commit `f96bc3d25b4aea4def3e1122a2004c7bf56c04ad`, against the delivered 1.1 application. This is a feature integration into the single-server foundation, not a claim that the remote GitHub branch was pushed.

## What is unified

| Capability | Unified behavior |
|---|---|
| Dashboard / sellers / daily queues / appointments / reports / search / audit | Existing DB-backed 1.1 functions retained, with independent pipeline/contact/task states |
| Call preparation | New local rules, property talking points, editable saved preparation notes and reviewed checkboxes. Not a call log. A new version preserves prior versions in the DB. Opener withheld for DNC, unknown eligibility/identity/phone, missing relationship context or stale evidence |
| Comparable research | Known exact subject, recorded value/tax/equity references, suggested research criteria, copyable address and portal home links. **No invented sold comps, deep URLs, appraisal, MLS feed or automatic browsing** |
| Rich property facts | Beds/baths/sqft/year, county/lot, recorded tax/value/equity/mortgage/condition/occupancy where explicitly available, with source provenance |
| Smart imports | Local header mapping (including whitespace), labelled/compound beds+baths+sqft, k/m amounts and explicitly separated full addresses. Ranges stay unknown rather than becoming invented midpoints |
| Address-only imports | A property-only prospect can have a genuinely blank owner name. UI says identity unknown; no fabricated person, creation date or permission clearance |
| Reuploads | Explicit duplicate resolution plus optional **fill empty local fields**. Known identity conflicts are refused; known primary values are never silently overwritten; original rows and enrichment provenance remain retained |
| Local batch analysis | Explicit rule-only refresh for at most 200 recently updated records per run; 0 Groq/Ollama requests, with actual updated/cached counts |
| Groq / Ollama | Existing optional guarded integrations. Groq still requires redacted input preview and approval **for each request**, plus output review. No automatic cloud batches |
| Both old company databases | Reviewed local bridge below; no SQL-file swap, uncertain automatic person merge or secret activation |

Unsafe automatic Groq upgrades/background uploads and the remote application's opt-in CRM creation/account-ID mechanism were deliberately **not ported**. No SMS/email/call/dialer/send route or seller-contact job is implemented. REsimpli remains read-only. Authorized manual CSV handoff remains the fallback for CRM creation.

## Two different schemas — never interchange the files

- Delivered 1.1 / unified 1.2: integer-key/Alembic schema, normally **`data/acquisitions.db`**.
- GitHub Next/FastAPI workspace: TEXT UUID-key schema, normally **`backend/acquisitions.db`**.

Both can contain important data. Keep both original folders. **Do not copy one DB over the other, change the unified `DATABASE_URL` to the legacy file, or run unified Alembic migrations against it.** A schema guard refuses the incompatible layout.

## Windows: recommended sequence when both have data

1. Stop **both applications** using Ctrl+C in all of their server windows. Do not delete/reset either DB.
2. Extract the complete 1.2 release into a **separate new folder**.
3. Run the new release's **`UPDATE-WINDOWS.cmd`** by double-clicking the file. Select the **old delivered 1.1 project root** containing `scripts/manage.py`, `data`, `backend` and `.venv` — not the GitHub Next folder.
4. Approve the stopped-app update. It backs up the target database and overwritten program files, preserves its data/private settings, and applies the additive migration. A pre-migration guard also makes a consistent recovery backup before an older unified schema is upgraded.
5. In the **old, now-updated unified project folder**, double-click **`MERGE-WORKSPACES.cmd`**. Select the GitHub project's **`backend\acquisitions.db`** in the native picker. This prepares a review, **not an import**.
6. Run **`START-WINDOWS.cmd`** in that updated unified folder. Open **http://127.0.0.1:8010** after the listening message.
7. In **Import Center → Bring both workspaces together**, open the prepared review. Every source seller starts **Not reviewed — leave untouched**. Choose:
   - **Separate**: preserve a separate person, including same-property/different-owner cases.
   - **Link**: only after confirming the same actual person. It transfers that selected person's history and binds an available stable CRM ID if the target does not have one. Conflicting known CRM IDs cannot be linked.
   - **Skip**: leave that source row out of the active unified DB; it remains in the original/snapshot.
8. Optional **fill empty local fields** applies only to explicitly linked records and never overwrites populated values. Known conflicting seller identities are refused. A property coincidence is not person identity.
9. Type **`MERGE REVIEWED RECORDS`** to approve only the chosen decisions. Processing is local, row-transactional and resumable. Repeat approvals do not duplicate committed records. A changed source snapshot uses stable legacy UUID mapping; a previously migrated person must be reviewed/linked rather than copied again.
10. If a candidate changed after preview, use **Refresh pending matches**, then review decisions again. This clears selected UI decisions, not committed data.
11. Compare seller/property/event/task counts, original dates, DNC flags and source archives before enabling any later **read-only** CRM reconciliation. Keep the originals and recovery backups until verified.

**Run `.cmd` files themselves; do not paste `@echo off` or other CMD contents into PowerShell.** No Bash, WSL or Node is needed to use the prebuilt Windows release. Native Windows helper execution remains unverified in this Linux environment.

Local CLI alternative, from the correct unified project root:

```powershell
& .\.venv\Scripts\python.exe .\scripts\merge_workspaces.py --source 'C:\path with spaces\ACQ-GreenseedTX\backend\acquisitions.db'
& .\.venv\Scripts\python.exe .\scripts\run.py --port 8010
```

Run one command at a time and stop at the first error. The source path is your **local PC path**, not a database upload.

Linux/macOS equivalent:

```sh
.venv/bin/python scripts/merge_workspaces.py --source '/trusted/local/legacy/backend/acquisitions.db'
.venv/bin/python scripts/run.py --port 8010
```

## Preservation and interpretation

- Source is opened read-only and snapshotted with SQLite's consistent **backup API**, not a raw copy of a potentially running WAL main file. Integrity and source foreign keys are checked. The target is backed up before migration-ledger/seller writes.
- Private source/target snapshots are stored beside the target DB in **`workspace-merges/`** (normally `data/workspace-merges`). Automatic schema-upgrade backups go in the target DB directory's `backups/`; the Windows updater additionally keeps a recovery directory under project `backups/`.
- Whole source snapshots preserve original tables and historical artifacts. They may contain confidential seller data **and historical settings**. They are not activated as runtime credentials and are not included in the release/Git. Protect them using OS ACLs and encryption; do not upload them to a chat or public repository.
- Selected people/properties/activities/follow-ups/appointments are converted with provenance. Stable official activity identities reconcile with later verified read-only sync where both ID and mapped event type match; no fuzzy timestamp/text dedup is asserted.
- Original legacy lead fields and historical AI insights, edited drafts and call plans appear under that lead's **Source records → confidential original/normalized values**. Those historical AI artifacts are **not promoted** to active analysis, drafts or current preparation.
- Legacy import history, mapping templates, sync/audit history, unassigned events and unsupported fields remain in the whole source snapshot/table-count inventory; they are **not reconstructed into the active unified import/sync history UI**. This avoids pretending incompatible history/state is current. Use a trusted read-only SQLite tool on a copy for forensic review if needed.
- Legacy `contact_status`, inbound direction, a pipeline name, task completion or a call marked merely `completed` is not promoted into proof of seller contact. Reliable explicit outcomes are used. Ambiguous old normalization (for example `disconnected` misclassified as `connected`) is not inherited as verified contact.
- For source API events, original raw timestamps are checked where available, including actual epoch timestamps. Missing/ambiguous dates remain unknown instead of retaining a legacy fallback-to-now as the actual call time. All original date values remain in provenance/snapshots. Naive legacy locally recorded timestamps use the old UTC-storage convention; date-only lead creation values retain their date precision in the app business timezone. Verify any workspace with different historical timezone conventions before migration.
- Legacy DNC remains sticky. An old `do_not_contact=false` by itself does **not** establish clearance in a new migrated record. Existing verified target restrictions are never lifted.
- Known primary target values are retained. A partial operation preserves earlier committed records; after a failure, review remaining pending rows. No external request or uncertain cloud/CRM operation is automatically retried.

## Rich live-source field mapping

The remote code contains useful **candidate** paths such as `propertyInfo.bedRoomCount`, `bathRoomCount`, `livingArea`, `yearBuilt`, `lotSizeAcres`, `county`, `valuation.estValue`, `estEquity`, `taxInfo.marketValue`, `totalAssessedValue`, `taxYear`, and `mortgageInfo.currentLoanBalance`.

These are **not verification of your account response contract**. The unified private response adapter must still map the actual account envelope, exact fields, stable IDs, contact outcomes and timezone correctly before live sync. Rich fields are supported in the normalizer/property metadata and the legacy bridge; no heuristic mapper is allowed to assert a verified account connection. Inspect and configure the adapter locally; never paste customer responses or keys into chat.

## Evidence and remaining limits

See `VERIFICATION.md`, `unified-upgrade-check.json` and current JUnit artifacts. A test DB created by the **exact checked-out GitHub ORM models** was migrated successfully, as well as WAL/backup/conflict/resume fixtures. A populated 1.1 DB upgraded with **all 17 original application-table values exactly unchanged**, integrity `ok`, zero FK violations and the new 19-table schema.

This does not verify either actual company database, Windows runtime, live API account, Groq generation/billing, a real Ollama model, large migrations, a 50k-row load or long scheduler soak. No automatic sold-comparable or legal/consent certification is claimed. GitHub was read for comparison; **no remote push is claimed**.
