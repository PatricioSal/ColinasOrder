@echo off
:: ============================================================
::  WhatsApp Order Bot — Desktop Shortcut Creator
::  Run this ONCE to create a Desktop icon.
::  After that, double-click the Desktop icon to start the bot.
:: ============================================================

title Creating Desktop Shortcut...
:: Resolve the parent root directory (one level up from src/)
for %%i in ("%~dp0..") do set "ROOT_DIR=%%~fi"
cd /d "%ROOT_DIR%"

echo.
echo  ============================================================
echo   Checking for repository updates from GitHub...
echo  ============================================================
git pull 2>nul
if %errorlevel% neq 0 (
    echo   [Info] Git not detected or offline. Skipping update check.
)
echo  ============================================================
echo.

echo  Creating Desktop shortcut for SAPI_WATCHER...
echo.

:: Use PowerShell to create a proper .lnk shortcut pointing to SAPI_WATCHER.bat in the root
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\SAPI_WATCHER.lnk'); " ^
  "$s.TargetPath = '%ROOT_DIR%\SAPI_WATCHER.bat'; " ^
  "$s.WorkingDirectory = '%ROOT_DIR%'; " ^
  "$s.WindowStyle = 1; " ^
  "$s.IconLocation = 'shell32.dll, 277'; " ^
  "$s.Description = 'Start the SAPI_WATCHER Dashboard'; " ^
  "$s.Save()"

if %errorlevel%==0 (
    echo  ============================================================
    echo   SUCCESS! Shortcut created on your Desktop:
    echo     "SAPI_WATCHER"
    echo.
    echo   Double-click it anytime to start the bot.
    echo  ============================================================
) else (
    echo  ============================================================
    echo   ERROR: Could not create shortcut.
    echo   Try right-clicking this file and choosing
    echo   "Run as administrator".
    echo  ============================================================
)

echo.
pause
