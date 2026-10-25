@echo off
rem One-time Cloudflare Tunnel setup. Usage:
rem   SETUP-TUNNEL-WINDOWS.cmd acq.example.com
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: SETUP-TUNNEL-WINDOWS.cmd ^<your.domain.com^>
  echo Example: SETUP-TUNNEL-WINDOWS.cmd acq.example.com
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_tunnel_windows.ps1" -Hostname "%~1"
if errorlevel 1 (
  echo.
  echo Tunnel setup failed. Keep the error shown above.
  pause
)
endlocal
