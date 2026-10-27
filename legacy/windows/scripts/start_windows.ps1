param([ValidateRange(1,65535)][int]$Port = 8010)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $Root

try {
    if (-not (Test-Path -LiteralPath (Join-Path $Root "frontend\dist\index.html"))) {
        throw "The built interface is missing. Use the complete release ZIP, not just individual source files."
    }
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python)) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
            if ($LASTEXITCODE -ne 0) { throw "Python 3.11 or newer is required. Python 3.12/3.13 is recommended." }
            & py -3 -m venv .venv
        } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
            & python.exe -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
            if ($LASTEXITCODE -ne 0) { throw "Python 3.11 or newer is required." }
            & python.exe -m venv .venv
        } else {
            throw "Python is not installed or not on PATH. Install Python with the launcher from python.org. Bash/WSL/Node are not required."
        }
        if ($LASTEXITCODE -ne 0) { throw "Could not create the local Python environment." }
    }
    & $Python -c "import importlib.util,sys; names=['fastapi','uvicorn','sqlalchemy','alembic','httpx','apscheduler','openpyxl','phonenumbers','pydantic_settings','defusedxml']; sys.exit(0 if all(importlib.util.find_spec(n) for n in names) else 1)"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing locked Python dependencies once. No AI model is downloaded."
        & $Python -m pip install --disable-pip-version-check -r (Join-Path $Root "backend\requirements-lock.txt")
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. Keep the error above; do not reset your database." }
    }
    Write-Host ""
    Write-Host "Acquisitions Assistant AI 1.2" -ForegroundColor Green
    Write-Host "After the listening message appears, open: http://127.0.0.1:$Port"
    Write-Host "Keep this window open. Ctrl+C stops the application."
    Write-Host "Groq requests require reviewed context. No seller communication is implemented."
    Write-Host ""
    & $Python (Join-Path $Root "scripts\run.py") --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) { throw "Server exited with an error. See the visible ERROR above. Try another local port if it is occupied." }
} catch {
    Write-Host ""
    Write-Host ("Startup failed: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
