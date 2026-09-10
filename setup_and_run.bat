@echo off
REM DEVELOPMENT ONLY - release users should run the signed UREX_MCS_Simulator.exe.
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install Python dependencies.
    pause
    exit /b 1
)
py -3 main.py
pause
