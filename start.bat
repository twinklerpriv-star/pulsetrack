@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  PulseTrack - Server starten
echo  ===========================
echo.

py --version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: "py" nicht gefunden. Zuerst install.bat ausfuehren.
    pause
    exit /b 1
)

py -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo Pakete fehlen. Starte install.bat ...
    call "%~dp0install.bat"
)

echo Server laeuft auf http://127.0.0.1:8000
echo Einrichtung:  http://127.0.0.1:8000/setup
echo Dashboard:   http://127.0.0.1:8000/
echo.
echo Fenster offen lassen - zum Beenden Strg+C oder Fenster schliessen.
echo.

timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8000/setup"

py -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

pause
