@echo off
rem Start Acquisitions Assistant AI for online/tunnel access on Windows.
rem Creates a strong local .env on first run, then prints how to expose it.
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_online_windows.ps1" -Port 8010
if errorlevel 1 (
  echo.
  echo Startup failed. Keep the error shown above.
  pause
)
endlocal
