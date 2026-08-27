@echo off
REM Open Friday's saved Edge profile so you can sign in to a site once.
REM Sign in, then close the browser window. Friday reuses that session later.
REM Optional: pass a URL, e.g.  edge-signin.bat https://github.com

setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "FRIDAY_PYTHON=.venv\Scripts\python.exe"
) else (
    set "FRIDAY_PYTHON=python"
)

echo Opening Friday's browser profile. Sign in, then close the window.
"%FRIDAY_PYTHON%" -m friday.browser login %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Sign-in helper exited with code %EXIT_CODE%.
    pause
)

endlocal & exit /b %EXIT_CODE%
