@echo off
rem Starts the Next.js frontend on http://localhost:3000 (proxies /api to :8000).
cd /d "%~dp0"
call npm run dev > next.log 2>&1
