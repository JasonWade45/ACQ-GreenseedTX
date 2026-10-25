#Requires -Version 5.1
<#
.SYNOPSIS
Prepares encrypted, integrity-checked backups of BOTH real company SQLite databases for upload to a PRIVATE GitHub repository.

IMPORTANT
- Run this file in PowerShell; do not paste its contents into a Command Prompt.
- Create an empty PRIVATE GitHub repository first. Never use the public ACQ-GreenseedTX repository.
- The encryption password is supplied once to this script and is never committed, printed, or uploaded.
- Keep the password in your password manager. Without it, nobody can restore the backups.
- The two selected roots must be different, and both source DBs are left untouched.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?$')]
    [string] $PrivateRepoUrl,

    [Parameter(Mandatory = $true)]
    [string] $LegacyRoot,

    [Parameter(Mandatory = $true)]
    [string] $DeliveredRoot,

    [Parameter(Mandatory = $true)]
    [string] $Branch = 'main',

    [string] $PythonExe = 'python',

    [string] $WorkRoot = (Join-Path $env:USERPROFILE 'acq-database-upload')
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

function Get-ExistingFile([string] $Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "File not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).ProviderPath
}

function Get-PythonCommand([string] $Candidate) {
    if ($Candidate -ne 'python') {
        return Get-ExistingFile $Candidate
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if (-not $command) {
        $command = Get-Command py -ErrorAction SilentlyContinue
    }
    if (-not $command) {
        throw 'Python 3 was not found. Install Python or pass -PythonExe with its full path.'
    }
    return $command.Source
}

# Ask for the password as a local secret. It never enters a command-line argument or a file.
$securePassword = Read-Host 'Create/enter a strong database backup password (not shown)' -AsSecureString
$plainPassword = [Net.NetworkCredential]::new('', $securePassword).Password
if ($plainPassword.Length -lt 16) {
    throw 'Use a backup password of at least 16 characters. Store it in your password manager.'
}

if ($PrivateRepoUrl -notmatch '/[A-Za-z0-9_.-]+/?$') {
    throw 'Invalid private repository URL.'
}
$repoName = ($PrivateRepoUrl.TrimEnd('/') -split '/')[-1]
if ($repoName -ieq 'ACQ-GreenseedTX') {
    throw 'Refusing to upload company databases to the PUBLIC ACQ-GreenseedTX repository. Create a separate PRIVATE repository.'
}
if ($repoName -match '(?i)acq-greenseed') {
    throw 'Choose a separate PRIVATE backup repository whose name is not similar to the public code repository.'
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git is not installed or is not on PATH.'
}
$publicRepo = 'https://github.com/JasonWade45/ACQ-GreenseedTX'
$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($gh) {
    $visibility = & $gh.Source api "repos/$(($PrivateRepoUrl -replace '^https://github\.com/','') -replace '/$','')" --jq '.private' 2>$null
    if ($LASTEXITCODE -eq 0 -and $visibility -ne 'true') {
        throw 'GitHub reports that the destination repository is NOT private. Stopping.'
    }
}
else {
    Write-Warning 'GitHub CLI was not found: confirm in your browser that this repository is PRIVATE before pushing.'
}

$python = Get-PythonCommand $PythonExe
$legacyRootPath = (Resolve-Path -LiteralPath $LegacyRoot).ProviderPath
$deliveredRootPath = (Resolve-Path -LiteralPath $DeliveredRoot).ProviderPath
$legacyDb = Get-ExistingFile (Join-Path $legacyRootPath 'backend\acquisitions.db')
$deliveredDb = Get-ExistingFile (Join-Path $deliveredRootPath 'data\acquisitions.db')
if ($legacyDb -eq $deliveredDb) {
    throw 'Both paths point to the same database. Select the two distinct original project roots.'
}

$stamp = [datetime]::UtcNow.ToString('yyyyMMdd-HHmmss')
$work = Join-Path $WorkRoot $stamp
$repo = Join-Path $work 'repo'
New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null
New-Item -ItemType Directory -Path $work | Out-Null
Write-Host "Private work folder: $work"

try {
    # Clone an existing PRIVATE repository. The source database files stay on this PC.
    & git clone --quiet -- $PrivateRepoUrl $repo
    if ($LASTEXITCODE -ne 0) {
        throw "Could not clone $PrivateRepoUrl. Create the empty PRIVATE repository and sign in to Git first."
    }
    $publishRoot = Join-Path $repo 'databases'
    New-Item -ItemType Directory -Force -Path $publishRoot | Out-Null

    # Embedded Python performs an online SQLite backup, integrity check, inventory,
    # password-authenticated encryption and a fresh encrypted read-back test.
    $helper = @'
import base64, hashlib, io, json, os, secrets, sqlite3, sys, zipfile
from datetime import datetime, timezone

py = sys.executable
work, password = sys.argv[1], sys.argv[2]
sources = {
    "legacy-github": sys.argv[3],
    "delivered-11": sys.argv[4],
}
out = sys.argv[5]
os.makedirs(out, exist_ok=True)
record = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "source_database_files_untouched": True,
    "method": "SQLite online backup API, integrity_check, ZIP, scrypt + AES-256-GCM, fresh read-back",
    "password_or_key_uploaded": False,
    "databases": {},
}
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    sys.stderr.write("Install once in your Python environment: python -m pip install cryptography\n")
    raise SystemExit(2)

def read_back(path, password, salt, nonce, tag, expected):
    blob = open(path, "rb").read()
    key = hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=1, dklen=32)
    raw = AESGCM(key).decrypt(nonce, blob[:-16] + tag, b"acq-database-backup-v1")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert z.testzip() is None and z.namelist() == ["database.sqlite3"]
        assert hashlib.sha256(z.read("database.sqlite3")).hexdigest() == expected

for name, source in sources.items():
    source = os.path.abspath(source)
    backup = os.path.join(work, name + ".sqlite3")
    if os.path.exists(backup):
        os.remove(backup)
    uri = "file:" + source.replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as src, sqlite3.connect(backup) as dst:
        src.backup(dst)
    with sqlite3.connect("file:" + backup + "?mode=ro", uri=True) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError("integrity_check failed: " + integrity)
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            counts[table] = db.execute("SELECT count(*) FROM " + quoted).fetchone()[0]
    raw = open(backup, "rb").read()
    sha = hashlib.sha256(raw).hexdigest()
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("database.sqlite3", raw)
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    key = hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=1, dklen=32)
    sealed = AESGCM(key).encrypt(nonce, zip_bytes.getvalue(), b"acq-database-backup-v1")
    ciphertext, tag = sealed[:-16], sealed[-16:]
    encrypted = os.path.join(out, name + ".sqlite3.zip.enc")
    with open(encrypted, "wb") as f:
        f.write(ciphertext)
    meta = {
        "source_project_root": os.path.dirname(os.path.dirname(source)),
        "source_relative_path": os.path.relpath(source, os.path.dirname(os.path.dirname(source))),
        "sqlite_backup_sha256": sha,
        "encrypted_archive_sha256": hashlib.sha256(ciphertext).hexdigest(),
        "integrity_check": integrity,
        "tables": tables,
        "row_counts": counts,
        "kdf": {"name": "scrypt", "n": 2**15, "r": 8, "p": 1, "key_bytes": 32},
        "salt_base64": base64.b64encode(salt).decode(),
        "nonce_base64": base64.b64encode(nonce).decode(),
        "tag_base64": base64.b64encode(tag).decode(),
        "aead": "AES-256-GCM",
        "associated_data": "acq-database-backup-v1",
        "inner_member": "database.sqlite3",
    }
    record["databases"][name] = meta
    read_back(encrypted, password, salt, nonce, tag, sha)
    os.remove(backup)
    open(os.path.join(out, name + ".json"), "w", encoding="utf-8").write(json.dumps(meta, indent=2) + "\n")
open(os.path.join(out, "manifest.json"), "w", encoding="utf-8").write(json.dumps(record, indent=2) + "\n")
print("Encrypted, independently read back and verified: " + ", ".join(record["databases"]))
'@
    $helperPath = Join-Path $work 'prepare.py'
    [IO.File]::WriteAllText($helperPath, ($helper -replace "`r?`n", "`n"))

    # Pass the password only over a closed stdin stream, never as an argv argument.
    $env:ACQ_BACKUP_PASSWORD = $plainPassword
    $script = @"
import os,runpy,sys
password=os.environ.pop('ACQ_BACKUP_PASSWORD')
sys.argv=[sys.argv[0],r'$work',password,r'$legacyDb',r'$deliveredDb',r'$publishRoot']
runpy.run_path(r'$helperPath',run_name='__main__')
"@
    $entry = Join-Path $work 'entry.py'
    [IO.File]::WriteAllText($entry, ($script -replace "`r?`n", "`n"))
    & $python $entry
    $code = $LASTEXITCODE
    Remove-Item Env:\ACQ_BACKUP_PASSWORD -ErrorAction SilentlyContinue
    [void][Runtime.InteropServices.Marshal]::ZeroFreeCoTaskMemUnicode([Runtime.InteropServices.Marshal]::StringToCoTaskMemUnicode($plainPassword))
    $plainPassword = $null
    if ($code -ne 0) {
        if ($code -eq 2) {
            throw 'Install cryptography once in the same Python environment, then rerun this file: python -m pip install cryptography'
        }
        throw "Encrypted backup preparation failed with exit code $code. Nothing was pushed."
    }

    # Stage encrypted payloads and metadata only. Raw SQLite/WAL files never enter the repo.
    @'
*.db
*.db-wal
*.db-shm
*.sqlite3
*.zip
!databases/*.enc
*.env
*password*
'@ | Set-Content -LiteralPath (Join-Path $repo '.gitignore') -Encoding UTF8
    [IO.File]::WriteAllText((Join-Path $repo 'README.md'), @'
# Private encrypted database backups

This repository contains password-encrypted SQLite backups prepared on Windows. It contains **no vendor keys, `.env` files, source-database WAL files, or raw databases**. Keep it PRIVATE.

`UPLOAD-DATABASES.ps1` and `RESTORE-DATABASES.ps1` from the public code repository prepare and restore these files. The encryption password is stored only in your own password manager; losing it makes the backups unrecoverable.
'@)
    & git -C $repo add -- .gitignore README.md databases
    if ($LASTEXITCODE -ne 0) { throw 'Git staging failed.' }
    $staged = @(& git -C $repo diff --cached --name-only)
    if ($LASTEXITCODE -ne 0) { throw 'Could not list staged files.' }
    foreach ($name in $staged) {
        if ($name -match '(?i)\.env|password|\.db$|\.db-wal$|\.db-shm$|\.sqlite3$|\.zip$' -and $name -notmatch '\.enc$') {
            throw "Refusing to stage a private or raw file: $name"
        }
    }
    & git -C $repo -c user.name='Database Backup' -c user.email='database-backup@localhost' commit --quiet -m 'Add encrypted backups of both company databases'
    if ($LASTEXITCODE -ne 0) { throw 'Git commit failed; review the private work folder.' }
    & git -C $repo push origin "HEAD:$Branch"
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Push did not complete. The encrypted commit is preserved locally in $repo."
        throw "After signing in to Git, run: git -C `"$repo`" push origin HEAD:$Branch"
    }
    Write-Host "SUCCESS: encrypted backups of both databases were pushed to $PrivateRepoUrl ($Branch)."
    Write-Host "Keep the password safe. It was not uploaded. Work folder: $work"
}
catch {
    Write-Error $_
    Write-Warning "No company database was replaced. Private artifacts may remain in $work; keep it private or delete it after recovery."
    throw
}
