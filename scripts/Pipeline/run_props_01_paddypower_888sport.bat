@echo off
setlocal
cd /d "%~dp0\..\.."

echo ==================================================
echo PROPS PART 1 OF 6 - PADDY POWER AND 888SPORT
echo Started: %date% %time%
echo ==================================================
echo.

echo [1/2] Paddy Power World Cup props...
python scripts\Football\fetch_paddypower_worldcup_props.py
if errorlevel 1 (
    echo FAILED: Paddy Power props.
    exit /b 1
)

echo.
echo [2/2] 888Sport World Cup props...
python scripts\Football\fetch_888sport_worldcup_props.py
if errorlevel 1 (
    echo FAILED: 888Sport props.
    exit /b 1
)

echo.
echo PROPS PART 1 COMPLETED: %date% %time%
exit /b 0
