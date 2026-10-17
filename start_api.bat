@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
echo AKI API: http://127.0.0.1:8000
echo API documentation: http://127.0.0.1:8000/docs
echo Press Ctrl+C to stop.
call run.bat serve %*
exit /b %errorlevel%

