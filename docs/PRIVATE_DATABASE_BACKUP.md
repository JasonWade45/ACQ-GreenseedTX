# Upload both company databases safely

The public `ACQ-GreenseedTX` repository contains code only. **Never attach real company
SQLite databases, WAL files, `.env` files, API keys or an encryption password to the public
repository or a chat.** A separate **private GitHub repository** has been created for the
encrypted backups.

You have two distinct databases:

- old GitHub/legacy project root → `backend\acquisitions.db` (UUID/legacy schema);
- old delivered 1.1 project root → `data\acquisitions.db` (integer/Alembic schema).

These are not interchangeable. Both remain on your Windows PC; the helper scripts never
overwrite, migrate or merge them automatically.

## Easiest: double-click the wrapper

1. Stop both old applications so their SQLite connections are closed.
2. Download the updated unified 1.2 release, or clone the public repository.
3. In the project root, double-click **`UPLOAD-DATABASES.cmd`**. Do not paste its contents
   into PowerShell. The wrapper asks for:
   - the private repository URL;
   - the old GitHub/legacy project root containing `backend\acquisitions.db`;
   - the old delivered 1.1 project root containing `data\acquisitions.db`.
4. The PowerShell helper then asks privately for a strong password (16+ characters). Save
   that password in your password manager — it is never written to the repository. Without
   it, the backups cannot be restored.

The wrapper defaults to `https://github.com/JasonWade45/acq-company-database-backups` and
known Windows paths; change any default that does not match your machine. Do not type an API
key into the wrapper.

## Command alternative (PowerShell)

Open **PowerShell**, change to the project root, and paste this one-line command. Adjust the
two roots if needed. This is a PowerShell command, not `.cmd` file contents:

```powershell
python -m pip install cryptography; powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\UPLOAD-DATABASES.ps1 -PrivateRepoUrl https://github.com/JasonWade45/acq-company-database-backups -LegacyRoot "C:\Users\ATG\Desktop\New folder\ACQ-GreenseedTX" -DeliveredRoot "C:\Users\ATG\Desktop\New folder\acquisitions-assistant-source\acquisitions-assistant"
```

If you split a PowerShell command over several lines, end each intermediate line with a
backtick (`` ` ``), not `^`. Using the `.cmd` wrapper is simpler.

Optional explicit database paths, if your folder layout differs:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\UPLOAD-DATABASES.ps1 -PrivateRepoUrl https://github.com/JasonWade45/acq-company-database-backups -LegacyRoot "C:\project\legacy" -DeliveredRoot "C:\project\delivered" -LegacyDb "C:\elsewhere\legacy.db" -DeliveredDb "C:\elsewhere\delivered.db"
```

## What the helper does

- Rejects the public `ACQ-GreenseedTX` repository and, when GitHub CLI is available, rejects
  any destination that is not private.
- Requires two distinct source DBs and compares their hashes.
- Uses Python's SQLite online backup API so a live WAL file is not copied raw.
- Runs `PRAGMA integrity_check` and records table names/counts for each backup.
- ZIPs, encrypts with scrypt + AES-256-GCM using the local password, then reads the encrypted
  payload back and verifies both the encrypted and restored SQLite SHA-256 values.
- Commits and pushes only `*.sqlite3.zip.enc`, per-DB metadata, and `manifest.json`.
- Leaves source DBs and their WAL files untouched, and never stages `.env`, source keys,
  raw databases, or plaintext ZIPs.
- Does not upload the encryption password. Table names/counts are metadata; no seller rows
  are written to the manifest.

The encryption/backup/restore round trip was tested here on **synthetic** SQLite databases in
WAL mode, including paths with spaces, `#` and an apostrophe. A wrong password was rejected.
Native Windows execution and the real company DBs were not available here.

## Restore and verify on a separate machine

Double-click **`RESTORE-DATABASES.cmd`** and choose `legacy-github` or `delivered-11`, or run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\RESTORE-DATABASES.ps1 -PrivateRepoUrl https://github.com/JasonWade45/acq-company-database-backups -Database legacy-github -OutputFolder "C:\AcqBackupRestoreCheck"
```

Repeat with `-Database delivered-11` in the same output folder. Enter the same password.
Each restore verifies the encrypted archive hash, decrypts the ZIP, verifies the SQLite hash
and `PRAGMA integrity_check`, and writes to a separate restored file. It refuses to overwrite
a previous restore or any live app database.

A backup is useful only after a tested restore. Do the restore check before relying on it.

## After the upload

The app is not switched to these backup files. On the Windows machine, use the unified
`UPDATE-WINDOWS.cmd` against the delivered 1.1 root, then `MERGE-WORKSPACES.cmd` to
prepare a read-only snapshot of the legacy DB. Approve separate/link/skip decisions in
Import Center. Keep the originals and all backups.

No actual company database, private repository contents, or encryption password was
available in this workspace. The helpers themselves were published; the company data stays
local until you run the upload on Windows. GitHub private repositories still require careful
access control; encryption is an additional safeguard, not permission to make the repository
public.
