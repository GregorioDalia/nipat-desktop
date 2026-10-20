@echo off
setlocal DisableDelayedExpansion
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\run.ps1" wizard
set "NIPAT_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %NIPAT_EXIT%
