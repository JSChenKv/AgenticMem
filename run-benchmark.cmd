@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
"%~dp0.venv\Scripts\python.exe" -m lab.dojo %*
if errorlevel 1 pause
