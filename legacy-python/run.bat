@echo off
REM Agent Call Sheet launcher
REM First run sets up a virtual environment and installs dependencies, then starts the dashboard.

cd /d "%~dp0"

if not exist ".venv" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo.
    echo ERROR: could not create venv. Make sure Python 3.9+ is installed and on PATH.
    echo Download Python from https://www.python.org/downloads/
    pause
    exit /b 1
  )
)

echo Installing/updating dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet

if not exist "config.json" (
  echo.
  echo config.json not found. Copying template...
  copy config.example.json config.json >nul
  echo.
  echo ============================================================
  echo  EDIT config.json and paste your API keys, then run me again.
  echo ============================================================
  notepad config.json
  pause
  exit /b 0
)

echo.
echo Starting dashboard...
".venv\Scripts\python.exe" app.py
pause
