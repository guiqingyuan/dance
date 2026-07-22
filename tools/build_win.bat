@echo off
:: ============================================================
::  A1Z Choreo Builder  -  Windows Package Script
::  Double-click this file to build A1Z.exe
:: ============================================================

:: Keep window open on ANY exit (including errors)
if "%PAUSE_ON_EXIT%"=="" (
    set PAUSE_ON_EXIT=1
    cmd /k "%~f0"
    exit /b
)

cd /d "%~dp0"
set LOG=%~dp0build_log.txt
echo. > "%LOG%"

echo ============================================================ | tee "%LOG%"
echo   A1Z Choreo Builder                                         | tee -a "%LOG%"
echo ============================================================ | tee -a "%LOG%"
echo.

:: ── Step 1: Check Python ─────────────────────────────────────
echo [1/4] Checking Python... | tee -a "%LOG%"
where python >> "%LOG%" 2>&1
python --version >> "%LOG%" 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Python not found in PATH.
    echo         Please install Python 3.10+ from https://python.org
    echo         Make sure to check "Add Python to PATH" during install.
    echo.
    echo Log saved to: %LOG%
    pause
    exit /b 1
)
python --version
echo [1/4] Python OK

:: ── Step 2: Install dependencies ─────────────────────────────
echo.
echo [2/4] Installing dependencies (may take a few minutes)...
pip install --upgrade pyinstaller fastapi "uvicorn[standard]" pillow mujoco numpy h11 websockets anyio >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] pip install failed. See build_log.txt for details.
    echo.
    type "%LOG%"
    pause
    exit /b 1
)
echo [2/4] Dependencies OK

:: ── Step 2.5: Render self-test ───────────────────────────────
echo.
echo [2.5/4] OpenGL render self-test...
python -c "import mujoco; m=mujoco.MjModel.from_xml_string('<mujoco><worldbody/></mujoco>'); r=mujoco.Renderer(m,64,64); r.update_scene(mujoco.MjData(m)); print('Render OK shape='+str(r.render().shape))" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [WARNING] OpenGL self-test failed - 3D view will show placeholder image.
    echo           Choreography editing still works. Continuing...
    echo.
) else (
    echo [2.5/4] Render OK
)

:: ── Step 3: PyInstaller ───────────────────────────────────────
echo.
echo [3/4] Building exe (first time takes 2-5 minutes)...
pyinstaller --clean --noconfirm choreo_server.spec >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller failed. See build_log.txt for details.
    echo.
    type "%LOG%"
    pause
    exit /b 1
)
echo [3/4] Build OK

:: ── Step 4: Finalize ─────────────────────────────────────────
echo.
echo [4/4] Finalizing...
if not exist "dist\A1Z\choreographies" mkdir "dist\A1Z\choreographies"

echo.
echo ============================================================
echo   SUCCESS!
echo   Output : tools\dist\A1Z\
echo   Run    : double-click A1Z.exe inside that folder
echo   Ship   : zip the entire dist\A1Z\ folder for users
echo ============================================================
echo.
echo Full log: %LOG%
pause
