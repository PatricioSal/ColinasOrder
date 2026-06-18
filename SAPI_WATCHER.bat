@echo off
cd /d "%~dp0"
title SAPI_WATCHER Launcher

echo ============================================================
echo  Checking for Updates...
echo ============================================================
git pull origin main 2>nul
if %errorlevel% neq 0 (
    echo [Info] Git not detected, offline, or repository branch tracking mismatch. Skipping update check.
)
echo ============================================================
echo.

:: Check for basic prerequisites (git, python, node)
where git >nul 2>&1
if %errorlevel% neq 0 goto :run_setup
where py >nul 2>&1
if %errorlevel% neq 0 (
    where python >nul 2>&1
    if %errorlevel% neq 0 goto :run_setup
)
where node >nul 2>&1
if %errorlevel% neq 0 goto :run_setup

:: Check if .env exists in root
if not exist ".env" goto :run_setup

:: If we get here, basic prerequisites are present. Let's make sure python packages and node modules are installed
echo ============================================================
echo  Verifying library dependencies...
echo ============================================================
:: Find Python command
set PYTHON_CMD=py
where py >nul 2>&1
if %errorlevel% neq 0 set PYTHON_CMD=python

%PYTHON_CMD% -m pip install -q -r src\requirements.txt
if %errorlevel% neq 0 (
    echo [Warning] Python library installation returned an error.
)

call npm install --prefix src --quiet
if %errorlevel% neq 0 (
    echo [Warning] Node.js package installation returned an error.
)

echo ============================================================
echo  Launching SAPI_WATCHER...
echo ============================================================
start "" %PYTHON_CMD% src\dashboard.py
exit /b

:run_setup
echo ============================================================
echo  Missing dependencies or .env config detected!
echo  Running setup assistant with Administrator privileges...
echo ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0src\setup_prerequisites.ps1\"' -Verb RunAs"
echo.
echo  Please complete the setup in the elevated window.
echo  Once setup is complete, you can launch SAPI_WATCHER.
echo ============================================================
pause
exit /b
