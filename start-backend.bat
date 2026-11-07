@echo off
echo ========================================================
echo Starting SEO Agent Team - FastAPI Backend Worker (Port 8000)
echo ========================================================
cd /d "%~dp0backend"
"%~dp0backend\venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
pause
