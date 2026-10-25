@echo off
setlocal
cd /d "%~dp0"
echo.
echo === Verify/restore one encrypted company database backup ===
echo This writes to a separate review folder; it never overwrites a live app database.
echo.
set "PRIVATE_REPO=https://github.com/JasonWade45/acq-company-database-backups"
set /p "PRIVATE_REPO=Private GitHub repo URL [%PRIVATE_REPO%]: "
set "PRIVATE_REPO=%PRIVATE_REPO:"=%"
if "%PRIVATE_REPO%"=="" echo A private repository URL is required. & goto :fail
set "DB_NAME=legacy-github"
set /p "DB_NAME=Which backup? legacy-github or delivered-11 [%DB_NAME%]: "
if /i not "%DB_NAME%"=="legacy-github" if /i not "%DB_NAME%"=="delivered-11" echo Choose exactly legacy-github or delivered-11. & goto :fail
set "OUT_FOLDER=%USERPROFILE%\AcqBackupRestoreCheck"
set /p "OUT_FOLDER=Separate output folder [%OUT_FOLDER%]: "
set "OUT_FOLDER=%OUT_FOLDER:"=%"
if "%OUT_FOLDER%"=="" echo An output folder is required. & goto :fail
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RESTORE-DATABASES.ps1" -PrivateRepoUrl "%PRIVATE_REPO%" -Database "%DB_NAME%" -OutputFolder "%OUT_FOLDER%"
if errorlevel 1 goto :fail
echo.
echo SUCCESS: backup restored and verified in the separate folder.
pause
endlocal
exit /b 0
:fail
echo.
echo Restore stopped. No existing company database was replaced. Read the error above.
pause
endlocal
exit /b 1
