@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  PulseTrack - Tests
echo  ==================
echo.

py -m pytest tests/test_api.py -v
echo.
pause
