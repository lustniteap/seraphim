@echo off
rem Double-click this file to start Seraphim.
rem The first run sets things up (about a minute); after that it opens straight away.
setlocal EnableExtensions
cd /d "%~dp0"
title Seraphim
rem Read and write text as UTF-8, which Seraphim's files and messages use.
set PYTHONUTF8=1
echo.
echo Seraphim
echo.

if exist ".venv\Scripts\seraphim-web.exe" goto run

rem ---- First run: find Python 3.9 or newer. "py" is the launcher the python.org installer adds;
rem ---- "python" can be a Microsoft Store stand-in, which fails this check and is skipped.
set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto setup
python -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto setup

echo Seraphim needs Python 3.9 or newer.
echo Opening the download page. Install it, and on the first screen of the installer
echo tick "Add python.exe to PATH". Then double-click Seraphim again.
start "" "https://www.python.org/downloads/windows/"
pause
exit /b 1

:setup
echo First run: setting up Seraphim. This takes about a minute...
%PY% -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -q --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -q -e ".[web]"
if errorlevel 1 goto failed
echo Done.
echo.
goto run

:failed
if exist ".venv" rmdir /s /q ".venv"
echo.
echo Setup didn't finish. Check your internet connection and double-click Seraphim again.
pause
exit /b 1

:run
rem Set SERAPHIM_SETUP_ONLY to stop here (used to test the setup without starting the app).
if defined SERAPHIM_SETUP_ONLY exit /b 0
".venv\Scripts\seraphim-web.exe"
if errorlevel 1 (
  echo.
  echo Seraphim stopped. Scroll up to see why, then double-click Seraphim again.
  pause
)
exit /b 0
