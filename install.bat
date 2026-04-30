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
    echo [ERROR] Python not found.
    echo         Download from https://python.org and make sure to check
    echo         "Add Python to PATH" during install.
    pause
    exit /b 1
)
echo [OK] Python found.

:: Create venv
echo [1/4] Creating virtual environment...
if exist venv rmdir /s /q venv
python -m venv venv
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

:: Install deps (NO pywin32 — DPAPI handled via ctypes)
echo [2/4] Installing dependencies...
venv\Scripts\python.exe -m pip install --upgrade pip --quiet
venv\Scripts\pip install pystray Pillow pycryptodome curl_cffi pyinstaller --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

:: Build exe — onedir (NOT onefile) avoids DLL ordinal errors
:: curl_cffi bundles native C libs that need to sit alongside the exe
echo [3/4] Building executable...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist "Claude Counter.spec" del "Claude Counter.spec"

venv\Scripts\pyinstaller ^
    --onedir ^
    --windowed ^
    --name "Claude Counter" ^
    --collect-all curl_cffi ^
    --collect-all pystray ^
    --hidden-import PIL ^
    --hidden-import Crypto ^
    claude_counter_win.py

if not exist "dist\Claude Counter\Claude Counter.exe" (
    echo [ERROR] Build failed. Check output above.
    pause
    exit /b 1
)

:: Install — copy whole folder to AppData
echo [4/4] Installing...
set INSTALL_DIR=%LOCALAPPDATA%\ClaudeCounter
if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"
xcopy /e /i /q "dist\Claude Counter" "%INSTALL_DIR%"

:: Add to Startup (auto-launch on login)
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
copy /Y "%INSTALL_DIR%\Claude Counter.exe" "%STARTUP%\Claude Counter.exe" >nul

echo.
echo  [OK] Done! Claude Counter installed to %INSTALL_DIR%
echo       Auto-launches on next login.
echo       Launching now...
echo.
start "" "%INSTALL_DIR%\Claude Counter.exe"
pause
