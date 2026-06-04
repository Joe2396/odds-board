@echo off
cd /d C:\Users\joete\odds-board

echo ================================
echo BeatTheBooks auto update started
echo ================================

echo.
echo Running football scrapers...
python scripts\Football\fetch_paddypower_worldcup_moneylines.py
python scripts\Football\fetch_boylesports_worldcup_moneylines.py
python scripts\Football\fetch_betvictor_worldcup_moneylines.py
python scripts\Football\fetch_unibet_worldcup_moneylines.py
python scripts\Football\fetch_livescorebet_worldcup_moneylines.py
python scripts\Football\fetch_williamhill_worldcup_moneylines.py
python scripts\Football\fetch_888sport_worldcup_moneylines.py

echo.
echo Building football pages/tools...
python scripts\Football\generate_worldcup_page.py
python scripts\Football\analyze_football_arbitrage.py
python scripts\Football\build_football_ev_alerts.py

echo.
echo Building combined pages...
python scripts\build_ev_alerts_all.py
python scripts\build_arbitrage_all.py

echo.
echo Committing and pushing updates...
git add football data ev-alerts arbitrage run_big_auto_update.bat

git commit -m "Auto update World Cup odds EV alerts and arbitrage" || echo No changes to commit

git pull --rebase origin main

git push origin main

echo.
echo ================================
echo BeatTheBooks auto update finished
echo ================================