@echo off
title Nexus v5 - Full Dependency Installer
color 0b

echo ====================================================
echo   NEXUS v5 - FULL SYSTEM INSTALLER
echo ====================================================
echo.

:: --- 1. PYTHON CHECK & DEPS ---
echo [STEP 1/2] Checking Python Environment...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0c
    echo [ERROR] Python not found. Please install Python and check "Add to PATH".
    pause
    exit /b
)

echo [+] Installing Python libraries (LCU-Driver, Psutil)...
python -m pip install --upgrade pip --user
python -m pip install lcu-driver psutil --user
echo.

:: --- 2. NODE.JS CHECK & DEPS ---
echo [STEP 2/2] Checking Node.js Environment...
node -v >nul 2>&1
if %errorlevel% neq 0 (
    color 0e
    echo [WARNING] Node.js not found. 
    echo If you are only running the LCU script, this is fine.
    echo If you want to run the Dashboard, please install Node.js.
) else (
    echo [+] Installing Node.js packages (Express, etc.)...
    :: This runs 'npm install' which looks at your package.json
    call npm install
)

echo.
echo ====================================================
echo   DONE! All dependencies should be ready.
echo   1. Run 'start.bat' to launch the dashboard.
echo   2. Make sure League is open for syncing.
echo ====================================================
echo.
pause