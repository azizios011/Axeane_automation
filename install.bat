@echo off
title Axeane Automation - Installer
color 0A

echo ==========================================
echo  Axeane Automation - Environment Setup
echo ==========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [ERROR] Python is not installed or not in your system PATH.
    echo Please install Python from https://www.python.org/ 
    echo IMPORTANT: Check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo [1/4] Creating virtual environment (venv) in root directory...
python -m venv venv

echo [2/4] Activating virtual environment...
call venv\Scripts\activate

echo [3/4] Installing Python dependencies...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt

echo [4/4] Installing Playwright Chromium browser (this may take a minute)...
playwright install chromium

echo.
echo ==========================================
color 0A
echo  [SUCCESS] Installation Complete!
echo  You can now start the app by double-clicking: run.bat
echo ==========================================
pause