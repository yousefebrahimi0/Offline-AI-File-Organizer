@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.9 or later from python.org.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv ".venv" || exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip || exit /b 1
".venv\Scripts\python.exe" -m pip install -e ".[gui]" || exit /b 1
".venv\Scripts\offline-ai-organizer-gui.exe"
