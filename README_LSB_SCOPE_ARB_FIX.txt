LiveScoreBet scope + football arbitrage safety fix

Files:
- scripts/Football/fetch_livescorebet_worldcup_props.py
- scripts/Football/analyze_football_arbitrage.py

What changed:
1. LiveScoreBet shots and shots-on-target tabs are clicked inside the correct market card.
2. Only the selected market card text is captured, instead of the whole page.
3. Shots markets fail closed if the selected scope cannot be verified.
4. Arbitrage uses canonical market identity:
   - combined match total
   - named team total
5. Player props are excluded from this match/team O/U arb scanner.
6. Historical LiveScoreBet team markets that exactly duplicate the combined market are skipped.

The scraper is intentionally set to MAX_MATCHES = 3 for testing.
After a successful test, change it to 15 for production.

Install from the repository root:
  copy /Y "%USERPROFILE%\Downloads\fetch_livescorebet_worldcup_props_SCOPE_FIX_TEST3.py" "scripts\Football\fetch_livescorebet_worldcup_props.py"
  copy /Y "%USERPROFILE%\Downloads\analyze_football_arbitrage_SCOPE_SAFETY_FIX.py" "scripts\Football\analyze_football_arbitrage.py"

Test:
  python scripts\Football\fetch_livescorebet_worldcup_props.py
  python scripts\Football\analyze_football_arbitrage.py
