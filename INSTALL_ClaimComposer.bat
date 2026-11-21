@echo off
rem Installs ClaimComposer for this user in %LOCALAPPDATA%\Programs\ClaimComposer
rem with a desktop shortcut and a Start menu entry.
title Install ClaimComposer
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\setup.ps1" -Mode install -Root "%~dp0."
if errorlevel 1 pause
