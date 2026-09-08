@echo off
REM Options Strategy Analyzer - Development Startup Script
REM This script starts both backend and frontend servers

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ╔═══════════════════════════════════════════════════════════════╗
echo ║  Options Strategy Analyzer - Development Environment          ║
echo ║  Starting Backend + Frontend...                               ║
echo ╚═══════════════════════════════════════════════════════════════╝
echo.

REM Prefer the existing project environment; otherwise create .venv.
if exist "venv\Scripts\python.exe" (
    set "PYTHON=venv\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    echo [1/3] Creating Python virtual environment...
    python -m venv .venv
    echo ✓ Virtual environment created
    set "PYTHON=.venv\Scripts\python.exe"
    echo.
)

REM Install dependencies into the selected project environment
echo [2/3] Checking Python dependencies...
"%PYTHON%" -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Python dependencies could not be installed.
    echo        Check the pip output above, then run start-dev.bat again.
    pause
    exit /b 1
)
echo ✓ Dependencies installed
echo.

REM Start backend in new terminal
echo [3/3] Starting servers...
echo Starting backend on http://127.0.0.1:8000
timeout /t 1 /nobreak >nul
start "OSA Backend" cmd /k "title OSA Backend (port 8000) && cd /d ""%~dp0"" && set PYTHONPATH=. && ""%PYTHON%"" -m uvicorn server.main:app --reload --host 127.0.0.1 --port 8000"

REM Wait a moment for backend to start
timeout /t 3 /nobreak >nul

REM Start frontend in another new terminal
echo Starting frontend on http://localhost:5173
cd frontend
call npm install -q
if errorlevel 1 (
    echo [ERROR] Frontend dependencies could not be installed.
    echo        Check the npm output above, then run start-dev.bat again.
    pause
    exit /b 1
)
timeout /t 1 /nobreak >nul
start "OSA Frontend" cmd /k "title OSA Frontend (port 5173) && cd /d ""%~dp0frontend"" && npm run dev"
cd ..

echo.
echo ✓ Both servers should now be starting...
echo.
echo 📊 Frontend: http://localhost:5173
echo 📡 Backend API: http://127.0.0.1:8000
echo 📖 API Documentation: http://127.0.0.1:8000/docs
echo.
echo To start development:
echo  1. Wait 5-10 seconds for both servers to initialize
echo  2. Open http://localhost:5173 in your browser
echo  3. Go to Data Manager and import "demo" data
echo  4. Start using the app!
echo.
echo ℹ️  Both terminal windows should remain open while developing
echo ℹ️  Press Ctrl+C in either terminal to stop the servers
echo.

endlocal
pause
