@echo off
setlocal

set SCRIPT_DIR=%~dp0
set PYTHON_DIR=%SCRIPT_DIR%python
set PYTHON_VERSION=3.10.20
set BUILD_TAG=20260310
set TRIPLE=x86_64-pc-windows-msvc
set FILENAME=cpython-%PYTHON_VERSION%+%BUILD_TAG%-%TRIPLE%-install_only.tar.gz
set URL=https://github.com/astral-sh/python-build-standalone/releases/download/%BUILD_TAG%/%FILENAME%

echo === LeRobot UI -- Standalone Installer ===
echo.

if exist "%PYTHON_DIR%" (
  echo Python already installed at %PYTHON_DIR%, skipping download.
) else (
  echo Downloading Python %PYTHON_VERSION% for %TRIPLE%...
  curl -L --fail -o "%TEMP%\%FILENAME%" "%URL%"
  echo Extracting...
  tar -xzf "%TEMP%\%FILENAME%" -C "%SCRIPT_DIR%"
  del "%TEMP%\%FILENAME%"
  echo Python installed at %PYTHON_DIR%
)

if exist "%SCRIPT_DIR%.venv" (
  echo Virtual environment already exists at .venv, skipping creation.
) else (
  echo Creating virtual environment...
  "%PYTHON_DIR%\python.exe" -m venv "%SCRIPT_DIR%.venv"
  echo Virtual environment created at .venv
)

REM Install ffmpeg if not already present
where ffmpeg >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  echo ffmpeg already installed, skipping.
) else (
  echo Installing ffmpeg via winget...
  winget install --id Gyan.FFmpeg -e --silent
  if %ERRORLEVEL% NEQ 0 (
    echo WARNING: winget install failed. Install ffmpeg manually: https://ffmpeg.org/download.html
  )
)

echo.
echo Installing dependencies (this may take 5-15 minutes, ~2-4GB download)...
"%SCRIPT_DIR%.venv\Scripts\pip.exe" install --upgrade pip
"%SCRIPT_DIR%.venv\Scripts\pip.exe" install -r "%SCRIPT_DIR%requirements-standalone.txt"
REM Install neuracore last 
"%SCRIPT_DIR%.venv\Scripts\pip.exe" install neuracore 

echo.
echo ==========================================
echo Installation complete!
echo.
echo Run the app:  run.bat
echo Dev/inspect:  .venv\Scripts\activate
echo ==========================================
endlocal
