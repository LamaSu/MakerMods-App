@echo off
setlocal

set SCRIPT_DIR=%~dp0
set PYTHON=%SCRIPT_DIR%.venv\Scripts\python.exe

if not exist "%PYTHON%" (
  echo Error: .venv not found. Run install.bat first.
  exit /b 1
)

echo Starting LeRobot UI at http://localhost:8000
cd /d "%SCRIPT_DIR%"
"%PYTHON%" -m backend.main
endlocal
