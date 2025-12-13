# -*- coding: utf-8 -*-
"""
BeatTheBooks Arbitrage Finder — Soccer + NFL
Markets:
- Soccer: 1X2, Totals, Spreads
- NFL: Moneyline, Totals, Spreads

Output:
  data/auto/arb_latest.html
"""

import html
from datetime import datetime, timezone
from pathlib import Path
import requests
import pandas as pd

# ================= CONFIG =================

API_KEY = "8e8a4a2421e95ad2fb0df450c88ef6c6"

SPORTS = {
    "Premier League": ("soccer_epl", "soccer"),
    "La Liga": ("soccer_spain_la_liga", "soccer"),
    "Bundesliga": ("soccer_germany_bundesliga", "soccer"),
    "Serie A": ("soccer_italy_serie_a", "soccer"),
    "Champions League": ("soccer_uefa_champs_league", "soccer"),
    "NFL": ("americanfootball_nfl", "nfl"),
}

REGIONS = "eu"
MARKETS = "h2h,totals,spreads"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

BANKROLL = 100.0
MIN_ROI_PCT = 1.0
OUTPUT_HTML = Path("data/auto/arb_latest.html")

SPREAD_LINES = {
    "soccer": {-1.0, 0.0, 1.0},
    "nfl": {-7.5, -3.5, 0.0, 3.5, 7.5},
}

ODDS_MIN = 1.01
ODDS_MAX = 1000.0

# ================= HELPERS =================

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

def fetch_odds(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = dict(
        apiKey=API_KEY,
        regions=REGIONS,
        markets=MARKETS,
        oddsFormat=ODDS_FORMAT,
        dateFormat=DATE_FORMAT,
    )
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        print(f"[WARN] {sport_key}: HTTP {r.status_code}")
        return []
    return r.json()

# ================= FLATTEN =================

def flatten(league, sport_type, data):
    rows = []

    for g in data:
        home = g.get("home_team")
        away = g.get("away_team")
        kickoff = g.get("commence_time")
        gid = g.get("id")

        for b in g.get("bookmakers", []):
            book = b.get("title", "")
            for m in b.get("markets", []):
                key = m.get("key")

                for o in m.get("outcomes", []):
                    odds = o.get("price")
                    name = (o.get("name") or "").strip()
                    point = o.get("point")

                    if odds is None:
                        continue

                    odds = float(odds)
                    if not (ODDS_MIN <= odds <= ODDS_MAX):
                        continue

                    side = None
                    line = None

                    if key == "h2h":
                        if name.lower() == "draw" and sport_type == "soccer":
                            side = "Draw"
                        elif name.lower() == (home or "").lower():
                            side = "Home"
                        elif name.lower() == (away or "").lower():
                            side = "Away"
                        else:
                            continue

                    elif key == "totals":
                        if point is None:
                            continue
                        line = float(point)
                        if "over" in name.lower():
                            side = "Over"
                        elif "under" in name.lower():
                            side = "Under"
                        else:
                            continue

                    elif key == "spreads":
                        if point is None:
                            continue
                        line = float(point)
                        if line not in SPREAD_LINES[sport_type]:
                            continue
                        if name.lower() == (home or "").lower():
                            side = "Home"
                        elif name.lower() == (away or "").lower():
                            side = "Away"
                        else:
                            continue

                    rows.append({
                        "league": league,
                        "sport": sport_type,
                        "event_id": gid,
                        "home": home,
                        "away": away,
                        "kickoff": kickoff,
                        "market": key,
                        "side": side,
                        "line": line,
                        "odds": odds,
                        "book": book,
                    })

    return pd.DataFrame(rows)

# ================= ARBITRAGE =================

def best_by_side(df):
    return df.sort_values("odds", ascending=False).groupby("side").first()

def build_h2h_arbs(df):
    out = []
    df = df[df.market == "h2h"]

    for (_, league, sport), g in df.groupby(["event_id", "league", "sport"]):
        sides = set(g.side)

        if sport == "soccer" and sides != {"Home", "Draw", "Away"}:
            continue
        if sport == "nfl" and sides != {"Home", "Away"}:
            continue

        best = best_by_side(g)
        inv_sum = sum(1 / best.odds)

        if inv_sum >= 1:
            continue

        roi = (1 - inv_sum) * 100
        if roi < MIN_ROI_PCT:
            continue

        row = {
            "league": league,
            "fixture": f"{g.iloc[0].home} vs {g.iloc[0].away}",
            "roi": round(roi, 2),
            "stakes": {}
        }

        for side in best.index:
            row["stakes"][side] = {
                "odds": best.loc[side].odds,
                "book": best.loc[side].book,
                "stake": round((BANKROLL / best.loc[side].odds) / inv_sum, 2)
            }

        out.append(row)

    return out

# ================= HTML =================

def render(arbs):
    ts = now_iso()

    html_out = f"""
<!doctype html>
<html>
<body style="background:#0F1621;color:#E2E8F0;font-family:Inter,system-ui;padding:24px;">
<h1>Soccer & NFL Arbitrage Board</h1>
<p>Updated: {ts} · Bankroll £{BANKROLL:.0f} · Min ROI {MIN_ROI_PCT:.0f}%</p>
"""

    if not arbs:
        html_out += "<p>No arbitrage opportunities found.</p>"
    else:
        for a in arbs:
            html_out += f"""
<div style="border:1px solid #1F2937;border-radius:12px;padding:14px;margin:16px 0;">
<h3>{html.escape(a['league'])} — {html.escape(a['fixture'])}</h3>
<p>ROI: <strong>{a['roi']}%</strong></p>
<ul>
"""
            for side, d in a["stakes"].items():
                html_out += (
                    f"<li>{side}: {d['odds']} @ {html.escape(d['book'])} "
                    f"— £{d['stake']}</li>"
                )
            html_out += "</ul></div>"

    html_out += "</body></html>"
    return html_out

# ================= MAIN =================

def main():
    frames = []

    for league, (key, sport) in SPORTS.items():
        data = fetch_odds(key)
        df = flatten(league, sport, data)
        if not df.empty:
            frames.append(df)

    if not frames:
        OUTPUT_HTML.write_text(render([]), encoding="utf-8")
        return

    full = pd.concat(frames, ignore_index=True)
    arbs = build_h2h_arbs(full)

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(render(arbs), encoding="utf-8")
    print("Arbitrage board updated")

if __name__ == "__main__":
    main()
