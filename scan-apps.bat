@echo off
REM Teach Friday every app installed on this laptop so "open <app>" works.
REM Run this once now, and again any time you install a new app.
REM Safe to re-run: existing entries are kept, only new apps are added.

setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "FRIDAY_PYTHON=.venv\Scripts\python.exe"
) else (
    set "FRIDAY_PYTHON=python"
)

"%FRIDAY_PYTHON%" -m friday.os_adapters.app_scan
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo App scan exited with code %EXIT_CODE%.
    pause
)

endlocal & exit /b %EXIT_CODE%
