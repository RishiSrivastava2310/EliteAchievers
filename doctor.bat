@echo off
cd /d "%~dp0"
call run.bat doctor
set "AKI_EXIT=%errorlevel%"
echo.
pause
exit /b %AKI_EXIT%
