@echo off
setlocal
cd /d "%~dp0"
echo.
echo === Encrypted backup upload for BOTH company databases ===
echo Destination MUST be a PRIVATE GitHub repository.
echo Do NOT type any API keys or database password here; the PowerShell script asks for the backup password privately.
echo.
set "PRIVATE_REPO=https://github.com/JasonWade45/acq-company-database-backups"
set /p "PRIVATE_REPO=Private GitHub repo URL [%PRIVATE_REPO%]: "
set "PRIVATE_REPO=%PRIVATE_REPO:"=%"
if "%PRIVATE_REPO%"=="" echo A private repository URL is required. & goto :fail
set "LEGACY_ROOT=C:\Users\ATG\Desktop\New folder\ACQ-GreenseedTX"
set /p "LEGACY_ROOT=Old GitHub/legacy project root (backend\acquisitions.db) [%LEGACY_ROOT%]: "
set "LEGACY_ROOT=%LEGACY_ROOT:"=%"
if "%LEGACY_ROOT%"=="" echo A legacy project root is required. & goto :fail
set "DELIVERED_ROOT=C:\Users\ATG\Desktop\New folder\acquisitions-assistant-source\acquisitions-assistant"
set /p "DELIVERED_ROOT=Old delivered 1.1 project root (data\acquisitions.db) [%DELIVERED_ROOT%]: "
set "DELIVERED_ROOT=%DELIVERED_ROOT:"=%"
if "%DELIVERED_ROOT%"=="" echo A delivered 1.1 project root is required. & goto :fail
echo.
echo Make sure both old applications are CLOSED before continuing.
pause
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0UPLOAD-DATABASES.ps1" -PrivateRepoUrl "%PRIVATE_REPO%" -LegacyRoot "%LEGACY_ROOT%" -DeliveredRoot "%DELIVERED_ROOT%"
if errorlevel 1 goto :fail
echo.
echo SUCCESS: encrypted backups were pushed to the PRIVATE repository.
echo Save the backup password you entered; it was not uploaded.
pause
endlocal
exit /b 0
:fail
echo.
echo Upload stopped. Both original company databases remain on this PC. Read the error above.
pause
endlocal
exit /b 1
