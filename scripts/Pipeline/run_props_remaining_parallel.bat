@echo off
setlocal EnableExtensions
pushd "%~dp0\..\.."

chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

set "STATE_DIR=%TEMP%\BeatTheBooks_props_remaining_%RANDOM%_%RANDOM%"
mkdir "%STATE_DIR%" >nul 2>&1

echo ==================================================
echo RUNNING FOUR REMAINING WORLD CUP PROPS PARTS
echo Started: %DATE% %TIME%
echo ==================================================
echo.
echo BetVictor and BoyleSports are deliberately excluded.
echo Logs: %STATE_DIR%
echo.

call :LAUNCH 1 "Paddy Power + 888Sport" "scripts\Pipeline\run_props_01_paddypower_888sport.bat"
call :LAUNCH 2 "LiveScoreBet + Midnite" "scripts\Pipeline\run_props_02_livescorebet_midnite.bat"
call :LAUNCH 3 "Unibet + Ladbrokes" "scripts\Pipeline\run_props_03_unibet_ladbrokes.bat"
call :LAUNCH 6 "William Hill" "scripts\Pipeline\run_props_06_williamhill.bat"

echo All four parts launched. Waiting for completion.

:WAIT_LOOP
set "DONE_COUNT=0"
for %%N in (1 2 3 6) do (
    if exist "%STATE_DIR%\part_%%N.status" set /a DONE_COUNT+=1
)

echo Completed: %DONE_COUNT%/4
if not "%DONE_COUNT%"=="4" (
    timeout /t 3 /nobreak >nul
    goto WAIT_LOOP
)

echo.
echo ==================================================
echo REMAINING PARALLEL PROPS RESULTS
echo ==================================================

set "FAILED_COUNT=0"
call :REPORT 1 "Paddy Power + 888Sport"
call :REPORT 2 "LiveScoreBet + Midnite"
call :REPORT 3 "Unibet + Ladbrokes"
call :REPORT 6 "William Hill"

echo.
if not "%FAILED_COUNT%"=="0" (
    echo %FAILED_COUNT% remaining props parts failed.
    rmdir /s /q "%STATE_DIR%" >nul 2>&1
    popd
    exit /b 1
)

echo All four remaining props parts completed successfully.
rmdir /s /q "%STATE_DIR%" >nul 2>&1
popd
exit /b 0


:LAUNCH
set "PART_NO=%~1"
set "PART_NAME=%~2"
set "PART_SCRIPT=%~3"
set "LOG_FILE=%STATE_DIR%\part_%PART_NO%.log"
set "STATUS_FILE=%STATE_DIR%\part_%PART_NO%.status"

echo Launching Part %PART_NO% - %PART_NAME%
start "BTB Props %PART_NO%" /b cmd /d /c call "scripts\Pipeline\run_props_parallel_worker.bat" "%PART_SCRIPT%" "%LOG_FILE%" "%STATUS_FILE%"
exit /b 0


:REPORT
set "PART_NO=%~1"
set "PART_NAME=%~2"
set /p PART_RC=<"%STATE_DIR%\part_%PART_NO%.status"

if "%PART_RC%"=="0" (
    echo [OK] Part %PART_NO% - %PART_NAME%
) else (
    echo [FAILED %PART_RC%] Part %PART_NO% - %PART_NAME%
    echo.
    echo Last 50 log lines for Part %PART_NO%:
    powershell -NoProfile -Command "Get-Content -LiteralPath '%STATE_DIR%\part_%PART_NO%.log' -Tail 50"
    echo.
    set /a FAILED_COUNT+=1
)
exit /b 0
