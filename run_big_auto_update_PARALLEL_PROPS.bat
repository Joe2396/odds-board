@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==================================================
echo BeatTheBooks balanced fast parallel update started
echo ==================================================
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

set "RUN_STATE=%TEMP%\beatthebooks_fast_v2_%RANDOM%_%RANDOM%"
mkdir "%RUN_STATE%" >nul 2>&1

set "BWIN_DONE=%RUN_STATE%\bwin.done"
set "BWIN_LOG=%RUN_STATE%\bwin.log"
set "BETVICTOR_DONE=%RUN_STATE%\betvictor.done"
set "BETVICTOR_LOG=%RUN_STATE%\betvictor.log"

echo.
echo Starting the two longest bookmaker branches immediately...
echo   - Bwin moneylines, ordinary props and match stats
echo   - BetVictor moneylines and all seven props/stat steps

start "BTB Bwin Full Branch" /b cmd /d /c call "scripts\Pipeline\run_bwin_fast_branch.bat" "%BWIN_DONE%" ^> "%BWIN_LOG%" 2^>^&1
start "BTB BetVictor Full Branch" /b cmd /d /c call "scripts\Pipeline\run_betvictor_full_branch.bat" "%BETVICTOR_DONE%" ^> "%BETVICTOR_LOG%" 2^>^&1

echo.
echo Running remaining football moneyline scrapers...

python scripts\Football\fetch_paddypower_worldcup_moneylines.py
if errorlevel 1 goto FAIL

python scripts\Football\fetch_boylesports_worldcup_moneylines.py
if errorlevel 1 goto FAIL

python scripts\Football\fetch_unibet_worldcup_moneylines.py
if errorlevel 1 goto FAIL

python scripts\Football\fetch_livescorebet_worldcup_moneylines.py
if errorlevel 1 goto FAIL

python scripts\Football\fetch_williamhill_worldcup_moneylines.py
if errorlevel 1 goto FAIL

python scripts\Football\fetch_888sport_worldcup_moneylines.py
if errorlevel 1 goto FAIL

python scripts\Football\fetch_ladbrokes_worldcup_moneylines.py
if errorlevel 1 goto FAIL

python scripts\Football\fetch_midnite_worldcup_moneylines.py
if errorlevel 1 goto FAIL

echo.
echo Running lightweight BoyleSports props while long branches continue...
call scripts\Pipeline\run_props_04_boylesports.bat
if errorlevel 1 (
    echo BoyleSports props failed.
    goto FAIL
)

echo.
echo Waiting for Bwin full branch...
call :WAIT_FOR_FILE "%BWIN_DONE%"
type "%BWIN_LOG%"
set /p BWIN_RC=<"%BWIN_DONE%"
if not "%BWIN_RC%"=="0" (
    echo Bwin branch reported a fatal failure.
    goto FAIL
)

echo.
echo Waiting for BetVictor full branch...
call :WAIT_FOR_FILE "%BETVICTOR_DONE%"
type "%BETVICTOR_LOG%"
set /p BETVICTOR_RC=<"%BETVICTOR_DONE%"
if not "%BETVICTOR_RC%"=="0" (
    echo BetVictor full branch failed.
    goto FAIL
)

echo.
echo Running the four remaining props parts in parallel...
call scripts\Pipeline\run_props_remaining_parallel.bat
if errorlevel 1 (
    echo Remaining props pipeline failed.
    goto FAIL
)

echo.
echo Validating World Cup moneyline data...
python validate_worldcup_moneylines.py
if errorlevel 1 (
    echo Validation failed. No pages generated, committed, or pushed.
    goto FAIL
)

echo.
echo Building football pages...
python scripts\Football\generate_worldcup_page.py
if errorlevel 1 (
    echo World Cup page generation failed.
    goto FAIL
)

echo.
echo Checking generated player folders...
for /f %%C in ('powershell -NoProfile -Command "$bad = Get-ChildItem 'football\world-cup' -Directory -Recurse ^| Where-Object { $_.FullName -match '\\player-props\\players\\' -and $_.Name -match '(^u-[0-9]|-(over|under)-[0-9]|corners|win-or-draw|win-either-half|yes-and-|no-and-)' }; @($bad).Count"') do set BAD_PLAYER_DIRS=%%C

if not "%BAD_PLAYER_DIRS%"=="0" (
    echo Found %BAD_PLAYER_DIRS% malformed generated player folders.
    powershell -NoProfile -Command "$bad = Get-ChildItem 'football\world-cup' -Directory -Recurse | Where-Object { $_.FullName -match '\\player-props\\players\\' -and $_.Name -match '(^u-[0-9]|-(over|under)-[0-9]|corners|win-or-draw|win-either-half|yes-and-|no-and-)' }; $bad.FullName"
    goto FAIL
)

echo.
echo Building football arbitrage...
python scripts\Football\analyze_football_arbitrage.py
if errorlevel 1 goto FAIL

echo.
echo Building football EV alerts...
python scripts\Football\build_football_ev_alerts.py
if errorlevel 1 goto FAIL
echo. 
echo Removing expired football EV alerts...
python scripts\Football\filter_expired_football_ev_alerts.py
if errorlevel 1 goto FAIL

echo.
echo Building combined EV alerts...
python scripts\build_ev_alerts_all.py
if errorlevel 1 goto FAIL

echo.
echo Building combined arbitrage...
python scripts\build_arbitrage_all.py
if errorlevel 1 goto FAIL

echo.
echo Staging approved generated data and pages...
git add football data ev-alerts arbitrage

git diff --cached --quiet
if not errorlevel 1 (
    echo No generated changes to commit.
) else (
    git commit -m "Auto update World Cup odds, props, EV alerts and arbitrage"
    if errorlevel 1 goto FAIL
)

echo.
echo Checking GitHub again before push...
git pull --rebase origin main
if errorlevel 1 (
    echo Final Git pull/rebase failed. Nothing was pushed.
    goto FAIL
)

git push origin main
if errorlevel 1 goto FAIL

call :CLEANUP

echo.
echo ==================================================
echo BeatTheBooks balanced fast parallel update finished
echo ==================================================
exit /b 0


:WAIT_FOR_FILE
if exist "%~1" exit /b 0
timeout /t 2 /nobreak >nul
goto WAIT_FOR_FILE


:FAIL
echo.
echo Update failed. Generated working files were not pushed.
call :CLEANUP
exit /b 1


:CLEANUP
if defined RUN_STATE (
    if exist "%RUN_STATE%" rmdir /s /q "%RUN_STATE%" >nul 2>&1
)
exit /b 0
