@echo off
cd /d "%~dp0"
title SAPI_WATCHER Launcher

echo ============================================================
echo  Checking for Updates...
echo ============================================================
git pull origin main 2>nul
if %errorlevel% neq 0 (
    echo [Info] Git not detected, offline, or repository branch mismatch. Skipping update check.
)
echo ============================================================
echo.

:: ── Find a working Python ──────────────────────────────────────
:: We must actually RUN python to check, because "where python"
:: can find the Windows Store app alias (a fake stub).
set "PYTHON_CMD="

:: Try 'py' launcher first (most reliable on Windows)
py --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=py"
    goto :python_found
)

:: Try 'python' on PATH
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
    goto :python_found
)

:: Try common install paths
for %%V in (313 312 311 310) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        goto :python_found
    )
)
for %%V in (313 312 311 310) do (
    if exist "C:\Program Files\Python%%V\python.exe" (
        set "PYTHON_CMD=C:\Program Files\Python%%V\python.exe"
        goto :python_found
    )
)

:: Python not found at all
goto :run_setup

:python_found
echo [OK] Python found: %PYTHON_CMD%

:: ── Check Node.js ──────────────────────────────────────────────
node --version >nul 2>&1
if %errorlevel% neq 0 goto :run_setup
echo [OK] Node.js found.

:: ── Check .env ─────────────────────────────────────────────────
if not exist ".env" goto :run_setup
echo [OK] .env file found.
echo.

:: ── Verify library dependencies ────────────────────────────────
echo ============================================================
echo  Verifying library dependencies...
echo ============================================================
"%PYTHON_CMD%" -m pip install -q -r src\requirements.txt 2>nul
if %errorlevel% neq 0 (
    echo [Warning] Python library installation returned an error.
)

pushd src
set PUPPETEER_SKIP_DOWNLOAD=true
call npm install --no-audit --no-fund 2>nul
if %errorlevel% neq 0 (
    echo [Warning] npm install failed. Retrying clean install...
    if exist "package-lock.json" del /f /q package-lock.json
    if exist "node_modules" rmdir /s /q node_modules
    call npm install --no-audit --no-fund
)
set PUPPETEER_SKIP_DOWNLOAD=
popd

:: ── Launch Dashboard ───────────────────────────────────────────
echo ============================================================
echo  Launching SAPI_WATCHER...
echo ============================================================
"%PYTHON_CMD%" src\dashboard.py
if %errorlevel% neq 0 (
    echo.
    echo [Error] SAPI_WATCHER crashed or failed to start (exit code: %errorlevel%).
    pause
)
exit /b

:run_setup
echo ============================================================
echo  Missing dependencies or .env config detected!
echo  Running setup assistant with Administrator privileges...
echo ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath powershell.exe -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0src\setup_prerequisites.ps1\"' -WorkingDirectory '%~dp0.' -Verb RunAs"
echo.
echo  Please complete the setup in the elevated window.
echo  Once setup is complete, re-run SAPI_WATCHER to launch.
echo ============================================================
pause
exit /b
