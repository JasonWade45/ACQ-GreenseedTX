# Upload both company databases safely

The public `ACQ-GreenseedTX` repository contains code only. **Never attach real company
SQLite databases, WAL files, `.env` files, API keys or an encryption password to the public
repository or a chat.** Create a separate **private GitHub repository** first.

You have two distinct databases:

- old GitHub/legacy project root → `backend\acquisitions.db` (UUID/legacy schema);
- old delivered 1.1 project root → `data\acquisitions.db` (integer/Alembic schema).

These are not interchangeable. Both remain on your Windows PC; the scripts never overwrite,
migrate or merge them automatically.

## Prepare and push encrypted backups

1. Stop both old applications so their SQLite connections are closed.
2. Create an **empty PRIVATE** GitHub repository with a different name. Do not create it
   inside the public repository. Make sure Git is signed in on Windows.
3. In PowerShell, from the updated unified project root, run the file (do not paste its
   contents):

```powershell
python -m pip install cryptography
powershell.exe -NoProfile -ExecutionPolicy Bypass ^
  -File .\UPLOAD-DATABASES.ps1 ^
  -PrivateRepoUrl https://github.com/YOUR-ACCOUNT/YOUR-PRIVATE-REPO ^
  -LegacyRoot "C:\path\to\old-GitHub-project" ^
  -DeliveredRoot "C:\path\to\old-delivered-1.1-project"
```

Use normal one-line PowerShell commands, or a `.ps1` file; `^` is a PowerShell line
continuation. The script prompts for a strong password (16+ characters) with no echo. Save
that password in your password manager — it is never written to the repository. Without it,
the backups cannot be restored.

The script will:

- reject the public `ACQ-GreenseedTX` repository and, when GitHub CLI is available, reject
  any destination that is not private;
- require both distinct source DBs and compare their hashes;
- use Python's SQLite online backup API so a live WAL file is not copied raw;
- run `PRAGMA integrity_check` and record table names/counts for each backup;
- ZIP, encrypt with scrypt + AES-256-GCM using the local password, then read the encrypted
  payload back and verify both the encrypted and restored SQLite SHA-256 values;
- commit and push only `*.sqlite3.zip.enc`, per-DB metadata, and `manifest.json`;
- leave source DBs and their WAL files untouched, and never stage `.env`, source keys,
  raw databases, or plaintext ZIPs.

A backup is useful only after a tested restore. See the next section.

## Restore and verify on a separate machine

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\RESTORE-DATABASES.ps1 `
  -PrivateRepoUrl https://github.com/YOUR-ACCOUNT/YOUR-PRIVATE-REPO `
  -Database legacy-github `
  -OutputFolder "C:\AcqBackupRestoreCheck"
```

Repeat with `-Database delivered-11` in the same output folder. Enter the same password.
Each restore verifies the encrypted archive hash, decrypts the ZIP, verifies the SQLite hash
and `PRAGMA integrity_check`, and writes to a separate restored file. It refuses to overwrite
a previous restore or any live app database.

## After the upload

The app is not switched to these backup files. On the Windows machine, use the unified
`UPDATE-WINDOWS.cmd` against the delivered 1.1 root, then `MERGE-WORKSPACES.cmd` to
prepare a read-only snapshot of the legacy DB. Approve separate/link/skip decisions in
Import Center. Keep the originals and all backups.

No actual company database, private repository, encryption password, or Windows helper was
available/executed in this workspace. The scripts are provided for local verification.
GitHub private repositories still require careful access control; encryption is an
additional safeguard, not permission to make the repository public.
