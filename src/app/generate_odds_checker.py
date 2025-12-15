# -*- coding: utf-8 -*-
"""
Odds Checker — Sports-based layout (Soccer / NFL / NBA)

Outputs:
  data/auto/odds_checker/index.html
  data/auto/odds_checker/<sport>/<league>/index.html
  data/auto/odds_checker/<sport>/<league>/<fixture>.html
"""

import html
import re
from datetime import datetime, timezone
from pathlib import Path
import requests
import pandas as pd

# ================= CONFIG =================

API_KEY = "8e8a4a2421e95ad2fb0df450c88ef6c6"

SPORTS = {
    "soccer": {
        "title": "Soccer",
        "leagues": {
            "epl": "soccer_epl",
            "la_liga": "soccer_spain_la_liga",
            "bundesliga": "soccer_germany_bundesliga",
            "serie_a": "soccer_italy_serie_a",
            "ucl": "soccer_uefa_champs_league",
        },
        "markets": {"h2h", "totals", "spreads"},
        "spread_lines": {-1.0, 0.0, 1.0},
    },
    "nfl": {
        "title": "NFL",
        "leagues": {"nfl": "americanfootball_nfl"},
        "markets": {"h2h", "totals", "spreads"},
        "spread_lines": {-1.5, 0.0, 1.5, 2.5, 3.5},
    },
    "nba": {
        "title": "NBA",
        "leagues": {"nba": "basketball_nba"},
        "markets": {"h2h", "totals"},
        "spread_lines": set(),
    },
}

REGIONS = "eu"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

BASE_DIR = Path("data/auto/odds_checker")

THEME_BG = "#0F1621"
TXT = "#E2E8F0"

ODDS_MIN = 1.01
ODDS_MAX = 1000.0

# ================= HELPERS =================

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

def tidy_book(name):
    return name or "Unknown"

def slugify(s):
    s = (s or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^\w\s-]", " ", s)
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "event"

def fixture_slug(home, away):
    return f"{slugify(home)}-vs-{slugify(away)}.html"

# ================= API =================

def fetch(sport_key, markets):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = dict(
        apiKey=API_KEY,
        regions=REGIONS,
        markets=",".join(markets),
        oddsFormat=ODDS_FORMAT,
        dateFormat=DATE_FORMAT,
    )
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        return []
    return r.json()

# ================= DF BUILDERS =================

def df_h2h(data):
    rows = []
    for g in data:
        for b in g.get("bookmakers", []):
            for m in b.get("markets", []):
                if m["key"] != "h2h":
                    continue
                for o in m["outcomes"]:
                    if o.get("price") is None:
                        continue
                    side = o["name"]
                    rows.append({
                        "event_id": g["id"],
                        "time": g["commence_time"],
                        "home": g["home_team"],
                        "away": g["away_team"],
                        "book": tidy_book(b["title"]),
                        "market": "h2h",
                        "side": side,
                        "odds": float(o["price"]),
                    })
    return pd.DataFrame(rows)

def df_totals(data):
    rows = []
    for g in data:
        for b in g.get("bookmakers", []):
            for m in b.get("markets", []):
                if m["key"] != "totals":
                    continue
                for o in m["outcomes"]:
                    if o.get("price") is None or o.get("point") is None:
                        continue
                    rows.append({
                        "event_id": g["id"],
                        "time": g["commence_time"],
                        "home": g["home_team"],
                        "away": g["away_team"],
                        "book": tidy_book(b["title"]),
                        "market": "totals",
                        "side": o["name"].title(),
                        "line": float(o["point"]),
                        "odds": float(o["price"]),
                    })
    return pd.DataFrame(rows)

def df_spreads(data, allowed_lines):
    rows = []
    for g in data:
        for b in g.get("bookmakers", []):
            for m in b.get("markets", []):
                if m["key"] != "spreads":
                    continue
                for o in m["outcomes"]:
                    if o.get("price") is None or o.get("point") is None:
                        continue
                    line = float(o["point"])
                    if line not in allowed_lines:
                        continue
                    rows.append({
                        "event_id": g["id"],
                        "time": g["commence_time"],
                        "home": g["home_team"],
                        "away": g["away_team"],
                        "book": tidy_book(b["title"]),
                        "market": "spreads",
                        "side": o["name"],
                        "line": line,
                        "odds": float(o["price"]),
                    })
    return pd.DataFrame(rows)

# ================= RENDER =================

def render_index(sections):
    cards = []
    for s in sections:
        cards.append(f"""
        <a href="{s}/index.html" style="text-decoration:none;color:{TXT};">
          <div style="background:#111827;border:1px solid #1F2937;
                      border-radius:14px;padding:18px;margin:14px 0;">
            <h2 style="margin:0;">{s.upper()}</h2>
            <div style="opacity:.7">View odds</div>
          </div>
        </a>
        """)
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="background:{THEME_BG};color:{TXT};font-family:Inter,system-ui;padding:24px;">
<h1>Odds Checker</h1>
<p style="opacity:.8">Updated: {now_iso()}</p>
{''.join(cards)}
</body></html>
"""

# ================= MAIN =================

def main():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    sports_written = []

    for sport, cfg in SPORTS.items():
        sport_dir = BASE_DIR / sport
        sport_dir.mkdir(exist_ok=True)
        any_data = False

        for league, key in cfg["leagues"].items():
            raw = fetch(key, cfg["markets"])
            if not raw:
                continue

            h2h = df_h2h(raw)
            totals = df_totals(raw)
            spreads = df_spreads(raw, cfg["spread_lines"]) if cfg["spread_lines"] else pd.DataFrame()

            if h2h.empty:
                continue

            any_data = True
            league_dir = sport_dir / league
            league_dir.mkdir(exist_ok=True)

            games = h2h[["event_id", "time", "home", "away"]].drop_duplicates()

            for _, fx in games.iterrows():
                page = f"""<!doctype html><html><body style="background:{THEME_BG};
                color:{TXT};font-family:Inter;padding:24px;">
                <h1>{fx['home']} vs {fx['away']}</h1>
                <p>{fx['time']} UTC</p>
                </body></html>"""
                (league_dir / fixture_slug(fx["home"], fx["away"])).write_text(page, encoding="utf-8")

            (league_dir / "index.html").write_text(
                f"<html><body style='background:{THEME_BG};color:{TXT};padding:24px;'>"
                f"<h1>{league.upper()}</h1></body></html>",
                encoding="utf-8",
            )

        if any_data:
            sports_written.append(sport)

    (BASE_DIR / "index.html").write_text(render_index(sports_written), encoding="utf-8")

if __name__ == "__main__":
    main()

