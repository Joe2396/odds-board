# -*- coding: utf-8 -*-
"""
Multi-Sport Arbitrage Board
Soccer (1X2)
NBA (H2H 2-way)

Outputs:
  data/auto/arb_latest_both.html
  data/auto/arb_latest_uk.html
  data/auto/arb_latest_eu.html

Also writes:
  data/auto/arb_latest.html   (alias of BOTH, for Shopify/backwards compatibility)

Run:
  python arb_multi.py --group BOTH
  python arb_multi.py --group UK
  python arb_multi.py --group EU
"""

import os
import html
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

import requests
import pandas as pd

# ================= CONFIG =================

# Prefer GitHub Secret env var; fallback to empty so page still renders with an error banner
API_KEY = "8e8a4a2421e95ad2fb0df450c88ef6c6"

SPORTS = {
    "Soccer — Premier League": "soccer_epl",
    "Soccer — La Liga": "soccer_spain_la_liga",
    "Soccer — Bundesliga": "soccer_germany_bundesliga",
    "Soccer — Serie A": "soccer_italy_serie_a",
    "Soccer — Champions League": "soccer_uefa_champs_league",
    "NBA": "basketball_nba",
}

# Fetch both, then filter into groups
REGIONS = "uk,eu"
MARKETS = "h2h,totals,spreads"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

BANKROLL = 100.0
MIN_ROI_PCT = 1.0

POPULAR_SPREAD_LINES = {-10.5, -7.5, -5.5, -3.5, -1.5, 0.5, 1.5, 3.5, 5.5, 7.5, 10.5}
ODDS_MIN = 1.01
ODDS_MAX = 1000.0

# ================= BOOKMAKER GROUPS =================

def load_bookmaker_groups(path="config/bookmakers.json"):
    return json.loads(Path(path).read_text(encoding="utf-8"))

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

def flatten(league, data, allowed_keys=None):
    rows = []
    for g in data:
        home = g.get("home_team") or ""
        away = g.get("away_team") or ""
        kickoff = g.get("commence_time")

        if not kickoff or not is_future_game(kickoff):
            continue

        for b in g.get("bookmakers", []):
            book_key = (b.get("key") or "").strip()

            # Filter by bookmaker KEY
            if allowed_keys is not None and book_key not in allowed_keys:
                continue

            book_title = b.get("title") or book_key or "Book"

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
                        "book": book_title,
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
            "Home": f"{best.loc['Home','odds']:.2f} @ {best.loc['Home','book']}",
            "Draw": f"{best.loc['Draw','odds']:.2f} @ {best.loc['Draw','book']}",
            "Away": f"{best.loc['Away','odds']:.2f} @ {best.loc['Away','book']}",
            "ROI": f"{roi:.2f}%",
        })

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("ROI", ascending=False)
    return out

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

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("ROI", ascending=False)
    return out

# ================= HTML =================

def render_table(df):
    if df.empty:
        return "<p style='opacity:0.75;'>No arbitrage opportunities right now.</p>"

    headers = "".join(
        f"<th style='text-align:left;padding:10px;border-bottom:1px solid #1F2937;'>{html.escape(h)}</th>"
        for h in df.columns
    )
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

def render_page(soccer_1x2: pd.DataFrame, nba_2way: pd.DataFrame, status_lines: list[str], group: str) -> str:
    group = (group or "BOTH").upper()

    status_html = ""
    if status_lines:
        status_html = (
            "<div style='margin:12px 0 18px;padding:12px;border:1px solid #334155;border-radius:12px;background:#0B1220;'>"
            + "<br>".join(html.escape(s) for s in status_lines)
            + "</div>"
        )

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Arbitrage Board</title>
  <style>
    body {{
      background:#0F1621;
      color:#E2E8F0;
      font-family:Inter,system-ui;
      padding:24px;
      margin:0;
    }}
    .topbar {{
      display:flex;
      justify-content:flex-end;
      align-items:center;
      gap:10px;
      margin-bottom:12px;
    }}
    .topbar label {{
      color: rgba(226,232,240,0.70);
      font-weight:650;
      font-size:14px;
    }}
    .topbar select {{
      background:#0B1220;
      color:#E2E8F0;
      border:1px solid #334155;
      border-radius:10px;
      padding:8px 10px;
      font-weight:700;
      outline:none;
    }}
    h1 {{ margin: 6px 0 6px; }}
    h2 {{ margin-top: 28px; }}
  </style>
</head>
<body>
  <div class="topbar">
    <label for="groupSelect">Bookmakers</label>
    <select id="groupSelect">
      <option value="BOTH">BOTH</option>
      <option value="UK">UK</option>
      <option value="EU">EU</option>
    </select>
  </div>

  <h1>Multi-Sport Arbitrage Board</h1>
  <p style="opacity:0.8;">Updated: {now_iso()} | Bankroll £{BANKROLL:.0f} | Min ROI {MIN_ROI_PCT:.1f}%</p>
  {status_html}

  <h2>Soccer 1X2 Arbitrage</h2>
  {render_table(soccer_1x2)}

  <h2>NBA H2H Arbitrage</h2>
  {render_table(nba_2way)}

<script>
(function() {{
  var current = "{group}";
  var sel = document.getElementById("groupSelect");
  if (sel) sel.value = current;

  function swapGroup(target) {{
    var path = window.location.pathname;

    // swap arb_latest_(uk|eu|both).html
    path = path.replace(/arb_latest_(uk|eu|both)\\.html/i, "arb_latest_" + target.toLowerCase() + ".html");

    // if user is on legacy arb_latest.html, treat it as BOTH and redirect cleanly
    if (/arb_latest\\.html/i.test(window.location.pathname)) {{
      path = path.replace(/arb_latest\\.html/i, "arb_latest_" + target.toLowerCase() + ".html");
    }}

    window.location.pathname = path;
  }}

  if (sel) {{
    sel.addEventListener("change", function() {{
      swapGroup(this.value);
    }});
  }}
}})();
</script>

</body>
</html>
"""

# ================= MAIN =================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=["UK", "EU", "BOTH"], default="BOTH")
    args = parser.parse_args()

    groups = load_bookmaker_groups()

    if args.group == "BOTH":
        allowed_keys = set(groups.get("UK", [])) | set(groups.get("EU", []))
    else:
        allowed_keys = set(groups.get(args.group, []))

    frames = []
    status_lines = []

    if not API_KEY:
        status_lines.append("ERROR: Missing ODDS_API_KEY (GitHub secret). Arbitrage data cannot be fetched.")
        status_lines.append("Fix: add ODDS_API_KEY to repo secrets and ensure workflow passes it.")
    else:
        for league, key in SPORTS.items():
            data, meta = fetch_odds(key)
            if meta.get("status") != 200:
                status_lines.append(
                    f"{league}: API error {meta.get('status')} (remaining={meta.get('remaining')}, used={meta.get('used')})"
                )
                continue

            df = flatten(league, data, allowed_keys=allowed_keys)
            if not df.empty:
                frames.append(df)

    if frames:
        full = pd.concat(frames, ignore_index=True)
    else:
        full = pd.DataFrame(columns=["league","fixture","kickoff","market","side","line","book","odds"])

    soccer_1x2 = build_1x2(full)
    nba_2way = build_2way(full)

    html_out = render_page(soccer_1x2, nba_2way, status_lines, args.group)

    out = Path(f"data/auto/arb_latest_{args.group.lower()}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_out, encoding="utf-8")
    print(f"Wrote: {out}")

    # Backwards-compatible alias for Shopify / existing links
    if args.group == "BOTH":
        alias = Path("data/auto/arb_latest.html")
        alias.write_text(html_out, encoding="utf-8")
        print(f"Wrote alias: {alias}")

if __name__ == "__main__":
    main()

