@echo off
setlocal
cd /d "%~dp0" || exit /b 80
set "PYTHONUTF8=1"
if defined LOCALAPPDATA (
  set "LOGROOT=%LOCALAPPDATA%\Navigator-Bridge-for-FH6"
) else (
  set "LOGROOT=%TEMP%\Navigator-Bridge-for-FH6"
)
if not exist "%LOGROOT%" mkdir "%LOGROOT%" 2>nul
if not exist "%LOGROOT%" exit /b 81
set "LOGFILE=%LOGROOT%\navigator-bridge-quiet-startup.log"
where uv >nul 2>nul
if errorlevel 1 (
  >"%LOGFILE%" echo ERROR: uv not found on PATH.
  exit /b 127
)
uv run --no-project --python 3.12 ".\navigator-bridge-for-fh6.py" %* >"%LOGFILE%" 2>&1
exit /b %errorlevel%
