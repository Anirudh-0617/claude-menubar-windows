@echo off
:: Claude Counter — Windows Installer
:: Run this once to set up the app.

echo.
echo  Claude Counter -- Windows Setup
echo  ================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Download from python.org and try again.
    pause
    exit /b 1
)

:: Create venv
echo [1/4] Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo [ERROR] Failed to create venv.
    pause
    exit /b 1
)

:: Install deps
echo [2/4] Installing dependencies...
venv\Scripts\pip install --upgrade pip --quiet
venv\Scripts\pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

:: Build exe with PyInstaller
echo [3/4] Building executable...
venv\Scripts\pip install pyinstaller --quiet
venv\Scripts\pyinstaller --onefile --windowed --name "Claude Counter" --icon=icon.ico claude_counter_win.py 2>nul
if not exist "dist\Claude Counter.exe" (
    venv\Scripts\pyinstaller --onefile --windowed --name "Claude Counter" claude_counter_win.py
)

:: Create shortcut in Startup folder (auto-launch on login)
echo [4/4] Installing...
set DEST=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
copy /Y "dist\Claude Counter.exe" "%DEST%\Claude Counter.exe" >nul

echo.
echo  [OK] Done! Claude Counter is installed.
echo       It will auto-launch on next login.
echo       Launching now...
echo.
start "" "dist\Claude Counter.exe"
pause
