# -*- coding: utf-8 -*-
"""
Multi-Sport Odds Checker
Now supports UK / EU bookmaker separation.

Run examples:
python generate_odds_checker.py --group UK
python generate_odds_checker.py --group EU
"""

import html
import re
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
import requests
import pandas as pd

# ================= CONFIG =================

API_KEY = "8e8a4a2421e95ad2fb0df450c88ef6c6"

SPORTS = {
    "Soccer": {
        "epl": "soccer_epl",
        "la_liga": "soccer_spain_la_liga",
        "bundesliga": "soccer_germany_bundesliga",
        "serie_a": "soccer_italy_serie_a",
        "ucl": "soccer_uefa_champs_league",
    },
    "NFL": {"nfl": "americanfootball_nfl"},
    "NBA": {"nba": "basketball_nba"},
}

REGIONS = "uk,eu"   # ✅ fetch both
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

THEME_BG = "#0F1621"
TXT = "#E2E8F0"

POPULAR_SOCCER_SPREADS = {-1.0, 0.0, 1.0}

# ================= BOOKMAKER GROUPS =================

def load_bookmaker_groups(path="config/bookmakers.json"):
    return json.loads(Path(path).read_text(encoding="utf-8"))

# ================= HELPERS =================

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def is_future_game(iso_time: str) -> bool:
    try:
        kickoff = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        return kickoff > datetime.now(timezone.utc)
    except Exception:
        return False

def slugify(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text or "item"

def fetch(sport_key: str):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": "h2h,totals,spreads",
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": DATE_FORMAT,
    }
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        print(f"[WARN] {sport_key}: {r.status_code}")
        return []
    return r.json()

# ================= DATA BUILD =================

def flatten(data, sport_name, allowed_keys: set):
    rows = []

    for g in data:
        kickoff = g.get("commence_time")
        if not kickoff or not is_future_game(kickoff):
            continue

        home = g.get("home_team")
        away = g.get("away_team")
        gid = g.get("id")

        for b in g.get("bookmakers", []):
            book_key = (b.get("key") or "").strip()
            if book_key not in allowed_keys:
                continue   # ✅ FILTER HERE

            book = b.get("title") or book_key or "Book"

            for m in b.get("markets", []):
                mkey = m.get("key")

                for o in m.get("outcomes", []):
                    price = o.get("price")
                    point = o.get("point")
                    name = (o.get("name") or "").strip()

                    if price is None:
                        continue

                    side = None
                    line = None

                    if mkey == "h2h":
                        if name.lower() == (home or "").lower():
                            side = "Home"
                        elif name.lower() == (away or "").lower():
                            side = "Away"
                        elif name.lower() == "draw":
                            side = "Draw"
                        else:
                            continue

                    elif mkey == "totals":
                        if "over" in name.lower():
                            side = "Over"
                        elif "under" in name.lower():
                            side = "Under"
                        else:
                            continue
                        if point is None:
                            continue
                        line = float(point)

                    elif mkey == "spreads":
                        if point is None:
                            continue
                        line = float(point)

                        if sport_name == "Soccer" and line not in POPULAR_SOCCER_SPREADS:
                            continue

                        if name.lower() == (home or "").lower():
                            side = "Home"
                        elif name.lower() == (away or "").lower():
                            side = "Away"
                        else:
                            continue

                    if side is None:
                        continue

                    rows.append({
                        "sport": sport_name,
                        "event_id": gid,
                        "home": home,
                        "away": away,
                        "kickoff": kickoff,
                        "market": mkey,
                        "side": side,
                        "line": line,
                        "book": book,
                        "odds": float(price),
                    })

    return pd.DataFrame(rows)

# ================= HTML UI (UNCHANGED) =================
# (everything from page_shell() down stays the same)

# ================= MAIN =================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=["UK", "EU"], default="EU")
    args = parser.parse_args()

    groups = load_bookmaker_groups()
    allowed_keys = set(groups.get(args.group, []))

    BASE_OUTPUT_DIR = Path(f"data/auto/odds_checker_{args.group.lower()}")
    BASE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sport_groups = {}
    updated_stamp = now_iso()

    for sport_name, leagues in SPORTS.items():
        for league_slug, api_key in leagues.items():
            data = fetch(api_key)
            df = flatten(data, sport_name, allowed_keys)

            if df.empty:
                continue

            league_dir = BASE_OUTPUT_DIR / league_slug
            league_dir.mkdir(parents=True, exist_ok=True)

            games = (
                df[["event_id", "home", "away", "kickoff"]]
                .drop_duplicates()
                .sort_values("kickoff")
            )

            rows = []
            for _, g in games.iterrows():
                slug = f"{slugify(g['home'])}-vs-{slugify(g['away'])}.html"

                rows.append(card(
                    f"{g['home']} vs {g['away']}",
                    f"Kickoff (UTC): {g['kickoff']}",
                    slug
                ))

                match_df = df[df["event_id"] == g["event_id"]].copy()
                fixture_html = render_fixture_page(
                    match_df=match_df,
                    home=g["home"],
                    away=g["away"],
                    kickoff=g["kickoff"],
                    updated=updated_stamp
                )
                (league_dir / slug).write_text(fixture_html, encoding="utf-8")

            league_body = f"""
<div class="navtop"><a href="../index.html">← All sports</a></div>
<h1>{html.escape(league_slug.replace('_',' ').title())}</h1>
<div class="meta">Updated: {updated_stamp}</div>
<div class="gridcards">{''.join(rows)}</div>
"""
            (league_dir / "index.html").write_text(
                page_shell(f"{league_slug} fixtures", league_body),
                encoding="utf-8"
            )

            sport_groups.setdefault(sport_name, []).append(
                (league_slug, league_slug.replace("_", " ").title())
            )

    (BASE_OUTPUT_DIR / "index.html").write_text(
        render_root_index(sport_groups),
        encoding="utf-8"
    )

if __name__ == "__main__":
    main()
