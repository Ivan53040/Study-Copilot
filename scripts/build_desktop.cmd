@echo off
rem Build the Study Copilot desktop app (Tauri) and its Windows installer.
rem Double-click, or run from any folder. Needs Node.js and Rust (rustup).
setlocal
title Study Copilot - build desktop app
cd /d "%~dp0..\frontend" || goto :fail

where npm >nul 2>nul || (echo Node.js/npm was not found. Install Node.js, then try again. & goto :fail)
where cargo >nul 2>nul || (echo Rust was not found. Install it from https://rustup.rs, then try again. & goto :fail)

if not exist node_modules (
  echo Installing frontend packages...
  call npm install || goto :fail
)

echo Freezing the backend with PyInstaller...
pushd "%~dp0.."
if exist .venv\Scripts\python.exe (set "PY=.venv\Scripts\python.exe") else (set "PY=python")
%PY% -m pip install --quiet pyinstaller || (popd & goto :fail)
%PY% scripts\build_backend.py || (popd & goto :fail)
popd

echo Building the desktop app. The first build can take several minutes...
call npm run tauri build || goto :fail

echo.
echo Done. The installer is in:
echo   %CD%\src-tauri\target\release\bundle\nsis
dir /b "src-tauri\target\release\bundle\nsis\*.exe"
start "" explorer "src-tauri\target\release\bundle\nsis"
echo.
pause
exit /b 0

:fail
echo.
echo Build failed. Scroll up for the error.
pause
exit /b 1
