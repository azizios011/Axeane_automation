@echo off
title Axeane Automation
color 0B

REM Ensure we are in the root directory where this .bat file lives
cd /d "%~dp0"

REM Check if virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    color 0C
    echo [ERROR] Virtual environment not found.
    echo Please run "install.bat" first to set up the environment.
    echo.
    pause
    exit /b 1
)

echo Activating environment and starting app...
call venv\Scripts\activate

REM Run the script inside the Router folder
python Router\run.py

echo.
echo [INFO] Application closed.
pause