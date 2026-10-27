@echo off
setlocal
cd /d "%~dp0"
title Acquisitions Assistant - update

if not exist "scripts\update_acq.py" (
  echo.
  echo This file must stay inside the extracted release folder.
  echo Extract the whole ZIP first, then double-click UPDATE-ACQ.cmd again.
  echo.
  pause
  exit /b 1
)

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo.
  echo Python was not found. Install Python 3.11 or newer from
  echo https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^),
  echo then double-click this file again. Nothing was changed.
  echo.
  pause
  exit /b 1
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 (
  echo.
  echo Python 3.11 or newer is required. Nothing was changed.
  echo.
  pause
  exit /b 1
)

echo.
echo This updates your existing installation and keeps your data, password and settings.
echo Close the app window first if it is still open.
echo.
%PY% scripts\update_acq.py --start %*
set "CODE=%ERRORLEVEL%"
echo.
if not "%CODE%"=="0" (
  echo The update did not finish. Your data is untouched.
  echo Read the message above, then run this file again.
) else (
  echo Done. The app opens in its own window on port 8010.
)
echo.
pause
endlocal
