@echo off
REM DEVELOPMENT ONLY - release users should run the signed UREX_MCS_Simulator.exe.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Python 3 is required to run from source.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install Python dependencies.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" main.py
pause