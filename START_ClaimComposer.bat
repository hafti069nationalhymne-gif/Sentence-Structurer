@echo off
rem ClaimComposer for Windows: double-click to set up once and start the app.
rem Closing this window stops the app.
title ClaimComposer
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\setup.ps1" -Mode start -Root "%~dp0."
if errorlevel 1 pause
