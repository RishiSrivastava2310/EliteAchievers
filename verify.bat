@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set "AKI_API_KEY="
set "AKI_CORS_ORIGINS="
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  exit /b 1
)
:choose_test_temp
set "AKI_TEST_TEMP=%CD%\reports\test-tmp-%RANDOM%-%RANDOM%"
if exist "%AKI_TEST_TEMP%" goto choose_test_temp
mkdir "%AKI_TEST_TEMP%"
if errorlevel 1 exit /b 1
set "PYTEST_DEBUG_TEMPROOT=%AKI_TEST_TEMP%"
".venv\Scripts\python.exe" -m pytest -q -p no:cacheprovider --junitxml=reports\pytest.xml
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" scripts\audit_model.py
if errorlevel 1 exit /b 1
if /i "%~1"=="--http" (
  ".venv\Scripts\python.exe" scripts\smoke_http.py
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" scripts\write_improvement_report.py
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" scripts\write_completion_report.py
if errorlevel 1 exit /b 1
echo Verification passed. Use verify.bat --http to include a local HTTP smoke check.
exit /b 0
