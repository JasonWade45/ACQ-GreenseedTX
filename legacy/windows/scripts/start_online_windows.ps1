# Acquisitions Assistant AI - start for online/tunnel access on Windows.
#
#   START-ONLINE-WINDOWS.cmd
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_online_windows.ps1 -Port 8010
#
# On first run this creates a local .env with a cryptographically random password and session
# secret, because the app refuses every /api request from a non-loopback Host header when no
# password is set (that is what makes a tunnel open the page but fail all data calls).
# An existing .env with a valid password is never overwritten.
#
# The server binds 127.0.0.1 on purpose: the tunnel terminates TLS and forwards to it.
# Do not bind 0.0.0.0 on an internet-facing machine.

param(
    [ValidateRange(1, 65535)][int]$Port = 8010,
    [string]$Timezone = "Africa/Cairo",
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $Root
$EnvPath = Join-Path $Root ".env"
$MinLength = 12

function New-Secret([int]$Bytes) {
    $buffer = [byte[]]::new($Bytes)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return (-join ($buffer | ForEach-Object { $_.ToString("x2") }))
}

function Read-EnvValue([string]$Path, [string]$Key) {
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    $pattern = "^\s*" + [regex]::Escape($Key) + "\s*=\s*(.*)$"
    foreach ($line in (Get-Content -LiteralPath $Path)) {
        if ($line -match $pattern) { return $Matches[1].Trim() }
    }
    return ""
}

function Write-EnvFile([string]$Path, [string]$Password, [string]$Secret, [int]$PortNumber, [string]$Zone) {
    $lines = @(
        "# Local configuration for online access. Never commit or upload this file.",
        "APP_HOST=127.0.0.1",
        "APP_PORT=$PortNumber",
        "APP_ACCESS_PASSWORD=$Password",
        "SESSION_SECRET=$Secret",
        "APP_TIMEZONE=$Zone"
    )
    Set-Content -LiteralPath $Path -Value $lines -Encoding ASCII
}

try {
    if (-not (Test-Path -LiteralPath (Join-Path $Root "frontend\dist\index.html"))) {
        throw "The built interface is missing. Extract the complete release ZIP, not individual files."
    }

    # ------------------------------------------------------------- configuration
    $ExistingPassword = Read-EnvValue $EnvPath "APP_ACCESS_PASSWORD"
    if ($ExistingPassword.Length -ge $MinLength -and -not $Force) {
        Write-Host "Using the existing .env password (length $($ExistingPassword.Length))." -ForegroundColor Green
        Write-Host "Pass -Force to generate a new one." -ForegroundColor DarkGray
    } else {
        $Password = "Acq-" + (New-Secret 12)
        $Secret = Read-EnvValue $EnvPath "SESSION_SECRET"
        if ($Secret.Length -lt 32) { $Secret = New-Secret 32 }
        Write-EnvFile $EnvPath $Password $Secret $Port $Timezone
        Write-Host ""
        Write-Host "Generated a new APP_ACCESS_PASSWORD:" -ForegroundColor Green
        Write-Host "    $Password" -ForegroundColor Green
        Write-Host "Save it in a password manager now; it is also stored in .env and shown only here."
        Write-Host ""
    }

    $Password = Read-EnvValue $EnvPath "APP_ACCESS_PASSWORD"
    if ($Password.Length -lt $MinLength) {
        throw "APP_ACCESS_PASSWORD in .env is shorter than $MinLength characters. Rerun with -Force to generate one."
    }

    # ------------------------------------------------------------- environment
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python)) {
        Write-Host "Creating the local Python environment (once)..." -ForegroundColor Yellow
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3 -m venv .venv
        } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
            & python.exe -m venv .venv
        } else {
            throw "Python 3.11+ is not installed or not on PATH. Install it from python.org, then rerun."
        }
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Python)) {
            throw "Could not create the local Python environment."
        }
        & $Python -m pip install --disable-pip-version-check -r (Join-Path $Root "backend\requirements-lock.txt")
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. Keep the error above." }
    }

    # ------------------------------------------------------------- guidance
    Write-Host ""
    Write-Host "Acquisitions Assistant AI - online mode" -ForegroundColor Cyan
    Write-Host "Local address : http://127.0.0.1:$Port"
    Write-Host "Health check  : http://127.0.0.1:$Port/api/health"
    Write-Host ""
    Write-Host "Nothing is exposed to the internet until you start ONE of these:" -ForegroundColor Yellow
    Write-Host "  temporary public URL, no account needed:"
    Write-Host "      cloudflared tunnel --url http://127.0.0.1:$Port"
    Write-Host "  your own domain, permanent service:"
    Write-Host "      SETUP-TUNNEL-WINDOWS.cmd acq.example.com"
    Write-Host "  tailscale:"
    Write-Host "      tailscale funnel $Port"
    Write-Host ""
    Write-Host "Keep this window open. Ctrl+C stops the app."
    Write-Host "No seller communication, CRM write or automatic cloud request is enabled."
    Write-Host ""

    & $Python (Join-Path $Root "scripts\run.py") --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "Server exited with an error. See the ERROR above. Try another port if $Port is occupied."
    }
} catch {
    Write-Host ""
    Write-Host ("Startup failed: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
