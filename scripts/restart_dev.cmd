@echo off
setlocal
rem Restart Study Copilot for local testing.
rem   backend -> http://127.0.0.1:8766  (auto-reloads on code changes)
rem   UI      -> http://localhost:5173  (Vite dev server, proxies /api to the backend)
rem Port 8766 is used instead of 8765 so this never clashes with another program on 8765.
rem Only windows this script started ("Study Copilot - ...") are stopped on restart.
cd /d "%~dp0.."
set "API_PORT=8766"
set "UI_PORT=5173"
set "STUDY_COPILOT_API=http://127.0.0.1:%API_PORT%"

echo Stopping a previous run of this script (if any)...
taskkill /F /T /FI "WINDOWTITLE eq Study Copilot - backend*" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq Study Copilot - UI*" >nul 2>&1
timeout /t 2 /nobreak >nul

for %%P in (%API_PORT% %UI_PORT%) do (
  netstat -ano | findstr ":%%P " | findstr "LISTENING" >nul && (
    echo.
    echo Port %%P is already in use by another program. Close it, or change the port at the top of this file.
    pause
    exit /b 1
  )
)

echo Starting the backend on %STUDY_COPILOT_API% ...
start "Study Copilot - backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port %API_PORT% --reload"

echo Starting the UI on http://localhost:%UI_PORT% ...
start "Study Copilot - UI" /D "%CD%\frontend" cmd /k "npm run dev -- --port %UI_PORT% --strictPort"

echo Waiting for both to come up...
set /a tries=0
:wait
set /a tries+=1
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:%API_PORT%/health | Out-Null; Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://localhost:%UI_PORT% | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 if %tries% lss 60 (
  timeout /t 1 /nobreak >nul
  goto wait
)

start "" http://localhost:%UI_PORT%
echo Ready. Close the two "Study Copilot" windows to stop it.
timeout /t 4 >nul
