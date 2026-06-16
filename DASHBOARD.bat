@echo off
:: ============================================================
::  WhatsApp Order Bot — Dashboard Launcher
::  Double-click to open the desktop app.
::  The app will start all services automatically.
:: ============================================================

title WhatsApp Order Bot
cd /d "%~dp0"
py dashboard.py
