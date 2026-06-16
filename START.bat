@echo off
:: ============================================================
::  WhatsApp Order Bot — Launcher
::  Double-click this file to start both services.
:: ============================================================

title WhatsApp Order Bot — Launcher

:: Change to the folder where this script lives (works from any location)
cd /d "%~dp0"

echo.
echo  ============================================================
echo    WhatsApp Order Bot — Starting...
echo  ============================================================
echo.
echo  [1/2] Starting Python Flask webhook  (port 5050)
echo  [2/2] Starting Node.js WhatsApp listener (port 3000)
echo.
echo  Both windows will open. Do NOT close them while the bot runs.
echo  To stop: close both windows, or press Ctrl+C in each.
echo.
echo  ============================================================
echo.

:: ----- Window 1: Python Flask webhook -----
start "WhatsApp Bot — Python Webhook" cmd /k "title WhatsApp Bot — Python Webhook && color 0A && echo. && echo  [Python] WhatsApp Webhook starting on port 5050... && echo. && py whatsapp_webhook.py"

:: Brief pause so Python initialises first
timeout /t 3 /nobreak >nul

:: ----- Window 2: Node.js WhatsApp listener -----
start "WhatsApp Bot — Node Listener" cmd /k "title WhatsApp Bot — Node Listener && color 0B && echo. && echo  [Node.js] WhatsApp Listener starting on port 3000... && echo  (Scan the QR code in WhatsApp the first time) && echo. && node whatsapp_listener.js"

echo  Both services launched. You can close this launcher window.
echo.
timeout /t 4 /nobreak >nul
exit
