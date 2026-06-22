@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0\..\.."

set "PIPELINE_DIR=%CD%\scripts\Pipeline"
set "WORKER=%PIPELINE_DIR%\run_props_parallel_worker.bat"
set "RUN_DIR=%TEMP%\BeatTheBooks_props_%RANDOM%_%RANDOM%"
set "TOTAL=6"
set "LAST_DONE=-1"

set "PART_1=Paddy Power + 888Sport"
set "PART_2=LiveScoreBet + Midnite"
set "PART_3=Unibet + Ladbrokes"
set "PART_4=BoyleSports"
set "PART_5=BetVictor"
set "PART_6=William Hill"

if not exist "%WORKER%" (
    echo ERROR: Missing parallel worker:
    echo %WORKER%
    exit /b 1
)

mkdir "%RUN_DIR%" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Could not create temporary run folder:
    echo %RUN_DIR%
    exit /b 1
)

echo ==================================================
echo RUNNING ALL SIX WORLD CUP PROPS PARTS IN PARALLEL
echo Started: %date% %time%
echo ==================================================
echo.
echo Each bookmaker part runs at the same time.
echo Scripts and merges inside each part remain sequential.
echo Logs: %RUN_DIR%
echo.

call :launch 1 "run_props_01_paddypower_888sport.bat"
call :launch 2 "run_props_02_livescorebet_midnite.bat"
call :launch 3 "run_props_03_unibet_ladbrokes.bat"
call :launch 4 "run_props_04_boylesports.bat"
call :launch 5 "run_props_05_betvictor.bat"
call :launch 6 "run_props_06_williamhill.bat"

echo.
echo All six parts launched. Waiting for completion...

:wait_loop
set /a DONE=0

for /L %%N in (1,1,%TOTAL%) do (
    if exist "%RUN_DIR%\part_%%N.status" set /a DONE+=1
)

if not "!DONE!"=="!LAST_DONE!" (
    echo Completed: !DONE!/%TOTAL%
    set "LAST_DONE=!DONE!"
)

if !DONE! LSS %TOTAL% (
    timeout /t 2 /nobreak >nul
    goto wait_loop
)

echo.
echo ==================================================
echo PARALLEL PROPS RESULTS
echo ==================================================

set "FAILED=0"

for /L %%N in (1,1,%TOTAL%) do (
    set "RC="
    set /p "RC="<"%RUN_DIR%\part_%%N.status"

    if "!RC!"=="0" (
        echo [OK] Part %%N - !PART_%%N!
    ) else (
        echo [FAILED !RC!] Part %%N - !PART_%%N!
        set "FAILED=1"
        echo.
        echo Last 40 log lines for Part %%N:
        powershell -NoProfile -Command "Get-Content -LiteralPath '%RUN_DIR%\part_%%N.log' -Tail 40"
        echo.
    )
)

if "%FAILED%"=="1" (
    echo One or more props parts failed.
    echo Full logs remain in:
    echo %RUN_DIR%
    exit /b 1
)

echo.
echo ALL SIX PARALLEL PROPS PARTS COMPLETED: %date% %time%
echo Logs: %RUN_DIR%
exit /b 0


:launch
set "PART_NUMBER=%~1"
set "PART_FILE=%~2"
set "PART_SCRIPT=%PIPELINE_DIR%\%PART_FILE%"
set "LOG_FILE=%RUN_DIR%\part_%PART_NUMBER%.log"
set "STATUS_FILE=%RUN_DIR%\part_%PART_NUMBER%.status"

if not exist "%PART_SCRIPT%" (
    echo ERROR: Missing Part %PART_NUMBER% script:
    echo %PART_SCRIPT%
    >"%LOG_FILE%" echo ERROR: Missing script: %PART_SCRIPT%
    >"%STATUS_FILE%" echo 9009
    exit /b 0
)

echo Launching Part %PART_NUMBER% - !PART_%PART_NUMBER%!
start "" /b cmd.exe /d /c ""%WORKER%" "%PART_SCRIPT%" "%LOG_FILE%" "%STATUS_FILE%""
exit /b 0
