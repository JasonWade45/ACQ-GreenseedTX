@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0UPDATE-WINDOWS.ps1"
echo.
pause
endlocal
