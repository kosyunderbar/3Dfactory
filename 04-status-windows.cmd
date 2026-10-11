@echo off
setlocal DisableDelayedExpansion
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows-dev.ps1" status
set "factoryStatus=%ERRORLEVEL%"
echo.
echo If tools are missing, run 01-prepare-windows.cmd first.
pause
exit /b %factoryStatus%
