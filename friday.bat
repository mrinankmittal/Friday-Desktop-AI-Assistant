@echo off
REM Launch Friday from anywhere. Double-click this file or pin it to the taskbar.
REM Uses the project's virtual environment if one exists.

setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "FRIDAY_PYTHON=.venv\Scripts\python.exe"
) else (
    set "FRIDAY_PYTHON=python"
)

"%FRIDAY_PYTHON%" run.py
set "EXIT_CODE=%ERRORLEVEL%"

REM Keep the window open on failure so a double-click still shows the error.
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Friday exited with code %EXIT_CODE%.
    pause
)

endlocal & exit /b %EXIT_CODE%
