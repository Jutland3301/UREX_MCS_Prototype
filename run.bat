@echo off
REM DEVELOPMENT ONLY - release users should run the signed UREX_MCS_Simulator.exe.
cd /d "%~dp0"
py -3 main.py
pause