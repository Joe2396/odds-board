@echo off
setlocal EnableExtensions DisableDelayedExpansion

cd /d "%~dp0\..\.."
set "PYTHONUTF8=1"

set "SKIP_MONEYLINES="
if /I "%~1"=="SKIP_MONEYLINES" set "SKIP_MONEYLINES=1"

set "RUN_STATE=%TEMP%\midnite_prod15_%RANDOM%_%RANDOM%"
mkdir "%RUN_STATE%" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Could not create temporary run directory:
    echo %RUN_STATE%
    exit /b 1
)

set "MAIN_DONE=%RUN_STATE%\main.done"
set "MAIN_LOG=%RUN_STATE%\main.log"
set "MAIN_WORKER=%RUN_STATE%\main_worker.bat"

set "STATS_DONE=%RUN_STATE%\stats.done"
set "STATS_LOG=%RUN_STATE%\stats.log"
set "STATS_WORKER=%RUN_STATE%\stats_worker.bat"

echo.
echo ============================================================
echo MIDNITE WORLD CUP PROD15 FAST PIPELINE V2
echo ============================================================
echo.

if defined SKIP_MONEYLINES (
    echo [1/5] Midnite moneylines already refreshed by master - skipping.
) else (
    echo [1/5] Refreshing Midnite World Cup moneylines...
    python scripts\Football\fetch_midnite_worldcup_moneylines.py
    if errorlevel 1 goto :failed
)

echo.
echo [2/5] Selecting one shared set of 15 upcoming fixtures...
python scripts\Football\prepare_midnite_worldcup_props_fixtures.py
if errorlevel 1 goto :failed

rem Create separate worker files so ERRORLEVEL is evaluated inside each
rem child process after its Python command finishes.
> "%MAIN_WORKER%" (
    echo @echo off
    echo cd /d "%CD%"
    echo set "PYTHONUTF8=1"
    echo python scripts\Football\fetch_midnite_worldcup_props_PROD15.py ^> "%MAIN_LOG%" 2^>^&1
    echo ^> "%MAIN_DONE%" echo %%errorlevel%%
)

> "%STATS_WORKER%" (
    echo @echo off
    echo cd /d "%CD%"
    echo set "PYTHONUTF8=1"
    echo python scripts\Football\fetch_midnite_worldcup_team_stats_PROD15.py ^> "%STATS_LOG%" 2^>^&1
    echo ^> "%STATS_DONE%" echo %%errorlevel%%
)

echo.
echo [3/5] Starting both Midnite props scrapers in parallel...
echo   - Main and player props
echo   - Match/Home/Away Shots and Shots on Target

start "Midnite Main Props" /b cmd /d /c call "%MAIN_WORKER%"
start "Midnite Team Stats" /b cmd /d /c call "%STATS_WORKER%"

call :WAIT_FOR_FILE "%MAIN_DONE%"
call :WAIT_FOR_FILE "%STATS_DONE%"

echo.
echo ---------------- MAIN / PLAYER PROPS LOG ----------------
if exist "%MAIN_LOG%" (
    type "%MAIN_LOG%"
) else (
    echo ERROR: Main/player log was not created.
)
echo.
echo ---------------- TEAM SHOTS / SOT LOG -------------------
if exist "%STATS_LOG%" (
    type "%STATS_LOG%"
) else (
    echo ERROR: Team Shots/SOT log was not created.
)
echo ---------------------------------------------------------

set "MAIN_RC="
set "STATS_RC="
set /p MAIN_RC=<"%MAIN_DONE%"
set /p STATS_RC=<"%STATS_DONE%"

echo Main/player exit code: %MAIN_RC%
echo Team Shots/SOT exit code: %STATS_RC%

if not "%MAIN_RC%"=="0" (
    echo Main/player props scraper failed.
    goto :failed
)

if not "%STATS_RC%"=="0" (
    echo Team Shots/SOT scraper failed.
    goto :failed
)

echo.
echo [4/5] Validating, backing up and merging production JSON...
python scripts\Football\merge_midnite_worldcup_props_PROD15.py
if errorlevel 1 goto :failed

echo.
echo [5/5] Running independent final validation...
python scripts\Football\validate_midnite_worldcup_props_PROD15.py
if errorlevel 1 goto :failed

call :cleanup

echo.
echo ============================================================
echo MIDNITE PROD15 FAST V2 COMPLETE - PASS
echo ============================================================
exit /b 0


:WAIT_FOR_FILE
if exist "%~1" exit /b 0
timeout /t 2 /nobreak >nul
goto :WAIT_FOR_FILE


:failed
echo.
echo ============================================================
echo MIDNITE PROD15 FAST V2 FAILED
echo Existing production JSON was preserved unless merge passed.
echo ============================================================
call :cleanup
exit /b 1


:cleanup
if defined RUN_STATE (
    if exist "%RUN_STATE%" (
        rmdir /s /q "%RUN_STATE%" >nul 2>&1
    )
)
exit /b 0
