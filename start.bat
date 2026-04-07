@echo off
echo ╔══════════════════════════════════════╗
echo ║        Strange Street Startup        ║
echo ╚══════════════════════════════════════╝
echo.

REM Check if .env exists
if not exist .env (
    echo [SETUP] Creating .env file...
    copy .env.example .env
    echo.
    echo !! IMPORTANT: Open .env and replace YOUR_PASSWORD with your PostgreSQL password
    echo    Then run this script again.
    echo.
    pause
    exit /b
)

REM Install dependencies
echo [1/3] Installing dependencies...
pip install -r requirements.txt -q
echo   Done.
echo.

REM Start the app
echo [2/3] Starting Strange Street...
echo   Open your browser at: http://localhost:8000
echo   Press Ctrl+C to stop.
echo.
uvicorn main:app --reload --host 0.0.0.0 --port 8000
