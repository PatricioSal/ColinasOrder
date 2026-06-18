@echo off
:: ============================================================
::  WhatsApp Order Bot — One-Click Automated Setup
::  Double-click this file to install all prerequisites and libraries.
:: ============================================================

title WhatsApp Order Bot — Setup Assistant

:: Check for administrative rights
net session >nul 2>&1
if %errorLevel% == 0 (
    goto :run
) else (
    echo.
    echo  ============================================================
    echo   This setup requires administrator permissions to install
    echo   Python, Node.js, PostgreSQL, and SQL Server ODBC drivers.
    echo   
    echo   Requesting administrator privileges...
    echo  ============================================================
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

:run
cd /d "%~dp0"
cls
echo.
echo  ============================================================
echo    Starting Automated Setup for WhatsApp Order Bot...
echo  ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_prerequisites.ps1"

echo.
echo  ============================================================
echo    Setup process finished. Press any key to close.
echo  ============================================================
echo.
pause
