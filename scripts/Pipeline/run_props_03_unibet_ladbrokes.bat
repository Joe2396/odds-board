@echo off
setlocal
cd /d "%~dp0\..\.."

echo ==================================================
echo PROPS PART 3 OF 6 - UNIBET AND LADBROKES
echo Started: %date% %time%
echo ==================================================
echo.

echo [1/5] Unibet main props...
python scripts\Football\fetch_unibet_worldcup_props.py
if errorlevel 1 (
    echo FAILED: Unibet main props.
    exit /b 1
)

echo.
echo [2/5] Unibet shots and cards...
python scripts\Football\fetch_unibet_worldcup_shots_cards.py
if errorlevel 1 (
    echo FAILED: Unibet shots/cards.
    exit /b 1
)

echo.
echo [3/5] Merging Unibet shots and cards...
python scripts\Football\merge_unibet_shots_cards.py
if errorlevel 1 (
    echo FAILED: Unibet shots/cards merge.
    exit /b 1
)

echo.
echo [4/5] Ladbrokes main props...
python scripts\Football\fetch_ladbrokes_worldcup_props.py
if errorlevel 1 (
    echo FAILED: Ladbrokes main props.
    exit /b 1
)

echo.
echo [5/5] Ladbrokes shots props...
python scripts\Football\fetch_ladbrokes_shots_props.py
if errorlevel 1 (
    echo FAILED: Ladbrokes shots props.
    exit /b 1
)

echo.
echo PROPS PART 3 COMPLETED: %date% %time%
exit /b 0
