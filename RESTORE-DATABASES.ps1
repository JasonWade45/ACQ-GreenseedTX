#Requires -Version 5.1
<#
.SYNOPSIS
Restores one encrypted database backup from the PRIVATE backup repository into a separate review folder.
It never overwrites a running company database and never decrypts both backups into the same path.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?$')]
    [string] $PrivateRepoUrl,

    [Parameter(Mandatory = $true)]
    [ValidateSet('legacy-github', 'delivered-11')]
    [string] $Database,

    [Parameter(Mandatory = $true)]
    [string] $OutputFolder,

    [string] $Branch = 'main',

    [string] $PythonExe = 'python'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

function Get-PythonCommand([string] $Candidate) {
    if ($Candidate -ne 'python') { return (Resolve-Path -LiteralPath $Candidate).ProviderPath }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if (-not $command) { $command = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $command) { throw 'Python 3 was not found. Pass -PythonExe with its full path.' }
    return $command.Source
}

$python = Get-PythonCommand $PythonExe
$password = [Net.NetworkCredential]::new('', (Read-Host 'Database backup password (not shown)' -AsSecureString)).Password
$repo = Join-Path $OutputFolder 'private-backup-repo'
$restore = Join-Path $OutputFolder 'restored'
if (-not (Test-Path -LiteralPath $OutputFolder)) {
    New-Item -ItemType Directory -Path $OutputFolder | Out-Null
}
if (-not (Test-Path -LiteralPath $repo)) {
    & git clone --quiet --branch $Branch -- $PrivateRepoUrl $repo
    if ($LASTEXITCODE -ne 0) { throw "Could not clone the private backup repository: $PrivateRepoUrl" }
}
New-Item -ItemType Directory -Force -Path $restore | Out-Null

$helper = @'
import base64, hashlib, io, json, os, sqlite3, sys, zipfile
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
repo, name, out, password = sys.argv[1:5]
meta = json.load(open(os.path.join(repo, "databases", name + ".json"), encoding="utf-8"))
encrypted = os.path.join(repo, "databases", name + ".sqlite3.zip.enc")
blob = open(encrypted, "rb").read()
assert hashlib.sha256(blob).hexdigest() == meta["encrypted_archive_sha256"], "Encrypted archive hash mismatch"
kdf = meta["kdf"]
assert (kdf["name"], kdf["n"], kdf["r"], kdf["p"], kdf["key_bytes"]) == ("scrypt", 2**15, 8, 1, 32)
salt = base64.b64decode(meta["salt_base64"])
nonce = base64.b64decode(meta["nonce_base64"])
tag = base64.b64decode(meta["tag_base64"])
key = hashlib.scrypt(password.encode(), salt=salt, n=kdf["n"], r=kdf["r"], p=kdf["p"], dklen=kdf["key_bytes"])
raw = AESGCM(key).decrypt(nonce, blob + tag, meta["associated_data"].encode())
with zipfile.ZipFile(io.BytesIO(raw)) as z:
    assert z.testzip() is None and z.namelist() == [meta["inner_member"]]
    db_bytes = z.read(meta["inner_member"])
assert hashlib.sha256(db_bytes).hexdigest() == meta["sqlite_backup_sha256"], "Restored SQLite hash mismatch"
target = os.path.join(out, name + ".sqlite3")
if os.path.exists(target):
    raise SystemExit("Refusing to overwrite an existing restored file: " + target)
open(target, "wb").write(db_bytes)
with sqlite3.connect("file:" + target + "?mode=ro", uri=True) as db:
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
print("Verified restore: " + target)
'@
$helperPath = Join-Path $OutputFolder 'restore.py'
[IO.File]::WriteAllText($helperPath, ($helper -replace "`r?`n", "`n"))
$env:ACQ_RESTORE_PASSWORD = $password
$entry = Join-Path $OutputFolder 'restore-entry.py'
[IO.File]::WriteAllText($entry, "import os,runpy,sys`npassword=os.environ.pop('ACQ_RESTORE_PASSWORD')`nsys.argv=[sys.argv[0],r'$repo',r'$Database',r'$restore',password]`nrunpy.run_path(r'$helperPath',run_name='__main__')`n")
try {
    & $python $entry
    if ($LASTEXITCODE -ne 0) { throw 'Password/hash/integrity verification failed. No existing database was replaced.' }
    Write-Host "SUCCESS: $Database was restored to a separate folder: $restore"
    Write-Host 'Do not copy it over a live application DB. Use the app import/merge review workflow.'
}
finally {
    Remove-Item Env:\ACQ_RESTORE_PASSWORD -ErrorAction SilentlyContinue
    $password = $null
}
