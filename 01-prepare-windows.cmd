@echo off
setlocal DisableDelayedExpansion
echo Factory simulator - first-time preparation (Windows x64)
echo Internet is required. Existing settings and database files are preserved.
echo Stop this project's servers before preparing an updated version.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows-dev.ps1" setup
if errorlevel 1 goto failed
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows-dev.ps1" build
if errorlevel 1 goto failed
echo.
echo Preparation complete. Next: double-click 02-start-windows.cmd
pause
exit /b 0
:failed
echo.
echo Preparation failed. Read the error above and WINDOWS-START.md.
echo Do not delete .env or .build-cache to retry.
pause
exit /b 1
