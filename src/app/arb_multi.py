# -*- coding: utf-8 -*-
"""
Multi-Sport Arbitrage Board
Soccer (1X2 + Totals + Spreads)
NBA (H2H 2-way + Totals + Spreads)

Output:
  data/auto/arb_latest.html
"""

import html
from datetime import datetime, timezone
from pathlib import Path
import requests
import pandas as pd

# ================= CONFIG =================

API_KEY = "YOUR_API_KEY_HERE"

SPORTS = {
    "Soccer — Premier League": "soccer_epl",
    "Soccer — La Liga": "soccer_spain_la_liga",
    "Soccer — Bundesliga": "soccer_germany_bundesliga",
    "Soccer — Serie A": "soccer_italy_serie_a",
    "Soccer — Champions League": "soccer_uefa_champs_league",

    # NBA
    "NBA": "basketball_nba",
}

REGIONS = "eu"
MARKETS = "h2h,totals,spreads"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

BANKROLL = 100.0
MIN_ROI_PCT = 1.0
OUTPUT_HTML = Path("data/auto/arb_latest.html")

POPULAR_SPREAD_LINES = {-10.5, -7.5, -5.5, -3.5, -1.5, 0.5, 1.5, 3.5, 5.5, 7.5, 10.5}

ODDS_MIN = 1.01
ODDS_MAX = 1000.0

# ================= HELPERS =================

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

def fetch_odds(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": DATE_FORMAT,
    }
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        print(f"[WARN] {sport_key} {r.status_code}")
        return []
    return r.json()

# ================= FLATTEN =================

def flatten(league, data):
    rows = []
    for g in data:
        home = g.get("home_team")
        away = g.get("away_team")
        kickoff = g.get("commence_time")

        for b in g.get("bookmakers", []):
            book = b.get("title")
            for m in b.get("markets", []):
                for o in m.get("outcomes", []):
                    price = o.get("price")
                    if price is None:
                        continue

                    odds = float(price)
                    if not (ODDS_MIN <= odds <= ODDS_MAX):
                        continue

                    name = (o.get("name") or "").lower()
                    line = o.get("point")

                    side = None

                    if m["key"] == "h2h":
                        if name == "draw":
                            side = "Draw"
                        elif name == home.lower():
                            side = "Home"
                        elif name == away.lower():
                            side = "Away"
                        else:
                            continue

                    elif m["key"] == "totals":
                        if "over" in name:
                            side = "Over"
                        elif "under" in name:
                            side = "Under"
                        else:
                            continue
                        line = float(line)

                    elif m["key"] == "spreads":
                        if line is None:
                            continue
                        line = float(line)
                        if line not in POPULAR_SPREAD_LINES:
                            continue
                        if name == home.lower():
                            side = "Home"
                        elif name == away.lower():
                            side = "Away"
                        else:
                            continue

                    rows.append({
                        "league": league,
                        "fixture": f"{home} vs {away}",
                        "kickoff": kickoff,
                        "market": m["key"],
                        "side": side,
                        "line": line,
                        "book": book,
                        "odds": odds,
                    })

    return pd.DataFrame(rows)

# ================= ARB LOGIC =================

def best_by_side(df):
    return df.sort_values("odds", ascending=False).groupby("side").first()

def build_1x2(df):
    rows = []
    df = df[df["market"] == "h2h"]

    for (league, fixture), sub in df.groupby(["league", "fixture"]):
        sides = set(sub["side"])
        if sides != {"Home", "Draw", "Away"}:
            continue

        best = best_by_side(sub)
        inv = sum(1 / best.loc[s, "odds"] for s in ["Home", "Draw", "Away"])
        if inv >= 1:
            continue

        roi = (1 - inv) * 100
        if roi < MIN_ROI_PCT:
            continue

        rows.append({
            "League": league,
            "Fixture": fixture,
            "Home": f"{best.loc['Home','odds']} @ {best.loc['Home','book']}",
            "Draw": f"{best.loc['Draw','odds']} @ {best.loc['Draw','book']}",
            "Away": f"{best.loc['Away','odds']} @ {best.loc['Away','book']}",
            "ROI": f"{roi:.2f}%",
        })

    return pd.DataFrame(rows)

def build_2way(df):
    rows = []
    df = df[df["market"] == "h2h"]

    for (league, fixture), sub in df.groupby(["league", "fixture"]):
        sides = set(sub["side"])
        if sides != {"Home", "Away"}:
            continue

        best = best_by_side(sub)
        inv = (1 / best.loc["Home", "odds"]) + (1 / best.loc["Away", "odds"])
        if inv >= 1:
            continue

        roi = (1 - inv) * 100
        if roi < MIN_ROI_PCT:
            continue

        rows.append({
            "League": league,
            "Fixture": fixture,
            "Home": f"{best.loc['Home','odds']} @ {best.loc['Home','book']}",
            "Away": f"{best.loc['Away','odds']} @ {best.loc['Away','book']}",
            "ROI": f"{roi:.2f}%",
        })

    return pd.DataFrame(rows)

# ================= HTML =================

def render_table(df):
    if df.empty:
        return "<p>No arbitrage opportunities.</p>"

    headers = "".join(f"<th>{h}</th>" for h in df.columns)
    rows = ""
    for _, r in df.iterrows():
        rows += "<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in r) + "</tr>"

    return f"""
    <table>
      <thead><tr>{headers}</tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """

# ================= MAIN =================

def main():
    frames = []

    for league, key in SPORTS.items():
        data = fetch_odds(key)
        df = flatten(league, data)
        if not df.empty:
            frames.append(df)

    if not frames:
        return

    full = pd.concat(frames, ignore_index=True)

    soccer_1x2 = build_1x2(full)
    nba_2way = build_2way(full)

    html_out = f"""
    <html><body>
    <h1>Multi-Sport Arbitrage Board</h1>
    <p>Updated: {now_iso()} | Bankroll £{BANKROLL} | Min ROI {MIN_ROI_PCT}%</p>

    <h2>Soccer 1X2 Arbitrage</h2>
    {render_table(soccer_1x2)}

    <h2>NBA H2H Arbitrage</h2>
    {render_table(nba_2way)}
    </body></html>
    """

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html_out, encoding="utf-8")

if __name__ == "__main__":
    main()

