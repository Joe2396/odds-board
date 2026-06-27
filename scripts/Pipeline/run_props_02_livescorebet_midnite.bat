@echo off
setlocal EnableExtensions
cd /d "%~dp0\..\.."

echo ==================================================
echo PROPS PART 2 OF 6 - LIVESCOREBET AND MIDNITE PROD15
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
echo [2/2] Midnite World Cup production props pipeline...
call scripts\Pipeline\run_midnite_worldcup_props_PROD15.bat SKIP_MONEYLINES
if errorlevel 1 (
    echo FAILED: Midnite PROD15 pipeline.
    exit /b 1
)

echo.
echo PROPS PART 2 COMPLETED: %date% %time%
exit /b 0
