@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  PulseTrack - Abhaengigkeiten installieren
echo  ==========================================
echo.

py --version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Python-Launcher "py" wurde nicht gefunden.
    echo Bitte Python von https://www.python.org/downloads/ installieren
    echo und "Add Python to PATH" aktivieren.
    pause
    exit /b 1
)

echo Installiere Pakete ...
py -m pip install --upgrade pip
py -m pip install fastapi uvicorn jinja2 pydantic python-multipart httpx pytest

if errorlevel 1 (
    echo.
    echo FEHLER bei der Installation.
    pause
    exit /b 1
)

echo.
echo Installation abgeschlossen.
echo Als Naechstes: start.bat doppelklicken.
echo.
pause
