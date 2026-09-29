@echo off
rem One click: opens Study Copilot in its own window (details in scripts\launcher.ps1).
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\launcher.ps1"
