@echo off
cd /d C:\Users\joete\odds-board

echo. | python scripts\fetch_upcoming_events.py
echo. | python scripts\fetch_espn_event_fightcards.py
echo. | python scripts\fetch_recent_past_events.py
echo. | python scripts\fetch_ufcstats_fighter_stats.py
echo. | python scripts\build_fighter_recent_fights.py
echo. | python scripts\fetch_betvictor_fight_urls.py
echo. | python scripts\fetch_coral_fight_urls.py
echo. | python scripts\fetch_paddypower_fight_urls.py
echo. | python scripts\fetch_888sport_props.py
echo. | python scripts\fetch_betfred_props.py
echo. | python scripts\fetch_betvictor_props.py
echo. | python scripts\fetch_boylesports_props.py
echo. | python scripts\fetch_boylesports_moneylines.py
echo. | python scripts\fetch_bwin_props.py
echo. | python scripts\fetch_coral_props.py
echo. | python scripts\fetch_livescorebet_ufc_moneylines.py
echo. | python scripts\fetch_tote_props.py
echo. | python scripts\fetch_ufc_props_paddypower.py
echo. | python scripts\fetch_unibet_props.py
echo. | python scripts\fetch_williamhill_props.py
echo. | python scripts\filter_betvictor_props.py
echo. | python scripts\filter_boylesports_props.py
echo. | python scripts\filter_coral_props.py
echo. | python scripts\filter_props.py
echo. | python scripts\generate_ufc_events.py
echo. | python scripts\generate_ufc_fighters.py
echo. | python scripts\generate_ufc_fights.py
echo. | python scripts\generate_ufc_hub.py
echo. | python scripts\generate_ufc_tracker.py
echo. | python scripts\generate_ev_alerts.py
echo. | python scripts\build_ev_alerts_all.py
echo. | python scripts\build_arbitrage_all.py

pause