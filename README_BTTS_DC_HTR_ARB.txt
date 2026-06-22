BeatTheBooks football arbitrage expansion

Adds:
- Both Teams To Score
- Double Chance
- Half Time Result

Named-market bookmaker coverage:
- PaddyPower
- BoyleSports
- LiveScoreBet
- Ladbrokes
- WilliamHill
- BetVictor
- Unibet
- 888Sport

Midnite is not included in this patch because its saved JSON structure needs
a separate adapter.

Double Chance is calculated using the correct overlapping-outcome hedge:
0.5 * (1/d_1X + 1/d_X2 + 1/d_12).

Files:
- analyze_football_arbitrage_BTTS_DC_HTR.py
- patch_build_arbitrage_all_named_markets.py
