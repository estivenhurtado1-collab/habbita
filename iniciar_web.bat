@echo off
cd /d "%~dp0"
echo Habitta ia - http://127.0.0.1:8000
python -m uvicorn web.app:app --reload --host 127.0.0.1 --port 8000
pause
