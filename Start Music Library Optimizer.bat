@echo off
rem Start Music Library Optimizer — starts the backend and opens the browser.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo Python not found on PATH. Install Python from https://www.python.org/
    pause
    exit /b 1
)
start "" /min python start_app.py
exit /b 0