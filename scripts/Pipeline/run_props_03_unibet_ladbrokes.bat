@echo off
setlocal EnableExtensions
pushd "%~dp0\..\.."

chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

echo ==================================================
echo PROPS PART 3 - UNIBET + LADBROKES CLEANED
echo Started: %DATE% %TIME%
echo ==================================================
echo.

echo [1/5] Unibet unified supported props...
python scripts\Football\fetch_unibet_worldcup_props_UNIFIED_PROD15_CLEAN.py
if errorlevel 1 (
    echo FAILED: Unibet unified props.
    goto FAIL
)

echo.
echo [2/5] Ladbrokes complete main props...
python scripts\Football\fetch_ladbrokes_worldcup_props.py
if errorlevel 1 (
    echo FAILED: Ladbrokes complete main props.
    goto FAIL
)

echo.
echo [3/5] Repair Ladbrokes goals and current goalscorers...
python scripts\Football\repair_ladbrokes_goals_goalscorer_PROD15_V2_LINEUP_AWARE.py
if errorlevel 1 (
    echo FAILED: Ladbrokes goals/goalscorer repair.
    goto FAIL
)

echo.
echo [4/5] Merge Ladbrokes aggregate shots and shots on target...
python scripts\Football\fetch_ladbrokes_shots_props.py
if errorlevel 1 (
    echo FAILED: Ladbrokes aggregate shots merge.
    goto FAIL
)

echo.
echo [5/5] Validate Ladbrokes aggregate Over/Under pairs...
python scripts\Football\validate_ladbrokes_aggregate_shots.py
if errorlevel 1 (
    echo FAILED: Ladbrokes aggregate shots validation.
    goto FAIL
)

echo.
echo ==================================================
echo PROPS PART 3 COMPLETED SUCCESSFULLY
echo Finished: %DATE% %TIME%
echo ==================================================

popd
endlocal
exit /b 0

:FAIL
echo.
echo ==================================================
echo PROPS PART 3 FAILED
echo Finished: %DATE% %TIME%
echo ==================================================

popd
endlocal
exit /b 1
