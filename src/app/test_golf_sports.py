# Tiny helper to see which golf sport keys your Odds API key supports.

import requests

API_KEY = "98fb91f398403151a3eece97dc514a0b"  

REGIONS = "uk"
MARKETS = "outrights"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 20

SPORT_CANDIDATES = [
    "golf_pga",
    "golf",
    "golf_masters",
    "golf_us_open",
    "golf_british_open",
    "golf_open_championship",
    "golf_pga_championship",
    "golf_the_masters",
    "golf_ryder_cup",
    "golf_lpga",
    "golf_european",
]


def test_sport(sport_key: str) -> None:
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = dict(
        apiKey=API_KEY,
        regions=REGIONS,
        markets=MARKETS,
        oddsFormat=ODDS_FORMAT,
        dateFormat=DATE_FORMAT,
    )
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
    except Exception as e:
        print(f"{sport_key}: REQUEST ERROR: {e}")
        return

    if r.status_code == 200:
        try:
            data = r.json()
        except Exception:
            data = []
        print(
            f"{sport_key}: OK (HTTP 200), markets returned: {len(data)}"
        )
    else:
        # Truncate text so logs stay readable
        msg = r.text.replace("\n", " ")[:200]
        print(f"{sport_key}: HTTP {r.status_code}: {msg}")


def main():
    print("=== Testing golf sport keys for The Odds API ===")
    for s in SPORT_CANDIDATES:
        test_sport(s)


if __name__ == "__main__":
    main()
