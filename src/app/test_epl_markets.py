import requests
import json

API_KEY = "8e8a4a2421e95ad2fb0df450c88ef6c6"   # your new key
SPORT = "soccer_epl"
REGIONS = "uk"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 20

# List of candidate markets to test
MARKET_CANDIDATES = [
    "h2h",             # Match Result
    "totals",          # Goals Over/Under
    "spreads",         # Handicap
    "btts",            # Both Teams to Score
    "double_chance",   # Double Chance
    "draw_no_bet",     # DNB
    "goals",           # Alt goals lines (sometimes)
    "cards",           # Cards markets (rare)
    "corners",         # Corners markets (rare)
    "player_goals",    # Scorer markets
]

def test_market(market_key: str):
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": market_key,
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": DATE_FORMAT
    }

    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"

    print(f"\n=== Testing market: {market_key} ===")

    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
    except Exception as e:
        print(f"REQUEST ERROR: {e}")
        return

    print(f"HTTP {r.status_code}")

    if r.status_code == 200:
        try:
            data = r.json()
            # If market exists, bookmakers should be populated
            total_markets = sum(len(g.get("bookmakers", [])) for g in data)
            print(f"Bookmakers returned: {total_markets}")
        except Exception as e:
            print(f"JSON ERROR: {e}")
    else:
        print(r.text[:250])

def main():
    print("=== EPL MARKET TEST ===")
    for mk in MARKET_CANDIDATES:
        test_market(mk)

if __name__ == "__main__":
    main()
