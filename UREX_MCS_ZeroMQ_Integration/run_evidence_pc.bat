@echo off
cd /d "%~dp0"
python -m evidence_suite.run --plan evidence-plan.local.json
pause
