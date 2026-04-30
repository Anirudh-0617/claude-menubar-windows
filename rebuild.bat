@echo off
:: Rebuild and reinstall Claude Counter after code changes.

echo.
echo  Claude Counter -- Rebuilding
echo  ==============================
echo.

:: Kill running instance
taskkill /IM "Claude Counter.exe" /F >nul 2>&1
echo [1/3] Stopped running instance.

:: Delete key cache
set CACHE=%USERPROFILE%\.claude_counter_key.bin
if exist "%CACHE%" (
    del "%CACHE%"
    echo        Deleted key cache.
)

:: Rebuild with onedir (avoids DLL ordinal errors)
echo [2/3] Building...
if exist dist  rmdir /s /q dist
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
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

:: Reinstall
echo [3/3] Installing...
set INSTALL_DIR=%LOCALAPPDATA%\ClaudeCounter
if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"
xcopy /e /i /q "dist\Claude Counter" "%INSTALL_DIR%"

set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
copy /Y "%INSTALL_DIR%\Claude Counter.exe" "%STARTUP%\Claude Counter.exe" >nul

echo.
echo  [OK] Done! Launching...
start "" "%INSTALL_DIR%\Claude Counter.exe"
