# -*- coding: utf-8 -*-
"""
Soccer & NFL Arbitrage Finder
Markets: H2H / Totals / Spreads
Single-page output:
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
    "Premier League": "soccer_epl",
    "La Liga": "soccer_spain_la_liga",
    "Bundesliga": "soccer_germany_bundesliga",
    "Serie A": "soccer_italy_serie_a",
    "Champions League": "soccer_uefa_champs_league",
    "NFL": "americanfootball_nfl",
}

REGIONS = "eu"
MARKETS = "h2h,totals,spreads"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

BANKROLL = 100.0
MIN_ROI_PCT = 1.0
OUTPUT_HTML = Path("data/auto/arb_latest.html")

POPULAR_SPREAD_LINES = {-1.0, 0.0, 1.0}
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
        print(f"[WARN] {sport_key}: {r.status_code}")
        return []
    return r.json()

# ================= FLATTEN =================

def flatten(league, data):
    rows = []
    for g in data:
        home, away = g.get("home_team"), g.get("away_team")
        gid, kickoff = g.get("id"), g.get("commence_time")

        if not home or not away:
            continue

        for b in g.get("bookmakers", []):
            book = b.get("title", "")
            for m in b.get("markets", []):
                for o in m.get("outcomes", []):
                    price, point, name = o.get("price"), o.get("point"), (o.get("name") or "").strip()
                    if price is None:
                        continue

                    odds = float(price)
                    if not (ODDS_MIN <= odds <= ODDS_MAX):
                        continue

                    side, line = None, None

                    if m["key"] == "h2h":
                        if name.lower() == "draw":
                            side = "Draw"
                        elif name.lower() == home.lower():
                            side = "Home"
                        elif name.lower() == away.lower():
                            side = "Away"
                        else:
                            continue

                    elif m["key"] == "totals":
                        if "over" in name.lower():
                            side = "Over"
                        elif "under" in name.lower():
                            side = "Under"
                        else:
                            continue
                        if point is None:
                            continue
                        line = float(point)

                    elif m["key"] == "spreads":
                        if point is None:
                            continue
                        line = float(point)
                        if line not in POPULAR_SPREAD_LINES:
                            continue
                        if name.lower() == home.lower():
                            side = "Home"
                        elif name.lower() == away.lower():
                            side = "Away"
                        else:
                            continue

                    rows.append({
                        "league": league,
                        "fixture": f"{home} vs {away}",
                        "market": m["key"],
                        "side": side,
                        "line": line,
                        "odds": odds,
                        "book": book,
                    })

    return pd.DataFrame(rows)

# ================= ARB CORE =================

def best_per_side(df):
    return df.sort_values("odds", ascending=False).groupby("side").first()

def calc_roi(best):
    return (1 - sum(1 / best["odds"])) * 100

def stakes(best):
    inv = sum(1 / best["odds"])
    return {s: round((BANKROLL / r.odds) / inv, 2) for s, r in best.iterrows()}

# ================= TABLE RENDER =================

def table(headers, rows):
    th = "".join(f"<th>{h}</th>" for h in headers)
    return f"""
    <div style="overflow:auto;border:1px solid #1F2937;border-radius:12px;margin-bottom:24px;">
      <table style="width:100%;min-width:1050px;border-collapse:collapse;">
        <thead style="background:#111827;">
          <tr>{th}</tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """

def td(x): return f"<td style='padding:10px;border-bottom:1px solid #111827;'>{x}</td>"

# ================= HTML =================

def render_board(df):
    out = [f"""
<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="background:#0F1621;color:#E2E8F0;font-family:Inter,system-ui;padding:24px;">
<h1>Soccer & NFL Arbitrage Board</h1>
<p style="opacity:.8">Updated: {now_iso()} · Bankroll £{BANKROLL:.0f} · Min ROI {MIN_ROI_PCT:.0f}%</p>
"""]

    # -------- 1X2 --------
    rows = []
    for (league, fixture), sub in df[df.market == "h2h"].groupby(["league", "fixture"]):
        if set(sub.side) != {"Home", "Draw", "Away"}:
            continue
        best = best_per_side(sub)
        roi = calc_roi(best)
        if roi < MIN_ROI_PCT:
            continue
        st = stakes(best)
        rows.append(
            "<tr>" +
            td(league) +
            td(fixture) +
            td(f"{best.loc['Home'].odds} @ {best.loc['Home'].book}") +
            td(f"{best.loc['Draw'].odds} @ {best.loc['Draw'].book}") +
            td(f"{best.loc['Away'].odds} @ {best.loc['Away'].book}") +
            td(f"{roi:.2f}%") +
            td(f"Home £{st['Home']}<br>Draw £{st['Draw']}<br>Away £{st['Away']}") +
            "</tr>"
        )

    out.append("<h2>Match Result (1X2)</h2>")
    out.append(table(
        ["League", "Fixture", "Home", "Draw", "Away", "ROI", "Suggested Stakes"],
        "".join(rows) if rows else "<tr><td colspan=7>No opportunities</td></tr>"
    ))

    # -------- TOTALS --------
    rows = []
    for (league, fixture, line), sub in df[df.market == "totals"].groupby(["league", "fixture", "line"]):
        if set(sub.side) != {"Over", "Under"}:
            continue
        best = best_per_side(sub)
        roi = calc_roi(best)
        if roi < MIN_ROI_PCT:
            continue
        st = stakes(best)
        rows.append(
            "<tr>" +
            td(league) +
            td(fixture) +
            td(f"{line:.1f}") +
            td(f"{best.loc['Over'].odds} @ {best.loc['Over'].book}") +
            td(f"{best.loc['Under'].odds} @ {best.loc['Under'].book}") +
            td(f"{roi:.2f}%") +
            td(f"Over £{st['Over']}<br>Under £{st['Under']}") +
            "</tr>"
        )

    out.append("<h2>Totals (Over / Under)</h2>")
    out.append(table(
        ["League", "Fixture", "Line", "Over", "Under", "ROI", "Suggested Stakes"],
        "".join(rows) if rows else "<tr><td colspan=7>No opportunities</td></tr>"
    ))

    out.append("</body></html>")
    return "".join(out)

# ================= MAIN =================

def main():
    frames = []
    for league, key in SPORTS.items():
        df = flatten(league, fetch_odds(key))
        if not df.empty:
            frames.append(df)

    if not frames:
        return

    full_df = pd.concat(frames, ignore_index=True)
    html_out = render_board(full_df)
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html_out, encoding="utf-8")
    print("Arbitrage board updated")

if __name__ == "__main__":
    main()
