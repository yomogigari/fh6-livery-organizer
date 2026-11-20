@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
where uv >nul 2>nul
if errorlevel 1 (
  echo ERROR: uv is not installed or is not on PATH.
  pause
  exit /b 1
)
uv run --no-project --python 3.12 --script ".\viewer_gui.py"
set "status=%errorlevel%"
if not "%status%"=="0" (
  echo Viewer GUI launch failed. Exit code: %status%
  pause
)
exit /b %status%
