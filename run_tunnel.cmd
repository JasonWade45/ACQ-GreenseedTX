@echo off
rem ============================================================
rem  run_tunnel.cmd ??? expose the app online via ngrok
rem  Prereqs: backend on :8000 (run_backend.cmd) and
rem           frontend on :3000 (run_frontend.cmd) already running.
rem  Prints the public https URL (frontend; /api/* is proxied
rem  to the backend automatically through next.config.js).
rem ============================================================

tasklist /fi "imagename eq ngrok.exe" 2>nul | find /i "ngrok.exe" >nul
if %errorlevel%==0 (
  echo ngrok is already running.
) else (
  echo Starting ngrok tunnel to localhost:8010 ...
  start "" ngrok http 8010
  timeout /t 6 >nul
)

echo.
echo Public URL:
powershell -NoProfile -Command "(Invoke-RestMethod 'http://127.0.0.1:4040/api/tunnels').tunnels | ForEach-Object { $_.public_url }"
echo.
echo Notes:
echo  - Open the URL from any device; /api works through it.
echo  - ngrok free shows a one-time warning page in browsers - click through.
echo  - The URL changes every time ngrok restarts.
echo  - Keep it private: the app has no login yet.
echo  - Stop the tunnel:  taskkill /f /im ngrok.exe

