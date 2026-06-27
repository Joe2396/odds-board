@echo off
cd /d C:\Users\joete\odds-board
echo ================================
echo BeatTheBooks auto update started
echo ================================
echo.
echo Pulling latest GitHub version first...
git pull --rebase --autostash origin main
IF ERRORLEVEL 1 (
    echo Git pull failed. Stopping update.
    exit /b 1
)
echo.
echo Running football moneyline scrapers...
python scripts\Football\fetch_paddypower_worldcup_moneylines.py
python scripts\Football\fetch_boylesports_worldcup_moneylines.py
python scripts\Football\fetch_betvictor_worldcup_moneylines.py
python scripts\Football\fetch_unibet_worldcup_moneylines.py
python scripts\Football\fetch_livescorebet_worldcup_moneylines.py
python scripts\Football\fetch_williamhill_worldcup_moneylines.py
python scripts\Football\fetch_888sport_worldcup_moneylines.py
python scripts\Football\fetch_ladbrokes_worldcup_moneylines.py
python scripts\Football\fetch_midnite_worldcup_moneylines.py
echo.
echo Running football props scrapers...
python scripts\Football\fetch_paddypower_worldcup_props.py
python scripts\Football\fetch_boylesports_worldcup_props.py
python scripts\Football\merge_boylesports_props.py
python scripts\Football\fetch_unibet_worldcup_props.py
echo.
echo Running corrected Unibet player shots/cards merge...
python scripts\Football\fetch_unibet_worldcup_shots_cards.py
IF ERRORLEVEL 1 (
    echo Unibet shots/cards scraper failed. Stopping before build.
    exit /b 1
)
python scripts\Football\merge_unibet_shots_cards.py
IF ERRORLEVEL 1 (
    echo Unibet shots/cards merge failed. Stopping before build.
    exit /b 1
)
python scripts\Football\fetch_livescorebet_worldcup_props.py
python scripts\Football\fetch_888sport_worldcup_props.py
python scripts\Football\fetch_williamhill_worldcup_props.py
python scripts\Football\fetch_betvictor_worldcup_props.py
python scripts\Football\fetch_ladbrokes_worldcup_props.py
python scripts\Football\fetch_ladbrokes_shots_props.py
call scripts\Pipeline\run_midnite_worldcup_props_PROD15.bat SKIP_MONEYLINES
IF ERRORLEVEL 1 (
    echo Midnite PROD15 pipeline failed. Stopping before build.
    exit /b 1
)
echo.
echo Validating World Cup moneyline data...
python validate_worldcup_moneylines.py
IF ERRORLEVEL 1 (
    echo Validation failed. Keeping previous good site version.
    echo No pages generated. No commit made. No push made.
    exit /b 1
)
echo.
echo Building football pages/tools...
python scripts\Football\generate_worldcup_page.py
python scripts\Football\analyze_football_arbitrage.py
python scripts\Football\build_football_ev_alerts.py
IF ERRORLEVEL 1 (
    echo Football build failed. Stopping before commit.
    exit /b 1
)
echo.
echo Building combined pages...
python scripts\build_ev_alerts_all.py
python scripts\build_arbitrage_all.py
IF ERRORLEVEL 1 (
    echo Combined build failed. Stopping before commit.
    exit /b 1
)
echo.
echo Committing and pushing updates...
git add football data ev-alerts arbitrage scripts run_big_auto_update.bat validate_worldcup_moneylines.py
git commit -m "Auto update World Cup odds, props, EV alerts and arbitrage" || echo No changes to commit
git push origin main
IF ERRORLEVEL 1 (
    echo Git push failed.
    exit /b 1
)
echo.
echo ================================
echo BeatTheBooks auto update finished
echo ================================