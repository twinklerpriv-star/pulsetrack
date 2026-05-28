@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  PulseTrack - Schnellstart
echo  =========================
echo.
echo  1. Einmalig:  install.bat
echo  2. Danach:    start.bat  (oeffnet Setup im Browser)
echo  3. Optional:  reset-daten.bat (alte Testdaten loeschen)
echo.
echo  Website tracken (z.B. elektropepi.at):
echo    - In Setup URL eingeben: https://www.elektropepi.at
echo    - Snippet kopieren und ins Website-Layout einfuegen
echo.
choice /C 123 /M "Was moechten Sie tun? [1] Installieren  [2] Server starten  [3] Daten zuruecksetzen"
if errorlevel 3 goto reset
if errorlevel 2 goto start
if errorlevel 1 goto install

:install
call "%~dp0install.bat"
goto end

:start
call "%~dp0start.bat"
goto end

:reset
call "%~dp0reset-daten.bat"
goto end

:end
