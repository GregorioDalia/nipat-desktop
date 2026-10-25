@echo off
setlocal DisableDelayedExpansion
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\setup.ps1"
set "NIPAT_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %NIPAT_EXIT%
