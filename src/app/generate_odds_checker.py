# -*- coding: utf-8 -*-
"""
Multi-Sport Odds Checker (Soccer + NFL + NBA)
Outputs:
  data/auto/odds_checker/index.html                (SPORT picker)
  data/auto/odds_checker/<league>/index.html       (fixtures for league)
  data/auto/odds_checker/<league>/<fixture>.html   (per-fixture page)
"""

import html
import re
from datetime import datetime, timezone
from pathlib import Path
import requests
import pandas as pd

# ================= CONFIG =================

API_KEY = "8e8a4a2421e95ad2fb0df450c88ef6c6"

LEAGUES = {
    # SOCCER
    "epl": "soccer_epl",
    "la_liga": "soccer_spain_la_liga",
    "bundesliga": "soccer_germany_bundesliga",
    "serie_a": "soccer_italy_serie_a",
    "ucl": "soccer_uefa_champs_league",

    # NFL
    "nfl": "americanfootball_nfl",

    # NBA
    "nba": "basketball_nba",
}

SPORT_GROUPS = {
    "Soccer": ["epl", "la_liga", "bundesliga", "serie_a", "ucl"],
    "NFL": ["nfl"],
    "NBA": ["nba"],
}

REGIONS = "eu"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

BASE_OUTPUT_DIR = Path("data/auto/odds_checker")

THEME_BG = "#0F1621"
TXT = "#E2E8F0"

# Soccer handicap lines only
POPULAR_SPREAD_LINES = {-1.0, 0.0, 1.0}

# ================= HELPERS =================

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

def tidy_book(name):
    if not name:
        return "Unknown"
    return {
        "Sky Bet": "SkyBet",
        "Betfair": "Betfair Sportsbook",
        "Paddy Power": "PaddyPower",
    }.get(name, name)

def slugify(s):
    s = (s or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^\w\s-]", " ", s)
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "team"

def fixture_slug(home, away):
    return f"{slugify(home)}-vs-{slugify(away)}.html"

# ================= API =================

def fetch(league_key, markets):
    url = f"https://api.the-odds-api.com/v4/sports/{league_key}/odds"
    params = dict(
        apiKey=API_KEY,
        regions=REGIONS,
        markets=markets,
        oddsFormat=ODDS_FORMAT,
        dateFormat=DATE_FORMAT,
    )
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(r.text)
    return r.json()

# ================= DATAFRAMES =================

def df_h2h(data):
    rows = []
    for g in data:
        for b in g.get("bookmakers", []):
            for m in b.get("markets", []):
                if m.get("key") != "h2h":
                    continue
                for o in m.get("outcomes", []):
                    if o.get("price") is None:
                        continue
                    rows.append(dict(
                        event_id=g["id"],
                        time=g["commence_time"],
                        home=g["home_team"],
                        away=g["away_team"],
                        book=tidy_book(b["title"]),
                        market="h2h",
                        side=o["name"],
                        odds=float(o["price"]),
                    ))
    return pd.DataFrame(rows)

def df_totals(data):
    rows = []
    for g in data:
        for b in g.get("bookmakers", []):
            for m in b.get("markets", []):
                if m.get("key") != "totals":
                    continue
                for o in m.get("outcomes", []):
                    if o.get("price") is None or o.get("point") is None:
                        continue
                    rows.append(dict(
                        event_id=g["id"],
                        time=g["commence_time"],
                        home=g["home_team"],
                        away=g["away_team"],
                        book=tidy_book(b["title"]),
                        market="totals",
                        side=o["name"].title(),
                        line=float(o["point"]),
                        odds=float(o["price"]),
                    ))
    return pd.DataFrame(rows)

def df_spreads(data):
    rows = []
    for g in data:
        for b in g.get("bookmakers", []):
            for m in b.get("markets", []):
                if m.get("key") != "spreads":
                    continue
                for o in m.get("outcomes", []):
                    if o.get("price") is None or o.get("point") is None:
                        continue
                    line = float(o["point"])
                    if line not in POPULAR_SPREAD_LINES:
                        continue
                    rows.append(dict(
                        event_id=g["id"],
                        time=g["commence_time"],
                        home=g["home_team"],
                        away=g["away_team"],
                        book=tidy_book(b["title"]),
                        market="spreads",
                        side=o["name"],
                        line=line,
                        odds=float(o["price"]),
                    ))
    return pd.DataFrame(rows)

# ================= RENDERING =================

def render_fixture_page(fx, h2h, totals, spreads):
    out = [f"""
<!doctype html>
<html>
<body style="background:{THEME_BG};color:{TXT};padding:24px;font-family:Inter,system-ui">
<a href="index.html" style="color:#93C5FD">← All fixtures</a>
<h1>{html.escape(fx['home'])} vs {html.escape(fx['away'])}</h1>
<p>Kickoff (UTC): {fx['time']} · Updated {now_iso()}</p>
"""]

    for title, df in [("Match Result", h2h), ("Totals", totals), ("Spreads", spreads)]:
        if df.empty:
            continue
        out.append(f"<h2>{title}</h2>")
        for _, r in df.iterrows():
            out.append(f"<p>{r['side']} — {r['odds']} @ {r['book']}</p>")

    out.append("</body></html>")
    return "".join(out)

def render_league_index(league, games):
    items = []
    for _, fx in games.iterrows():
        items.append(f"""
<a href="{fixture_slug(fx['home'], fx['away'])}" style="color:{TXT};text-decoration:none">
<div style="background:#111827;padding:14px;border-radius:12px;margin:10px 0">
<strong>{fx['home']} vs {fx['away']}</strong><br>
<span style="opacity:.7">{fx['time']} UTC</span>
</div></a>
""")

    return f"""
<!doctype html>
<html>
<body style="background:{THEME_BG};color:{TXT};padding:24px;font-family:Inter,system-ui">
<a href="../index.html" style="color:#93C5FD">← All sports</a>
<h1>{league.replace("_"," ").title()} Odds Checker</h1>
{''.join(items)}
</body></html>
"""

def render_root_index(available_leagues):
    sections = []

    for sport, leagues in SPORT_GROUPS.items():
        visible = [l for l in leagues if l in available_leagues]
        if not visible:
            continue

        sections.append(f"<h2 style='margin-top:28px'>{sport.upper()}</h2>")

        for league in visible:
            sections.append(f"""
<a href="{league}/index.html" style="color:{TXT};text-decoration:none">
<div style="background:#111827;padding:14px;border-radius:12px;margin:10px 0">
<strong>{league.replace("_"," ").title()}</strong>
</div></a>
""")

    return f"""
<!doctype html>
<html>
<body style="background:{THEME_BG};color:{TXT};padding:24px;font-family:Inter,system-ui">
<h1>Odds Checker</h1>
<p>Updated: {now_iso()}</p>
{''.join(sections)}
</body></html>
"""

# ================= MAIN =================

def main():
    BASE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_games = []
    h2h_all, totals_all, spreads_all = [], [], []

    for league, key in LEAGUES.items():
        try:
            raw = fetch(key, "h2h")
            h2h = df_h2h(raw)
            if not h2h.empty:
                h2h["league"] = league
                h2h_all.append(h2h)

            raw = fetch(key, "totals")
            totals = df_totals(raw)
            if not totals.empty:
                totals["league"] = league
                totals_all.append(totals)

            raw = fetch(key, "spreads")
            spreads = df_spreads(raw)
            if not spreads.empty:
                spreads["league"] = league
                spreads_all.append(spreads)

        except Exception as e:
            print(f"Skipping {league}: {e}")

    df_h2h = pd.concat(h2h_all, ignore_index=True)
    df_totals = pd.concat(totals_all, ignore_index=True) if totals_all else pd.DataFrame()
    df_spreads = pd.concat(spreads_all, ignore_index=True) if spreads_all else pd.DataFrame()

    games = df_h2h[["event_id","time","home","away","league"]].drop_duplicates()

    for _, fx in games.iterrows():
        ldir = BASE_OUTPUT_DIR / fx["league"]
        ldir.mkdir(exist_ok=True)

        html_page = render_fixture_page(
            fx,
            df_h2h[df_h2h.event_id == fx.event_id],
            df_totals[df_totals.event_id == fx.event_id] if not df_totals.empty else pd.DataFrame(),
            df_spreads[df_spreads.event_id == fx.event_id] if not df_spreads.empty else pd.DataFrame(),
        )

        (ldir / fixture_slug(fx["home"], fx["away"])).write_text(html_page, encoding="utf-8")

    for league in games["league"].unique():
        ldir = BASE_OUTPUT_DIR / league
        (ldir / "index.html").write_text(
            render_league_index(league, games[games.league == league]),
            encoding="utf-8"
        )

    (BASE_OUTPUT_DIR / "index.html").write_text(
        render_root_index(games["league"].unique()),
        encoding="utf-8"
    )

if __name__ == "__main__":
    main()
