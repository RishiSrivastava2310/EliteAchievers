@echo off
cd /d "%~dp0"
call run.bat demo
set "AKI_EXIT=%errorlevel%"
echo.
pause
exit /b %AKI_EXIT%

