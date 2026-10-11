@echo off
setlocal DisableDelayedExpansion
echo Stopping this project's local servers and managed simulation...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows-dev.ps1" down
if errorlevel 1 goto failed
echo.
echo Stopped. Settings, database files and saved run history are preserved.
pause
exit /b 0
:failed
echo.
echo Stop failed. Read the error above and WINDOWS-START.md.
pause
exit /b 1
