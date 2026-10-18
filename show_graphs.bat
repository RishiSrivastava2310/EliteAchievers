@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
echo Preparing the patient graph demo...
".venv\Scripts\python.exe" scripts\build_showcase.py --ai --if-needed %*
if errorlevel 1 (
  echo Graph demo could not be prepared. Run setup.bat for missing libraries, or doctor.bat to check data.
  pause
  exit /b 1
)
echo Opening the graph demo in your browser.
set "AKI_SHOWCASE_URL="
set /p "AKI_SHOWCASE_URL="<"reports\showcase_open_url.txt"
start "" "%AKI_SHOWCASE_URL%"
exit /b 0
