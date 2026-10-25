# Startup exits after migration output — logging correction

## Confirmed defect

Older archives call `logging.config.fileConfig(config.config_file_name)` in `backend/migrations/env.py`. Python's default `disable_existing_loggers=True` disables pre-existing Uvicorn/application error loggers during startup migrations. A later startup/listen failure can then return to the terminal with no visible cause. Healthy server/listening messages can also disappear.

An occupied local port reproduced the exact truncated output in a controlled test, but this **does not prove the original user's own port was occupied**. Other errors could be hidden the same way. Package installation reported by that user succeeded on Windows/Python 3.12.10; the pip update notice was not a failure.

The correction is:

```python
fileConfig(config.config_file_name, disable_existing_loggers=False)
```

This changes logging only: no database reset, source/business record edit, CRM request, account configuration, outreach, or dependency reinstall.

## Apply to an already extracted older archive (PowerShell)

First enter your actual project folder (the folder containing `backend`, `frontend`, `scripts`, and README). With the server stopped, run:

```powershell
$ErrorActionPreference = "Stop"
$file = ".\backend\migrations\env.py"
if (-not (Test-Path "$file.bak")) { Copy-Item -LiteralPath $file -Destination "$file.bak" }
$text = Get-Content -LiteralPath $file -Raw -Encoding UTF8
$text = $text.Replace("fileConfig(config.config_file_name)", "fileConfig(config.config_file_name, disable_existing_loggers=False)")
Set-Content -LiteralPath $file -Value $text -Encoding UTF8
```

The backup is only the migration's **Python source file**, not your database. This replacement is idempotent; it does not enable CRM sync or change settings. PowerShell 5.1 may write a UTF-8 BOM, which Python source files support.

Then deliberately try a different local port:

```powershell
& .\.venv\Scripts\python.exe .\scripts\run.py --port 8010
```

Open `http://127.0.0.1:8010`. A successful run stays running in that terminal and shows `Application startup complete` and `Uvicorn running on ...`. Stop with Ctrl+C. If the terminal immediately returns, retain the newly visible `ERROR`/traceback. A port conflict should be resolved by choosing an unused port, not by killing unrelated programs or deleting company data. Do not reinstall packages just to expose a startup error.

## Actual validation

- Two newly added regression tests failed before the correction: application loggers became disabled; occupied-port process exited with no ERROR visible.
- After correction, those regressions pass; full backend: **105 passed, 1 explicit real-account test skipped**. Ruff passed.
- Controlled occupied-port error is now visible, e.g. `ERROR: [Errno 98] ... address already in use` on Linux (Windows error text/code may differ).
- An unoccupied loopback server reached startup-complete/listening, returned HTTP 200 for the SPA, health and an isolated empty seller database, and shut down normally.
- These automated reproductions were executed on Linux/Python 3.13.16. The user's Windows/Python 3.12.10 runtime after this change is **not yet confirmed**. No real account/model or seller communication was exercised.
