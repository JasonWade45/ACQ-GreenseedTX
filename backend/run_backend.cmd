@echo off
rem Starts the Acquisitions Assistant API on 127.0.0.1:8000.
rem Output is written to uvicorn.log next to this script.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > uvicorn.log 2>&1
