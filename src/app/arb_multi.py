# -*- coding: utf-8 -*-
"""
Multi-Sport Arbitrage Board
Soccer (1X2)
NBA (H2H 2-way)

Output:
  data/auto/arb_latest.html
"""

import os
import html
from datetime import datetime, timezone
from pathlib import Path
import requests
import pandas as pd

# ================= CONFIG =================

API_KEY = os.getenv("ODDS_API_KEY")
# If not set, we still generate a page (so the site updates), but we'll show an error banner.
# This prevents the "stuck since December" problem.
SPORTS = {
    "Soccer — Premier League": "soccer_epl",
    "Soccer — La Liga": "soccer_spain_la_liga",
    "Soccer — Bundesliga": "soccer_germany_bundesliga",
    "Soccer — Serie A": "soccer_italy_serie_a",
    "Soccer — Champions League": "soccer_uefa_champs_league",
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
    if not API_KEY:
        return [], {"status": "missing_api_key"}

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": DATE_FORMAT,
    }
    r = requests.get(url, params=params, timeout=TIMEOUT)

    meta = {
        "status": r.status_code,
        "remaining": r.headers.get("x-requests-remaining"),
        "used": r.headers.get("x-requests-used"),
    }

    if r.status_code != 200:
        print(f"[WARN] {sport_key} HTTP {r.status_code}")
        return [], meta

    return r.json(), meta

def is_future_game(iso_time: str) -> bool:
    try:
        kickoff = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        return kickoff > datetime.now(timezone.utc)
    except Exception:
        return False

# ================= FLATTEN =================

def flatten(league, data):
    rows = []
    for g in data:
        home = g.get("home_team") or ""
        away = g.get("away_team") or ""
        kickoff = g.get("commence_time")

        # avoid stale/completed games
        if not kickoff or not is_future_game(kickoff):
            continue

        for b in g.get("bookmakers", []):
            book = b.get("title") or b.get("key") or "Book"
            for m in b.get("markets", []):
                mkey = m.get("key")

                for o in m.get("outcomes", []):
                    price = o.get("price")
                    if price is None:
                        continue

                    odds = float(price)
                    if not (ODDS_MIN <= odds <= ODDS_MAX):
                        continue

                    name = (o.get("name") or "").strip().lower()
                    line = o.get("point")

                    side = None
                    line_val = None

                    if mkey == "h2h":
                        if name == "draw":
                            side = "Draw"
                        elif name == home.lower():
                            side = "Home"
                        elif name == away.lower():
                            side = "Away"
                        else:
                            continue

                    elif mkey == "totals":
                        # not used in current arb build, but keep flattening for later expansion
                        if "over" in name:
                            side = "Over"
                        elif "under" in name:
                            side = "Under"
                        else:
                            continue
                        if line is None:
                            continue
                        line_val = float(line)

                    elif mkey == "spreads":
                        # not used in current arb build, but keep flattening for later expansion
                        if line is None:
                            continue
                        line_val = float(line)
                        if line_val not in POPULAR_SPREAD_LINES:
                            continue
                        if name == home.lower():
                            side = "Home"
                        elif name == away.lower():
                            side = "Away"
                        else:
                            continue

                    if side is None:
                        continue

                    rows.append({
                        "league": league,
                        "fixture": f"{home} vs {away}",
                        "kickoff": kickoff,
                        "market": mkey,
                        "side": side,
                        "line": line_val,
                        "book": book,
                        "odds": odds,
                    })

    return pd.DataFrame(rows)

# ================= ARB LOGIC =================

def best_by_side(df):
    # best odds (highest) per side
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
            "Home": f"{best.loc['Home','odds']:.2f} @ {best.loc['Home','book']}",
            "Draw": f"{best.loc['Draw','odds']:.2f} @ {best.loc['Draw','book']}",
            "Away": f"{best.loc['Away','odds']:.2f} @ {best.loc['Away','book']}",
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
            "Home": f"{best.loc['Home','odds']:.2f} @ {best.loc['Home','book']}",
            "Away": f"{best.loc['Away','odds']:.2f} @ {best.loc['Away','book']}",
            "ROI": f"{roi:.2f}%",
        })

    return pd.DataFrame(rows)

# ================= HTML =================

def render_table(df):
    if df.empty:
        return "<p style='opacity:0.75;'>No arbitrage opportunities right now.</p>"

    headers = "".join(f"<th style='text-align:left;padding:10px;border-bottom:1px solid #1F2937;'>{html.escape(h)}</th>" for h in df.columns)
    rows = ""
    for _, r in df.iterrows():
        rows += "<tr>" + "".join(
            f"<td style='padding:10px;border-bottom:1px solid #111827;'>{html.escape(str(v))}</td>"
            for v in r
        ) + "</tr>"

    return f"""
    <table style="width:100%;border-collapse:collapse;">
      <thead><tr>{headers}</tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """

def render_page(soccer_1x2: pd.DataFrame, nba_2way: pd.DataFrame, status_lines: list[str]) -> str:
    status_html = ""
    if status_lines:
        status_html = "<div style='margin:12px 0 18px;padding:12px;border:1px solid #334155;border-radius:12px;background:#0B1220;'>" + \
                      "<br>".join(html.escape(s) for s in status_lines) + \
                      "</div>"

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Arbitrage Board</title>
</head>
<body style="background:#0F1621;color:#E2E8F0;font-family:Inter,system-ui;padding:24px;">
  <h1>Multi-Sport Arbitrage Board</h1>
  <p style="opacity:0.8;">Updated: {now_iso()} | Bankroll £{BANKROLL:.0f} | Min ROI {MIN_ROI_PCT:.1f}%</p>
  {status_html}

  <h2>Soccer 1X2 Arbitrage</h2>
  {render_table(soccer_1x2)}

  <h2 style="margin-top:28px;">NBA H2H Arbitrage</h2>
  {render_table(nba_2way)}
</body>
</html>
"""

# ================= MAIN =================

def main():
    frames = []
    status_lines = []

    if not API_KEY:
        status_lines.append("ERROR: Missing ODDS_API_KEY (GitHub secret). Arbitrage data cannot be fetched.")
        status_lines.append("Fix: add ODDS_API_KEY to repo secrets and ensure workflow passes it.")
    else:
        # fetch all leagues
        for league, key in SPORTS.items():
            data, meta = fetch_odds(key)
            if meta.get("status") != 200:
                status_lines.append(f"{league}: API error {meta.get('status')} (remaining={meta.get('remaining')}, used={meta.get('used')})")
                continue

            df = flatten(league, data)
            if not df.empty:
                frames.append(df)

    if frames:
        full = pd.concat(frames, ignore_index=True)
    else:
        full = pd.DataFrame(columns=["league","fixture","kickoff","market","side","line","book","odds"])

    soccer_1x2 = build_1x2(full)
    nba_2way = build_2way(full)

    html_out = render_page(soccer_1x2, nba_2way, status_lines)

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html_out, encoding="utf-8")
    print(f"Wrote: {OUTPUT_HTML}")

if __name__ == "__main__":
    main()
