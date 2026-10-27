@echo off
setlocal
cd /d "%~dp0"
title Acquisitions Assistant - local app

if not exist "frontend\dist\index.html" (
  echo.
  echo The bundled interface is missing.
  echo Extract the complete release ZIP and run this file from the folder that
  echo contains backend, frontend, scripts and README.md.
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: creating the private Python environment...
  where py >nul 2>nul
  if errorlevel 1 (
    where python >nul 2>nul
    if errorlevel 1 (
      echo Python is not installed. Install it from https://www.python.org/downloads/
      echo and tick "Add python.exe to PATH", then run this file again.
      pause
      exit /b 1
    )
    python -m venv .venv
  ) else (
    py -3 -m venv .venv
  )
  if errorlevel 1 (
    echo Could not create .venv. Keep the message above.
    pause
    exit /b 1
  )
)

rem A 3.9 interpreter would create .venv and then fail every dependency install.
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install it, delete the .venv folder,
  echo then run this file again.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -c "import fastapi,uvicorn,segno" >nul 2>nul
if errorlevel 1 (
  echo First run: installing the locked dependencies ^(no AI model is downloaded^)...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r backend\requirements-lock.txt
  if errorlevel 1 (
    echo Dependency installation failed. Keep the message above.
    pause
    exit /b 1
  )
)

echo.
echo If another device cannot connect, allow the port once in an Administrator window:
echo   netsh advfirewall firewall add rule name="Acquisitions Assistant" dir=in action=allow protocol=TCP localport=8010
echo.

".venv\Scripts\python.exe" scripts\acq_desktop.py --port 8010
if errorlevel 1 (
  echo.
  echo The app stopped with an error. Keep the message above.
  pause
)
endlocal
