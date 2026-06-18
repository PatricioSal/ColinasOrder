@echo off
:: ============================================================
::  WhatsApp Order Bot — Desktop Shortcut Creator
::  Run this ONCE to create a Desktop icon.
::  After that, double-click the Desktop icon to start the bot.
:: ============================================================

title Creating Desktop Shortcut...
cd /d "%~dp0"

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

echo  Creating Desktop shortcut for WhatsApp Order Bot...
echo.

:: Use PowerShell to create a proper .lnk shortcut
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\WhatsApp Order Bot.lnk'); " ^
  "$s.TargetPath = '%~dp0DASHBOARD.bat'; " ^
  "$s.WorkingDirectory = '%~dp0'; " ^
  "$s.WindowStyle = 1; " ^
  "$s.IconLocation = 'shell32.dll, 277'; " ^
  "$s.Description = 'Start the WhatsApp Order Bot Dashboard'; " ^
  "$s.Save()"

if %errorlevel%==0 (
    echo  ============================================================
    echo   SUCCESS! Shortcut created on your Desktop:
    echo     "WhatsApp Order Bot"
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
