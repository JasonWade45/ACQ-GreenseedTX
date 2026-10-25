# Acquisitions Assistant — Unified 1.2.1

Patch release for safe backup of **both** real company databases. The application code is
unchanged from Unified 1.2; the release adds tested helpers, wrappers and documentation.

## New

- Separate **private** GitHub repository `JasonWade45/acq-company-database-backups` for
  encrypted backups. It is confirmed private and contains helper files only — no company
  database has been uploaded from this workspace.
- `UPLOAD-DATABASES.cmd` / `UPLOAD-DATABASES.ps1`: prepare both original SQLite DBs using
  Python's online backup API, check integrity, record table names/counts, encrypt each DB
  with scrypt + AES-256-GCM, verify a fresh encrypted read-back, and push only encrypted
  payloads and metadata to the private repository. The password is prompted locally and
  never uploaded.
- `RESTORE-DATABASES.cmd` / `RESTORE-DATABASES.ps1`: verify archive hashes, decrypt to a
  separate review folder, verify SQLite hash and `PRAGMA integrity_check`, and refuse to
  overwrite a live database.
- `docs/PRIVATE_DATABASE_BACKUP.md` and an Arabic section in `START_HERE_WINDOWS_AR.md`.

## Tested

The embedded Python backup/restore logic was tested on synthetic SQLite WAL databases with
spaces, `#`, `?` and an apostrophe in their paths. Both encrypted archives were read back
and restored with integrity `ok`; a wrong password was rejected; ciphertext contained no
plaintext marker; simulated Git staging contained only encrypted payloads, JSON metadata,
`.gitignore` and `README.md`. The private repository's visibility was confirmed through the
GitHub API.

Native PowerShell/Windows execution and the two real company databases were **not**
available here. Run the helpers on the Windows PC that holds the originals, then test a
restore before relying on a backup.

## Safety

The two company DBs remain distinct and local: GitHub UUID `backend/acquisitions.db` and
delivered integer/Alembic `data/acquisitions.db`. Never replace one with the other. Keep the
public code repository free of raw DBs, WAL files, `.env` files, vendor keys and backup
passwords. After backup, use `UPDATE-WINDOWS.cmd` and `MERGE-WORKSPACES.cmd`, then approve
separate/link/skip decisions in Import Center.

No seller communication, CRM write, automatic cloud batch or unverified account creation is
enabled. Prior 1.2 QA still applies: 167 backend passes + one intentional live skip, 20 UI
unit passes, 17 compiled-app browser passes and an extracted-release boot/hash/auth smoke.
