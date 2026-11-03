@echo off
setlocal
cd /d "%~dp0"

if not exist ".env" (
    echo ERROR: .env is missing. Copy .env.example to .env and configure it.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
    if errorlevel 1 (
        echo ERROR: Could not create virtual environment. Install Python 3.11 or newer.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.11 or newer is required.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import aiogram, aiosqlite, dotenv, argon2, PIL, tzdata" >nul 2>&1
if errorlevel 1 (
    echo Installing project dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Dependency installation failed.
        pause
        exit /b 1
    )
)

echo Starting Telegram bot. Press Ctrl+C to stop it.
echo Keep this window open while the bot is running.
".venv\Scripts\python.exe" main.py
if errorlevel 1 (
    echo Bot stopped with an error. See messages above.
    pause
)
endlocal
