@echo off
REM ============================================================
REM  NovelForge - double-click this file to start writing.
REM
REM  This launches the full application. Everything works here:
REM  creating novels, writing, the map maker, the corkboard, the
REM  outline, settings, compiling and backups.
REM
REM  (The web redesign is unfinished and lives behind --web.
REM   Do not use it for real writing yet.)
REM ============================================================
setlocal

set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
set "PYW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"

REM Fall back to whatever Python is on PATH.
if not exist "%PY%" set "PY=python"
if not exist "%PYW%" set "PYW=%PY%"

cd /d "%~dp0"

REM Is there a Python at all? The most common first-run problem, so say so
REM plainly instead of leaving a cryptic error.
"%PY%" --version >nul 2>nul
if errorlevel 1 (
    echo.
    echo NovelForge needs Python 3.13 or newer, and none was found.
    echo.
    echo   1. Download it free from https://www.python.org/downloads/
    echo   2. In the installer, tick "Add python.exe to PATH"
    echo   3. Then double-click Write.bat again
    echo.
    pause
    exit /b 1
)

REM First run only: fetch the two small libraries NovelForge needs, if they
REM are missing. This needs the internet once; after that it all works offline.
"%PY%" -c "import docx, PIL" >nul 2>nul
if errorlevel 1 (
    echo.
    echo NovelForge needs two small Python libraries: python-docx and Pillow.
    echo Installing them now. This happens once and needs an internet connection.
    echo.
    "%PY%" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo.
        echo The libraries could not be installed. Check your internet connection,
        echo then double-click Write.bat again.
        echo.
        pause
        exit /b 1
    )
)

REM pythonw.exe launches with no console window behind the app.
if exist "%PYW%" (
    start "" "%PYW%" -m novelforge
) else (
    "%PY%" -m novelforge
    if errorlevel 1 (
        echo.
        echo NovelForge could not start. The error is above.
        pause
    )
)

endlocal
