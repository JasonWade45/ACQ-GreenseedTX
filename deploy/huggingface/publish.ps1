# Publish the app to a Hugging Face Gradio Space (free, no credit card).
#
# Prerequisites:
#   1. A Hugging Face account and a write token: https://huggingface.co/settings/tokens
#   2. A Space created in the UI (SDK: Gradio, Blank, CPU basic, public).
#   3. The working tree committed; this script exports HEAD, not uncommitted files.
#
# Usage:
#   pwsh -File deploy/huggingface/publish.ps1 -SpaceUrl https://huggingface.co/spaces/USER/SPACE
#
# The Space password and Neon URL are NOT in this repository. Add them in the Space
# Settings -> Variables and secrets after the first build.

param(
    [Parameter(Mandatory = $true)]
    [string]$SpaceUrl,
    [string]$Message = "Deploy Acquisitions Assistant"
)

$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$tmpRoot = Join-Path $env:TEMP ("acq-hf-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$space = Join-Path $tmpRoot "space"
$archive = Join-Path $tmpRoot "app.zip"

if (-not (Test-Path (Join-Path $repo "frontend\dist\index.html"))) {
    throw "frontend/dist/index.html is missing. Run: cd frontend; npm ci; npm run build"
}
if (-not (Test-Path (Join-Path $repo "backend\app\version.py"))) {
    throw "Run this from the Acquisitions Assistant repository."
}

New-Item -ItemType Directory -Force $tmpRoot | Out-Null
try {
    Write-Host "Cloning the Space..." -ForegroundColor Cyan
    git clone $SpaceUrl $space
    if ($LASTEXITCODE -ne 0) { throw "Could not clone the Space. Check the URL and your HF access." }

    Write-Host "Exporting the committed application from HEAD..." -ForegroundColor Cyan
    Push-Location $repo
    try {
        git archive --format=zip --output=$archive HEAD
        if ($LASTEXITCODE -ne 0) { throw "git archive failed" }
    }
    finally {
        Pop-Location
    }

    # Empty the Space working tree but keep its .git directory.
    Get-ChildItem -Force $space | Where-Object { $_.Name -ne ".git" } | Remove-Item -Recurse -Force
    Expand-Archive -Path $archive -DestinationPath $space -Force

    # The Space needs its YAML metadata at the root.
    Copy-Item (Join-Path $repo "deploy\huggingface\README.md") (Join-Path $space "README.md") -Force

    Push-Location $space
    try {
        git add -A
        git -c user.name="Acquisitions Assistant" -c user.email="deploy@localhost" commit -m $Message
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Nothing new to commit; pushing the existing Space tree." -ForegroundColor Yellow
        }
        Write-Host "Pushing to Hugging Face (a token is requested as the password)..." -ForegroundColor Cyan
        git push origin main
        if ($LASTEXITCODE -ne 0) { throw "Push failed. Use a write token from https://huggingface.co/settings/tokens" }
    }
    finally {
        Pop-Location
    }

    Write-Host ""
    Write-Host "Pushed. Watch the Space build in its Logs tab." -ForegroundColor Green
    Write-Host "Then add the secrets in Space Settings -> Variables and secrets:" -ForegroundColor Green
    Write-Host "  APP_ACCESS_PASSWORD (12+ chars), DATABASE_URL (Neon, ?sslmode=require),"
    Write-Host "  SESSION_SECRET (random), APP_TIMEZONE=Africa/Cairo, PORT=7860,"
    Write-Host "  RESIMPLI_MODE=disabled, SYNC_ENABLED=false, CRM_WRITES_ENABLED=false"
    Write-Host "App URL: https://<owner>-<space>.hf.space/api/health"
}
finally {
    if (Test-Path $tmpRoot) { Remove-Item $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
