@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Oeffne Dashboard (Server muss in start.bat laufen) ...
timeout /t 1 /nobreak >nul
start "" "http://127.0.0.1:8000/"
