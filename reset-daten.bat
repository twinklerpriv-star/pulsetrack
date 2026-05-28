@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  PulseTrack - Daten zuruecksetzen
echo  ================================
echo.
echo  Damit werden nur Analytics-Hits geloescht.
echo  Die Setup-Konfiguration bleibt erhalten.
echo.
choice /C JN /M "Fortfahren? [J]a / [N]ein"
if errorlevel 2 goto abort
if errorlevel 1 goto run

:run
py --version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Python-Launcher "py" wurde nicht gefunden.
    pause
    exit /b 1
)

py -c "import os, sqlite3; db='analytics.db'; print('DB:', os.path.abspath(db)); con=sqlite3.connect(db); con.execute('DELETE FROM hits;'); con.commit(); con.close(); print('OK: Analytics-Daten geloescht.')"
if errorlevel 1 (
    echo FEHLER beim Zuruecksetzen der Daten.
    pause
    exit /b 1
)

echo.
echo Fertig. Starte jetzt den Server neu mit start.bat.
echo.
choice /C JN /M "start.bat jetzt starten? [J]a / [N]ein"
if errorlevel 2 goto end
if errorlevel 1 call "%~dp0start.bat"
goto end

:abort
echo Abgebrochen.

:end
pause
