@echo off
REM Import your contacts (names, phone numbers, and emails) into Friday.
REM Export from Google Contacts as CSV, save it as "contacts (1).csv" in this
REM folder (keep the "E-mail 1 - Value" column), then run this. Safe to re-run:
REM existing contacts are kept and only get their email filled in.

setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "FRIDAY_PYTHON=.venv\Scripts\python.exe"
) else (
    set "FRIDAY_PYTHON=python"
)

"%FRIDAY_PYTHON%" -m engine.db
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Contact import exited with code %EXIT_CODE%.
    pause
)

endlocal & exit /b %EXIT_CODE%
