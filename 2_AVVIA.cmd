@echo off
setlocal DisableDelayedExpansion
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\run.ps1" wizard
set "NIPAT_EXIT=%ERRORLEVEL%"
if "%NIPAT_EXIT%"=="85" exit /b 0
echo.
pause
exit /b %NIPAT_EXIT%
