@echo off
setlocal

pushd "%~dp0\..\.."

echo ============================================================
echo BETVICTOR WORLD CUP PROPS
echo ============================================================

echo.
echo [1/7] Main BetVictor props
python scripts\Football\fetch_betvictor_worldcup_props.py
if errorlevel 1 exit /b 1

echo.
echo [2/7] Exact player shots, SOT and fouls
python scripts\Football\fetch_betvictor_player_stats_exact.py
if errorlevel 1 exit /b 1

echo.
echo [3/7] Merge exact player shots, SOT and fouls
python scripts\Football\merge_betvictor_player_stats_exact.py
if errorlevel 1 exit /b 1

echo.
echo [4/7] Exact player tackles
python scripts\Football\fetch_betvictor_player_tackles.py
if errorlevel 1 exit /b 1

echo.
echo [5/7] Merge exact player tackles
python scripts\Football\merge_betvictor_player_tackles.py
if errorlevel 1 exit /b 1

echo.
echo [6/7] Bet Builder match and team statistics
python scripts\Football\fetch_betvictor_betbuilder_match_stats.py
if errorlevel 1 exit /b 1

echo.
echo [7/7] Merge Bet Builder match and team statistics
python scripts\Football\merge_betvictor_betbuilder_stats.py
if errorlevel 1 exit /b 1

echo.
echo BetVictor props completed successfully.

popd
endlocal
exit /b 0
