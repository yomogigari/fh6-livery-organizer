@echo off
setlocal
cd /d "%~dp0" || exit /b 80
set "PYTHONUTF8=1"
if defined LOCALAPPDATA (
  set "LOGROOT=%LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge"
) else (
  set "LOGROOT=%TEMP%\LO4FH6"
)
if not exist "%LOGROOT%" mkdir "%LOGROOT%" 2>nul
if not exist "%LOGROOT%" exit /b 81
set "LOGFILE=%LOGROOT%\viewer-gui-quiet-startup.log"
where uv >nul 2>nul
if errorlevel 1 (
  >"%LOGFILE%" echo ERROR: uv not found on PATH.
  exit /b 127
)
uv run --no-project --python 3.12 --script ".\viewer_gui.py" >"%LOGFILE%" 2>&1
exit /b %errorlevel%
