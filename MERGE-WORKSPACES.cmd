@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0MERGE-WORKSPACES.ps1"
if errorlevel 1 echo Preparation stopped. Keep both databases. Read the error above.
pause
