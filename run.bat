@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  call setup.bat
  if errorlevel 1 exit /b 1
)
if not exist "artifacts\model.joblib" (
  call setup.bat
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m aki %*
set "AKI_EXIT=%errorlevel%"
if not "%AKI_EXIT%"=="0" echo Command failed. See the error above.
exit /b %AKI_EXIT%

