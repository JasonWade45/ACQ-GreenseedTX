$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Python venv creation failed" }
& .\.venv\Scripts\python.exe -m pip install -r backend/requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw "Python dependency install failed" }
npm --prefix frontend ci
if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
npm --prefix frontend run build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
& .\.venv\Scripts\python.exe scripts/manage.py migrate
if ($LASTEXITCODE -ne 0) { throw "Database migration failed" }
Write-Host "Ready. Run: .\.venv\Scripts\python.exe scripts/run.py"
