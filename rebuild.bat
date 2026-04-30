@echo off
:: Rebuild and reinstall Claude Counter after code changes.

echo.
echo  Claude Counter -- Rebuilding
echo  ==============================
echo.

:: Kill running instance
taskkill /IM "Claude Counter.exe" /F >nul 2>&1
echo [1/3] Stopped running instance.

:: Delete key cache so fresh key is fetched
set CACHE=%USERPROFILE%\.claude_counter_key.bin
if exist "%CACHE%" (
    del "%CACHE%"
    echo [1/3] Deleted key cache.
)

:: Rebuild
echo [2/3] Building...
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build
if exist "Claude Counter.spec" del "Claude Counter.spec"

venv\Scripts\pyinstaller --onefile --windowed --name "Claude Counter" --icon=icon.ico claude_counter_win.py 2>nul
if not exist "dist\Claude Counter.exe" (
    venv\Scripts\pyinstaller --onefile --windowed --name "Claude Counter" claude_counter_win.py
)

:: Copy to Startup
set DEST=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
copy /Y "dist\Claude Counter.exe" "%DEST%\Claude Counter.exe" >nul
echo [3/3] Installed to Startup folder.

echo.
echo  [OK] Done! Launching...
start "" "dist\Claude Counter.exe"
