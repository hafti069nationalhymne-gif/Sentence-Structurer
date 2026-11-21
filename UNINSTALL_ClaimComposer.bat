@echo off
rem Removes ClaimComposer for this user. Runs from a temporary copy so the folder can be deleted.
title Uninstall ClaimComposer
set "CC_TMP=%TEMP%\claimcomposer-uninstall.ps1"
copy /y "%~dp0installer\setup.ps1" "%CC_TMP%" >nul
cd /d "%TEMP%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%CC_TMP%" -Mode uninstall -Root "%TEMP%"
del "%CC_TMP%" >nul 2>&1
