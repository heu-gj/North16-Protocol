@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_gui.ps1"
if errorlevel 1 pause
