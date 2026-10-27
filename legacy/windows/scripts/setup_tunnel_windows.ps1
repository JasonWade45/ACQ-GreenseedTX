# Acquisitions Assistant AI - one-time Cloudflare Tunnel setup on Windows.
#
#   SETUP-TUNNEL-WINDOWS.cmd acq.example.com
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_tunnel_windows.ps1 -Hostname acq.example.com
#
# Steps: verify cloudflared, verify the local app answers, log in to Cloudflare, create a named
# tunnel, write config.yml (existing file backed up), route DNS, install the Windows service,
# then verify https://<hostname>/api/health.
#
# Nothing is uploaded, no database is touched. The tunnel only forwards HTTP to the local
# server, so APP_ACCESS_PASSWORD remains the only way in.

param(
    [Parameter(Mandatory = $true)][string]$Hostname,
    [ValidateRange(1, 65535)][int]$Port = 8010,
    [string]$TunnelName = "acq",
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$CloudflaredDir = Join-Path $env:USERPROFILE ".cloudflared"
$ConfigPath = Join-Path $CloudflaredDir "config.yml"

function Invoke-Step([string]$Message, [scriptblock]$Action) {
    Write-Host ""
    Write-Host "== $Message" -ForegroundColor Cyan
    if ($DryRun) {
        Write-Host "   (dry run: skipped)" -ForegroundColor DarkGray
        return
    }
    $global:LASTEXITCODE = 0
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "Step failed: $Message" }
}

try {
    $Hostname = $Hostname.Trim().ToLowerInvariant()
    if ($Hostname -notmatch "^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$") {
        throw "Hostname must look like acq.example.com (lowercase letters, digits, dots, hyphens)."
    }

    Write-Host ""
    Write-Host "Cloudflare Tunnel setup" -ForegroundColor Green
    Write-Host "  hostname : $Hostname"
    Write-Host "  tunnel   : $TunnelName"
    Write-Host "  forwards : http://127.0.0.1:$Port"

    # 1 - cloudflared present
    if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
        Write-Host ""
        Write-Host "cloudflared is not installed. Install it with:" -ForegroundColor Yellow
        Write-Host "    winget install --id Cloudflare.cloudflared"
        Write-Host "Then close and reopen PowerShell and run this script again."
        throw "cloudflared is missing."
    }
    Write-Host ("  cloudflared: " + ((& cloudflared --version) -join " "))

    # 2 - the local app must already be running, otherwise the tunnel serves 502
    try {
        $Health = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri "http://127.0.0.1:$Port/api/health"
        Write-Host "  local app  : $($Health.StatusCode) $($Health.Content)"
    } catch {
        throw "No answer on http://127.0.0.1:$Port/api/health. Start START-ONLINE-WINDOWS.cmd first and keep it running."
    }

    # 3 - Cloudflare login (writes cert.pem once)
    if (-not (Test-Path -LiteralPath (Join-Path $CloudflaredDir "cert.pem"))) {
        Invoke-Step "Cloudflare login (browser opens; sign in with the account that owns the domain)" {
            & cloudflared tunnel login
        }
        if (-not (Test-Path -LiteralPath (Join-Path $CloudflaredDir "cert.pem"))) {
            throw "Login did not create cert.pem in $CloudflaredDir. Use an account that owns the domain."
        }
    } else {
        Write-Host "  login      : certificate already present"
    }

    # 4 - find or create the tunnel
    $TunnelId = ""
    $Existing = @()
    try {
        $Raw = (& cloudflared tunnel list --output json) -join ""
        if ($Raw.Trim()) { $Existing = @($Raw | ConvertFrom-Json) }
    } catch {
        Write-Host "  warning: could not parse the tunnel list; continuing." -ForegroundColor Yellow
    }
    $Match = $Existing | Where-Object { $_.name -eq $TunnelName } | Select-Object -First 1
    if ($Match) {
        $TunnelId = $Match.id
        Write-Host "  tunnel     : '$TunnelName' already exists ($TunnelId)"
    } else {
        Invoke-Step "Create tunnel '$TunnelName'" { & cloudflared tunnel create $TunnelName }
        $Raw = (& cloudflared tunnel list --output json) -join ""
        $Match = @($Raw | ConvertFrom-Json) | Where-Object { $_.name -eq $TunnelName } | Select-Object -First 1
        if (-not $Match) { throw "Tunnel was not created. Run 'cloudflared tunnel list' to inspect." }
        $TunnelId = $Match.id
        Write-Host "  tunnel     : created $TunnelId"
    }

    # 5 - config.yml (back up an existing one; never silently replace it)
    $Credentials = Join-Path $CloudflaredDir "$TunnelId.json"
    if (-not (Test-Path -LiteralPath $Credentials)) {
        throw "Credentials file missing: $Credentials. Recreate with 'cloudflared tunnel create $TunnelName'."
    }
    $Yaml = @(
        "tunnel: $TunnelId",
        "credentials-file: $($Credentials -replace '\\', '/')",
        "ingress:",
        "  - hostname: $Hostname",
        "    service: http://127.0.0.1:$Port",
        "    originRequest:",
        "      connectTimeout: 30s",
        "  - service: http_status:404"
    ) -join "`r`n"

    if ($DryRun) {
        Write-Host ""
        Write-Host "config.yml that would be written:" -ForegroundColor DarkGray
        Write-Host $Yaml -ForegroundColor DarkGray
    } else {
        if (-not (Test-Path -LiteralPath $CloudflaredDir)) {
            New-Item -ItemType Directory -Path $CloudflaredDir -Force | Out-Null
        }
        if (Test-Path -LiteralPath $ConfigPath) {
            $Backup = "$ConfigPath.bak-" + (Get-Date -Format "yyyyMMdd-HHmmss")
            Copy-Item -LiteralPath $ConfigPath -Destination $Backup -Force
            Write-Host "  config     : existing file backed up to $Backup"
        }
        Set-Content -LiteralPath $ConfigPath -Value $Yaml -Encoding ASCII
        Write-Host "  config     : wrote $ConfigPath"
    }

    # 6 - DNS route and the Windows service
    Invoke-Step "Route $Hostname to tunnel '$TunnelName'" {
        & cloudflared tunnel route dns $TunnelName $Hostname
    }
    Invoke-Step "Install cloudflared as a Windows service (starts with Windows)" {
        & cloudflared service install
    }

    Write-Host ""
    Write-Host "== Configured" -ForegroundColor Cyan
    if (-not $DryRun) {
        try { Start-Service -Name "Cloudflared" -ErrorAction Stop }
        catch { Write-Host "  note: service start reported: $($_.Exception.Message)" -ForegroundColor Yellow }
        Start-Sleep -Seconds 3
    }

    Write-Host ""
    Write-Host "Verify (may take up to a minute for DNS and the certificate):" -ForegroundColor Green
    Write-Host "    curl.exe https://$Hostname/api/health"
    Write-Host "Then open https://$Hostname and sign in with APP_ACCESS_PASSWORD from .env."
    Write-Host ""
    Write-Host "The app must stay running (START-ONLINE-WINDOWS.cmd); the tunnel alone returns 502."
    Write-Host "Remove later: cloudflared service uninstall ; cloudflared tunnel delete $TunnelName"
} catch {
    Write-Host ""
    Write-Host ("Setup stopped: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
