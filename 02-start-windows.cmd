@echo off
setlocal DisableDelayedExpansion
echo Starting the local factory simulator services...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows-dev.ps1" up
if errorlevel 1 goto failed
start "" "http://127.0.0.1:5173"
echo.
echo Ready. Select a scenario and start it in the browser.
echo Closing the browser does not stop the servers.
echo To stop: double-click 03-stop-windows.cmd
pause
exit /b 0
:failed
echo.
echo Startup failed. For first use, run 01-prepare-windows.cmd.
echo Read the error above and WINDOWS-START.md.
pause
exit /b 1
