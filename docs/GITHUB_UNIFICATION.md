# GitHub unification — 1.2

This tree is based directly on `JasonWade45/ACQ-GreenseedTX` commit **f96bc3d25b4aea4def3e1122a2004c7bf56c04ad**, not the stale 1.1 publication bundle. Its original history and every earlier tracked file remain retrievable from that commit. No force-push, history rewrite or company-database overwrite is needed.

## One active application

The active root is React/TypeScript/Vite + the same-origin FastAPI server. The prebuilt `frontend/dist` is intentionally versioned so Windows startup needs Python but no Node/WSL. The older Next application and incompatible UUID ORM are preserved by Git history rather than shipped as a second active server with unsafe legacy defaults.

Retained features include the database-backed dashboard, seller profiles and search, independent pipeline/contact/task states, daily queues/tasks/appointments/reports/audit, read-only CRM sync, full reviewed CSV/XLSX imports, backups and gated optional AI. Compatible GitHub functionality was ported: persistent preparation/checklists, grounded property-research criteria, richer fact extraction, compound/property-only imports and explicitly reviewed fill-empty enrichment.

Automatic on-key/background Groq batches, hardcoded account IDs and unverified CRM creation/write paths are deliberately **not** active features. There are no seller send/call/email/SMS functions. Every optional cloud request still requires selected/redacted context and separate human approval.

## Your two actual databases stay local

GitHub contains public code, fictional fixtures and QA evidence—not company SQLite/WAL/snapshots, private environment/password files, vendor keys, dependencies or logs.

The old GitHub `backend/acquisitions.db` and delivered 1.1 `data/acquisitions.db` have different schemas. **Never replace one with the other.** Stop both old apps, keep copies, update the old delivered 1.1 root using the new `UPDATE-WINDOWS.cmd`, then run `MERGE-WORKSPACES.cmd` there and select the old GitHub DB. `START-WINDOWS.cmd` opens the unified server; approve explicit separate/link/skip choices in Import Center. Preparing a source never silently merges people.

لا تنسخ قاعدة فوق التانية. شغّل ملفات CMD بالدبل كليك، ولا تلصق محتواها في PowerShell. البيانات الحقيقية لا تُرفع إلى GitHub أو المحادثة. التفاصيل في `START_HERE_WINDOWS_AR.md` و`docs/UNIFIED_MERGE.md`.

## Verification and boundaries

The imported release was actually tested: 167 backend passes + one intentional live-account skip, 20 UI unit passes and 17 compiled-app browser passes. Backup/restore, all 17 old table values on 1.1 upgrade, an exact pinned-ORM fictional bridge, desktop/mobile screenshots and extracted-archive boot/hash checks have recorded evidence. See `docs/VERIFICATION.md`.

Rechecking this publication tree is separate from claiming real-account/native-Windows/company-data validation. Those remain unverified. A local commit or authentication attempt is not proof of a remote upload; only the remote branch after a successful push establishes publication.

Publication-tree recheck: **167 backend passed + 1 live skip; 20 UI unit passed; Ruff/ESLint/TypeScript/Vite passed; npm audit reported 0 vulnerabilities**. The rebuilt JS/CSS asset names match the tested release. The existing 17-case browser evidence is retained as its original run, not relabelled as new.
