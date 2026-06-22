@echo off
setlocal
cd /d "%~dp0\..\.."

echo ==================================================
echo PROPS PART 2 OF 6 - LIVESCOREBET AND MIDNITE
echo Started: %date% %time%
echo ==================================================
echo.

echo [1/2] LiveScoreBet World Cup props...
python scripts\Football\fetch_livescorebet_worldcup_props.py
if errorlevel 1 (
    echo FAILED: LiveScoreBet props.
    exit /b 1
)

echo.
echo [2/2] Midnite World Cup props...
python scripts\Football\fetch_midnite_worldcup_props.py
if errorlevel 1 (
    echo FAILED: Midnite props.
    exit /b 1
)

echo.
echo PROPS PART 2 COMPLETED: %date% %time%
exit /b 0
