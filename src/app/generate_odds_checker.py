# -*- coding: utf-8 -*-
"""
Multi-Sport Odds Checker
Sports:
- Soccer (EPL, La Liga, Bundesliga, Serie A, UCL)
- NFL
- NBA

Outputs:
data/auto/odds_checker/index.html
+ per-league index pages
+ per-fixture pages (match pages)
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

REGIONS = "eu"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

BASE_OUTPUT_DIR = Path("data/auto/odds_checker")

THEME_BG = "#0F1621"
TXT = "#E2E8F0"

POPULAR_SOCCER_SPREADS = {-1.0, 0.0, 1.0}

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

def flatten(data, sport_name):
    rows = []

    for g in data:
        kickoff = g.get("commence_time")
        if not kickoff or not is_future_game(kickoff):
            continue

        home = g.get("home_team")
        away = g.get("away_team")
        gid = g.get("id")

        for b in g.get("bookmakers", []):
            book = b.get("title") or b.get("key") or "Book"
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

                    # extra safety: do not allow rows without side
                    if side is None:
                        continue

                    rows.append({
                        "sport": sport_name,
                        "event_id": gid,
                        "home": home,
                        "away": away,
                        "kickoff": kickoff,
                        "market": mkey,   # h2h / totals / spreads
                        "side": side,     # Home/Away/Draw OR Over/Under OR Home/Away
                        "line": line,     # totals/spreads number, else None
                        "book": book,
                        "odds": float(price),
                    })

    return pd.DataFrame(rows)

# ================= HTML UI =================

def page_shell(title: str, body_html: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  :root {{
    --bg: {THEME_BG};
    --fg: {TXT};
    --card: #0B1220;
    --card2: #0E1A2D;
    --border: #1F2937;
    --muted: rgba(226,232,240,0.70);
    --link: #93C5FD;
    --pill: rgba(148,163,184,0.12);
    --pillBorder: rgba(148,163,184,0.22);
    --bestBg: rgba(16,185,129,0.14);
    --bestBorder: rgba(16,185,129,0.35);
  }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--fg);
    font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial;
  }}
  .wrap {{
    max-width: 1100px;
    margin: 0 auto;
    padding: 22px 18px 44px;
  }}
  a {{ color: var(--link); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  h1 {{ margin: 6px 0 6px; font-size: 42px; letter-spacing: -0.02em; }}
  h2 {{ margin: 24px 0 10px; font-size: 26px; }}
  .meta {{ color: var(--muted); margin-bottom: 16px; }}
  .navtop {{ margin: 8px 0 18px; }}
  .panel {{
    background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.00));
    border: 1px solid var(--border);
    border-radius: 16px;
    overflow: hidden;
    margin: 14px 0 22px;
  }}
  .panel-h {{
    padding: 14px 16px;
    border-bottom: 1px solid var(--border);
    background: rgba(255,255,255,0.02);
    font-weight: 800;
    font-size: 22px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 16px;
  }}
  th, td {{
    padding: 14px 16px;
    vertical-align: middle;
  }}
  th {{
    text-align: left;
    color: var(--muted);
    font-weight: 700;
    background: rgba(255,255,255,0.01);
  }}
  tr + tr td {{
    border-top: 1px solid rgba(31,41,55,0.8);
  }}
  .best {{
    font-weight: 800;
    font-size: 22px;
    line-height: 1.1;
  }}
  .best small {{
    display: block;
    font-size: 14px;
    font-weight: 650;
    color: var(--muted);
    margin-top: 4px;
  }}
  .pills {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }}
  .pill {{
    background: var(--pill);
    border: 1px solid var(--pillBorder);
    padding: 6px 10px;
    border-radius: 999px;
    white-space: nowrap;
  }}
  .pill.bestpill {{
    background: var(--bestBg);
    border-color: var(--bestBorder);
  }}
  .subtle {{
    color: var(--muted);
    font-size: 14px;
    margin-top: 6px;
  }}
  .gridcards a {{
    text-decoration: none;
  }}
  .card {{
    background: #111827;
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 16px;
    margin: 12px 0;
  }}
  .card-title {{
    font-size: 18px;
    font-weight: 800;
  }}
  .card-sub {{
    margin-top: 6px;
    color: var(--muted);
  }}
</style>
</head>
<body>
  <div class="wrap">
    {body_html}
  </div>
</body>
</html>
"""

def card(title, subtitle, href):
    return f"""
<a href="{href}">
  <div class="card">
    <div class="card-title">{html.escape(title)}</div>
    <div class="card-sub">{html.escape(subtitle)}</div>
  </div>
</a>
"""

def render_root_index(groups):
    sections = []
    for sport, leagues in groups.items():
        blocks = []
        for league_key, league_name in leagues:
            blocks.append(card(league_name, "Open fixtures", f"{league_key}/index.html"))
        sections.append(f"<h2>{html.escape(sport)}</h2><div class='gridcards'>{''.join(blocks)}</div>")

    body = f"""
<h1>Odds Checker</h1>
<div class="meta">Updated: {now_iso()}</div>
{''.join(sections)}
"""
    return page_shell("Odds Checker", body)

def market_label(market_key: str) -> str:
    if market_key == "h2h":
        return "Match Result (1X2)"
    if market_key == "totals":
        return "Totals (Over/Under)"
    if market_key == "spreads":
        return "Spreads (Handicap)"
    return market_key.upper()

def format_odds(x: float) -> str:
    try:
        return f"{float(x):.2f}".rstrip("0").rstrip(".")
    except Exception:
        return str(x)

def render_market_panels(match_df: pd.DataFrame) -> str:
    """
    For each market:
      - group by (line, side) so totals/spreads show separate lines
      - for each outcome row, show:
          outcome | best price | all books sorted
    """
    out = []

    if match_df.empty:
        return "<div class='meta'>No odds available.</div>"

    # stable market ordering
    market_order = ["h2h", "totals", "spreads"]
    markets = [m for m in market_order if m in set(match_df["market"].tolist())]
    for m in sorted(set(match_df["market"].tolist())):
        if m not in markets:
            markets.append(m)

    for market in markets:
        dfm = match_df[match_df["market"] == market].copy()
        if dfm.empty:
            continue

        # For totals/spreads, separate by line
        # For h2h, line is None, so it naturally forms one group.
        # We'll build rows in a nice logical order:
        # h2h => Home, Draw, Away
        # totals => Over, Under
        # spreads => Home, Away
        if market == "h2h":
            side_order = ["Home", "Draw", "Away"]
        elif market == "totals":
            side_order = ["Over", "Under"]
        else:
            side_order = ["Home", "Away"]

        # Unique (line, side) combos
        # Use line first (so totals/spreads line blocks appear grouped)
        combos = dfm[["line", "side"]].drop_duplicates()

        # sort by line (None last) then side order
        def side_rank(s): 
            try: 
                return side_order.index(s)
            except ValueError:
                return 999

        combos = combos.assign(
            _line_sort=combos["line"].apply(lambda v: 999999 if pd.isna(v) else float(v)),
            _side_sort=combos["side"].apply(side_rank),
        ).sort_values(["_line_sort", "_side_sort"])

        rows_html = []
        for _, c in combos.iterrows():
            line = c["line"]
            side = c["side"]

            block = dfm[(dfm["side"] == side)]
            if pd.isna(line):
                block = block[block["line"].isna()]
            else:
                block = block[block["line"] == float(line)]

            if block.empty:
                continue

            # Sort books by odds best->worst
            block_sorted = block.sort_values("odds", ascending=False)

            best_row = block_sorted.iloc[0]
            best_odds = format_odds(best_row["odds"])
            best_book = best_row["book"]

            # Outcome label
            outcome = side
            if market in ("totals", "spreads") and not pd.isna(line):
                # match screenshot style (Over 2.5, Home -1.0 etc.)
                sign = ""
                if market == "spreads":
                    # spreads commonly shown with sign
                    lv = float(line)
                    sign = "+" if lv > 0 else ""
                outcome = f"{side} {sign}{float(line):g}"

            pills = []
            for _, r in block_sorted.iterrows():
                book = r["book"]
                odds = format_odds(r["odds"])
                is_best = (book == best_book and odds == best_odds)
                pills.append(
                    f"<span class='pill {'bestpill' if is_best else ''}'>{html.escape(book)} @ {html.escape(odds)}</span>"
                )

            rows_html.append(f"""
<tr>
  <td style="width:18%;font-weight:750;">{html.escape(outcome)}</td>
  <td style="width:18%;">
    <div class="best">{html.escape(best_odds)} <span style="color:var(--muted);font-weight:650;">@</span> {html.escape(best_book)}</div>
  </td>
  <td>
    <div class="pills">{''.join(pills)}</div>
  </td>
</tr>
""")

        panel = f"""
<div class="panel">
  <div class="panel-h">{html.escape(market_label(market))}</div>
  <table>
    <thead>
      <tr>
        <th style="width:18%;">Outcome</th>
        <th style="width:18%;">Best price</th>
        <th>All books (sorted)</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows_html) if rows_html else "<tr><td colspan='3' class='subtle'>No odds.</td></tr>"}
    </tbody>
  </table>
</div>
"""
        out.append(panel)

    return "".join(out)

def render_fixture_page(match_df: pd.DataFrame, home: str, away: str, kickoff: str, updated: str) -> str:
    body = f"""
<div class="navtop"><a href="index.html">← All fixtures</a></div>
<h1>{html.escape(home)} vs {html.escape(away)}</h1>
<div class="meta">Kickoff (UTC): {html.escape(kickoff)} · Updated: {html.escape(updated)}</div>
{render_market_panels(match_df)}
"""
    return page_shell(f"{home} vs {away}", body)

# ================= MAIN =================

def main():
    BASE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sport_groups = {}
    updated_stamp = now_iso()

    for sport_name, leagues in SPORTS.items():
        for league_slug, api_key in leagues.items():
            data = fetch(api_key)
            df = flatten(data, sport_name)
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
