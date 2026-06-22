@echo off
setlocal
cd /d "%~dp0\..\.."

echo ==================================================
echo PROPS PART 4 OF 6 - BOYLESPORTS
echo Started: %date% %time%
echo ==================================================
echo.

echo [1/3] BoyleSports main props...
python scripts\Football\fetch_boylesports_worldcup_props.py
if errorlevel 1 (
    echo FAILED: BoyleSports main props.
    exit /b 1
)

echo.
echo [2/3] BoyleSports full stats props...
python scripts\Football\fetch_boylesports_stats_props.py
if errorlevel 1 (
    echo FAILED: BoyleSports stats props.
    exit /b 1
)

echo.
echo [3/3] Merging BoyleSports props and stats...
python scripts\Football\merge_boylesports_props.py
if errorlevel 1 (
    echo FAILED: BoyleSports props merge.
    exit /b 1
)

echo.
echo PROPS PART 4 COMPLETED: %date% %time%
exit /b 0
