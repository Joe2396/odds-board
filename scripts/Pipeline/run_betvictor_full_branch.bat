@echo off
setlocal EnableExtensions
cd /d "%~dp0\..\.."

set "DONE_FILE=%~1"
set "RC=0"

chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

echo ==========================================
echo BetVictor full moneyline and props branch
echo ==========================================
echo.

echo [BetVictor 1/8] Moneylines...
python scripts\Football\fetch_betvictor_worldcup_moneylines.py
if errorlevel 1 goto FAILED

echo.
echo [BetVictor 2/8] Main props...
python scripts\Football\fetch_betvictor_worldcup_props.py
if errorlevel 1 goto FAILED

echo.
echo [BetVictor 3/8] Exact player shots, SOT and fouls...
python scripts\Football\fetch_betvictor_player_stats_exact.py
if errorlevel 1 goto FAILED

echo.
echo [BetVictor 4/8] Merge exact player stats...
python scripts\Football\merge_betvictor_player_stats_exact.py
if errorlevel 1 goto FAILED

echo.
echo [BetVictor 5/8] Exact player tackles...
python scripts\Football\fetch_betvictor_player_tackles.py
if errorlevel 1 goto FAILED

echo.
echo [BetVictor 6/8] Merge exact player tackles...
python scripts\Football\merge_betvictor_player_tackles.py
if errorlevel 1 goto FAILED

echo.
echo [BetVictor 7/8] Bet Builder match and team statistics...
python scripts\Football\fetch_betvictor_betbuilder_match_stats.py
if errorlevel 1 goto FAILED

echo.
echo [BetVictor 8/8] Merge Bet Builder statistics...
python scripts\Football\merge_betvictor_betbuilder_stats.py
if errorlevel 1 goto FAILED

echo.
echo BetVictor full branch completed successfully.
> "%DONE_FILE%" echo 0
exit /b 0

:FAILED
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" set "RC=1"
echo.
echo BetVictor full branch failed with exit code %RC%.
> "%DONE_FILE%" echo %RC%
exit /b %RC%
