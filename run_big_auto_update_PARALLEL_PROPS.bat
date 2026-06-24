@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==========================================
echo BeatTheBooks fast parallel update started
echo ==========================================
echo.

echo Checking Git working tree...
for /f "delims=" %%G in ('git status --porcelain') do (
    echo Working tree is not clean. Stopping before pull or scraping.
    echo Commit, stash, or discard the existing changes first.
    exit /b 1
)

echo Pulling latest GitHub version first...
git pull --rebase origin main
if errorlevel 1 (
    echo Git pull failed. Stopping update.
    exit /b 1
)

set "RUN_STATE=%TEMP%\beatthebooks_%RANDOM%_%RANDOM%"
mkdir "%RUN_STATE%" >nul 2>&1

set "BWIN_DONE=%RUN_STATE%\bwin.done"
set "BWIN_LOG=%RUN_STATE%\bwin.log"
set "BETVICTOR_DONE=%RUN_STATE%\betvictor.done"
set "BETVICTOR_LOG=%RUN_STATE%\betvictor.log"

echo.
echo Starting long-running bookmaker branches early...
echo   - Bwin moneylines, props and match stats
echo   - BetVictor moneylines

start "BTB Bwin" /b cmd /d /c call "scripts\Pipeline\run_bwin_fast_branch.bat" "%BWIN_DONE%" ^> "%BWIN_LOG%" 2^>^&1
start "BTB BetVictor Moneylines" /b cmd /d /c call "scripts\Pipeline\run_betvictor_moneyline_branch.bat" "%BETVICTOR_DONE%" ^> "%BETVICTOR_LOG%" 2^>^&1

echo.
echo Running remaining football moneyline scrapers...

python scripts\Football\fetch_paddypower_worldcup_moneylines.py
if errorlevel 1 exit /b 1

python scripts\Football\fetch_boylesports_worldcup_moneylines.py
if errorlevel 1 exit /b 1

python scripts\Football\fetch_unibet_worldcup_moneylines.py
if errorlevel 1 exit /b 1

python scripts\Football\fetch_livescorebet_worldcup_moneylines.py
if errorlevel 1 exit /b 1

python scripts\Football\fetch_williamhill_worldcup_moneylines.py
if errorlevel 1 exit /b 1

python scripts\Football\fetch_888sport_worldcup_moneylines.py
if errorlevel 1 exit /b 1

python scripts\Football\fetch_ladbrokes_worldcup_moneylines.py
if errorlevel 1 exit /b 1

python scripts\Football\fetch_midnite_worldcup_moneylines.py
if errorlevel 1 exit /b 1

echo.
echo Waiting for BetVictor moneylines before props pipeline...
call :WAIT_FOR_FILE "%BETVICTOR_DONE%"

type "%BETVICTOR_LOG%"
set /p BETVICTOR_RC=<"%BETVICTOR_DONE%"

if not "%BETVICTOR_RC%"=="0" (
    echo BetVictor moneylines failed. Stopping before props pipeline.
    call :CLEANUP
    exit /b 1
)

echo.
echo Running split World Cup props pipeline in parallel...
call scripts\Pipeline\run_props_all_parts_parallel.bat
if errorlevel 1 (
    echo Props pipeline failed. Stopping before validation and build.
    call :CLEANUP
    exit /b 1
)

echo.
echo Waiting for Bwin branch to finish...
call :WAIT_FOR_FILE "%BWIN_DONE%"
type "%BWIN_LOG%"

echo.
echo Validating World Cup moneyline data...
python validate_worldcup_moneylines.py
if errorlevel 1 (
    echo Validation failed. No pages generated, committed, or pushed.
    call :CLEANUP
    exit /b 1
)

echo.
echo Building football pages...
python scripts\Football\generate_worldcup_page.py
if errorlevel 1 (
    echo World Cup page generation failed.
    call :CLEANUP
    exit /b 1
)

echo.
echo Checking generated player folders...
for /f %%C in ('powershell -NoProfile -Command "$bad = Get-ChildItem 'football\world-cup' -Directory -Recurse ^| Where-Object { $_.FullName -match '\\player-props\\players\\' -and $_.Name -match '(^u-[0-9]|-(over|under)-[0-9]|corners|win-or-draw|win-either-half|yes-and-|no-and-)' }; @($bad).Count"') do set BAD_PLAYER_DIRS=%%C

if not "%BAD_PLAYER_DIRS%"=="0" (
    echo Found %BAD_PLAYER_DIRS% malformed generated player folders.
    echo Stopping before EV, arbitrage, commit, and push.
    powershell -NoProfile -Command "$bad = Get-ChildItem 'football\world-cup' -Directory -Recurse | Where-Object { $_.FullName -match '\\player-props\\players\\' -and $_.Name -match '(^u-[0-9]|-(over|under)-[0-9]|corners|win-or-draw|win-either-half|yes-and-|no-and-)' }; $bad.FullName"
    call :CLEANUP
    exit /b 1
)

echo.
echo Building football arbitrage...
python scripts\Football\analyze_football_arbitrage.py
if errorlevel 1 (
    call :CLEANUP
    exit /b 1
)

echo.
echo Building football EV alerts...
python scripts\Football\build_football_ev_alerts.py
if errorlevel 1 (
    call :CLEANUP
    exit /b 1
)

echo.
echo Building combined EV alerts...
python scripts\build_ev_alerts_all.py
if errorlevel 1 (
    call :CLEANUP
    exit /b 1
)

echo.
echo Building combined arbitrage...
python scripts\build_arbitrage_all.py
if errorlevel 1 (
    call :CLEANUP
    exit /b 1
)

echo.
echo Staging approved generated data and pages...
git add football data ev-alerts arbitrage

git diff --cached --quiet
if not errorlevel 1 (
    echo No generated changes to commit.
) else (
    git commit -m "Auto update World Cup odds, props, EV alerts and arbitrage"
    if errorlevel 1 (
        echo Git commit failed.
        call :CLEANUP
        exit /b 1
    )
)

echo.
echo Checking GitHub again before push...
git pull --rebase origin main
if errorlevel 1 (
    echo Final Git pull/rebase failed. Nothing was pushed.
    call :CLEANUP
    exit /b 1
)

git push origin main
if errorlevel 1 (
    echo Git push failed.
    call :CLEANUP
    exit /b 1
)

call :CLEANUP

echo.
echo ==========================================
echo BeatTheBooks fast parallel update finished
echo ==========================================
exit /b 0


:WAIT_FOR_FILE
if exist "%~1" exit /b 0
timeout /t 2 /nobreak >nul
goto WAIT_FOR_FILE


:CLEANUP
if defined RUN_STATE (
    if exist "%RUN_STATE%" rmdir /s /q "%RUN_STATE%" >nul 2>&1
)
exit /b 0
