@echo off
setlocal EnableExtensions
cd /d "%~dp0\..\.."

set "DONE_FILE=%~1"

echo ========================================
echo BetVictor moneyline branch started
echo ========================================
echo.

python scripts\Football\fetch_betvictor_worldcup_moneylines.py
set "RC=%ERRORLEVEL%"

echo.
echo ========================================
echo BetVictor moneyline branch finished
echo Exit code: %RC%
echo ========================================

> "%DONE_FILE%" echo %RC%
exit /b %RC%
