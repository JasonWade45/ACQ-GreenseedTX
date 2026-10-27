@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_windows.ps1" -Port 8010
if errorlevel 1 (
  echo.
  echo The application did not start. Keep the error shown above.
  pause
)
endlocal
