import json
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "ufc" / "data" / "odds.json"

API_KEY = "98fb91f398403151a3eece97dc514a0b"

SPORT = "mma_mixed_martial_arts"
REGIONS = "uk"
MARKETS = "h2h"
ODDS_FORMAT = "decimal"

URL = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"


def fetch_ufc_odds():
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
    }

    response = requests.get(URL, params=params, timeout=30)
    response.raise_for_status()

    return response.json()


def simplify_odds(events):
    simplified = []

    for event in events:
        home = event.get("home_team")
        away = event.get("away_team")

        fight = {
            "id": event.get("id"),
            "sport_key": event.get("sport_key"),
            "commence_time": event.get("commence_time"),
            "home_team": home,
            "away_team": away,
            "bookmakers": [],
        }

        for bookmaker in event.get("bookmakers", []):
            book = {
                "key": bookmaker.get("key"),
                "title": bookmaker.get("title"),
                "last_update": bookmaker.get("last_update"),
                "markets": [],
            }

            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue

                outcomes = []

                for outcome in market.get("outcomes", []):
                    outcomes.append(
                        {
                            "name": outcome.get("name"),
                            "price": outcome.get("price"),
                        }
                    )

                book["markets"].append(
                    {
                        "key": "h2h",
                        "outcomes": outcomes,
                    }
                )

            if book["markets"]:
                fight["bookmakers"].append(book)

        simplified.append(fight)

    return simplified


def main():
    print("Fetching UFC moneyline odds from The Odds API...")
    raw_events = fetch_ufc_odds()

    odds = simplify_odds(raw_events)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "source": "the_odds_api",
                "sport": SPORT,
                "regions": REGIONS,
                "markets": MARKETS,
                "odds_format": ODDS_FORMAT,
                "events": odds,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"Saved odds for {len(odds)} UFC events to {OUT_PATH}")

    for event in odds[:10]:
        print(f"- {event.get('home_team')} vs {event.get('away_team')}")
        print(f"  Bookmakers: {len(event.get('bookmakers', []))}")


if __name__ == "__main__":
    main()
