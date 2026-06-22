@echo off
cd /d "%~dp0"
title SAPI_WATCHER

:: ── Auto-update from GitHub ────────────────────────────────────
git pull origin main 2>nul
if %errorlevel% neq 0 (
    echo [Info] Git not available or offline. Skipping update check.
)

:: ── Find Python ────────────────────────────────────────────────
:: We run python --version instead of using "where" because the
:: Windows Store app alias fools "where" but fails when executed.
set "PYTHON_CMD="

py --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=py"
    goto :found_python
)

python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
    goto :found_python
)

for %%V in (313 312 311 310) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        goto :found_python
    )
)
for %%V in (313 312 311 310) do (
    if exist "C:\Program Files\Python%%V\python.exe" (
        set "PYTHON_CMD=C:\Program Files\Python%%V\python.exe"
        goto :found_python
    )
)

goto :needs_setup

:found_python

:: ── Check Node.js ──────────────────────────────────────────────
node --version >nul 2>&1
if %errorlevel% neq 0 goto :needs_setup

:: ── Check .env ─────────────────────────────────────────────────
if not exist ".env" goto :needs_setup

:: ── Quick dependency check (silent, fast) ──────────────────────
"%PYTHON_CMD%" -m pip install -q -r src\requirements.txt 2>nul

pushd src
set PUPPETEER_SKIP_DOWNLOAD=true
call npm install --no-audit --no-fund --silent 2>nul
set PUPPETEER_SKIP_DOWNLOAD=
popd

:: ── Launch ─────────────────────────────────────────────────────
echo.
echo ============================================================
echo  Starting SAPI_WATCHER...
echo ============================================================
echo.
"%PYTHON_CMD%" src\dashboard.py
if %errorlevel% neq 0 (
    echo.
    echo [Error] SAPI_WATCHER exited with code %errorlevel%.
    pause
)
exit /b

:: ── First-time setup ───────────────────────────────────────────
:needs_setup
echo.
echo ============================================================
echo  First-time setup required.
echo  An administrator window will open to install dependencies.
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process powershell.exe -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File ""%~dp0src\setup_prerequisites.ps1""' -WorkingDirectory '%~dp0.' -Verb RunAs"
echo.
echo  Complete the setup, then re-run this shortcut.
echo.
pause
exit /b
