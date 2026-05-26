@echo off
REM ================================================================
REM  Autonomous Browser Agent — Windows Startup Script
REM ================================================================

echo.
echo  ===================================================
echo   Autonomous Browser Agent ^| AI-Powered Web Operator
echo  ===================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.11+ and try again.
    pause ^& exit /b 1
)

REM Activate venv
if exist "venv\Scripts\activate.bat" (
    echo [*] Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo [!] No venv found. Creating one...
    python -m venv venv
    call venv\Scripts\activate.bat
    echo [*] Upgrading pip...
    python -m pip install --upgrade pip --quiet
    echo [*] Installing dependencies (this may take a few minutes)...
    pip install -r requirements.txt --quiet
    echo [*] Attempting to install browser-use from GitHub...
    pip install "git+https://github.com/browser-use/browser-use.git" --quiet 2>nul
    echo [*] Installing Playwright Chromium browser...
    playwright install chromium
)

REM Check .env
if not exist ".env" (
    echo [ERROR] .env file not found!
    echo         Edit the .env file and set your GROQ_API_KEY.
    pause ^& exit /b 1
)

REM Warn if still placeholder key
findstr /C:"GROQ_API_KEY=your_groq_api_key_here" .env >nul 2>&1
if not errorlevel 1 (
    echo.
    echo [WARNING] GROQ_API_KEY is still the placeholder!
    echo           Get your free key at: https://console.groq.com
    echo           Then edit .env and replace the placeholder.
    echo.
    pause
)

REM Validate imports
echo [*] Validating backend imports...
python test_imports.py
if errorlevel 1 (
    echo.
    echo [ERROR] Import check failed. Fix the issues above before starting.
    pause ^& exit /b 1
)

echo.
echo [*] Starting server...
echo.
echo     UI      ^|  http://localhost:8000
echo     API     ^|  http://localhost:8000/api/docs
echo     Health  ^|  http://localhost:8000/health
echo.
echo  Press Ctrl+C to stop the server.
echo.

python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

pause
