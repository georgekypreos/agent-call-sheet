@echo off
REM Agent Call Sheet — CSV mode launcher
REM Use this when you don't have API keys yet. Drop a Courted CSV export
REM into data\courted_agents.csv before running.

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

if not exist "data\courted_agents.csv" (
  echo.
  echo ============================================================
  echo  Drop your Courted CSV export at:
  echo    %CD%\data\courted_agents.csv
  echo  Then run this script again.
  echo ============================================================
  if not exist "data" mkdir data
  pause
  exit /b 0
)

echo.
echo Starting dashboard in CSV mode...
".venv\Scripts\python.exe" csv_mode.py
pause
