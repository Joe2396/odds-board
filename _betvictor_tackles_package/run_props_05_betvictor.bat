@echo off
setlocal
cd /d C:\Users\joete\odds-board

echo ============================================================
echo BETVICTOR PROPS PART 5
echo Started: %date% %time%
echo ============================================================

echo.
echo [1/5] Main BetVictor props
python scripts\Football\fetch_betvictor_worldcup_props.py
if errorlevel 1 goto :fail

echo.
echo [2/5] Exact BetVictor player tackles
python scripts\Football\fetch_betvictor_player_tackles.py
if errorlevel 1 goto :fail

echo.
echo [3/5] Merge exact BetVictor player tackles
python scripts\Football\merge_betvictor_player_tackles.py
if errorlevel 1 goto :fail

echo.
echo [4/5] BetVictor Bet Builder match and team stats
python scripts\Football\fetch_betvictor_betbuilder_match_stats.py
if errorlevel 1 goto :fail

echo.
echo [5/5] Merge BetVictor Bet Builder match and team stats
python scripts\Football\merge_betvictor_betbuilder_stats.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo PROPS PART 5 COMPLETED: %date% %time%
echo ============================================================
exit /b 0

:fail
echo.
echo ============================================================
echo PROPS PART 5 FAILED: %date% %time%
echo ============================================================
exit /b 1
