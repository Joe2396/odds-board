# -*- coding: utf-8 -*-
"""
Multi-Sport Odds Checker (UK / EU / BOTH) + Corners (Soccer)

Sports:
- Soccer (EPL, La Liga, Bundesliga, Serie A, UCL)
- NFL
- NBA

Outputs (by bookmaker group):
data/auto/odds_checker_uk/index.html
data/auto/odds_checker_eu/index.html
data/auto/odds_checker_both/index.html
+ per-league index pages
+ per-fixture pages (match pages)

NEW:
- Soccer “Total Corners (Over/Under)” via per-event endpoint:
  market key: alternate_totals_corners
  (only added when available for that game)

Run:
  python generate_odds_checker.py --group BOTH
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

# Per your preference: hard-code API key (no secrets/env)
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

# Fetch both UK + EU so we can filter into UK/EU/BOTH builds
REGIONS = "uk,eu"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

THEME_BG = "#0F1621"
TXT = "#E2E8F0"

POPULAR_SOCCER_SPREADS = {-1.0, 0.0, 1.0}

# Corners config (soccer only)
CORNERS_MARKET = "alternate_totals_corners"   # Total corners O/U
CORNERS_EVENT_CAP_PER_LEAGUE = 2            # keep API usage sane

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
    """
    Bulk endpoint for main markets.
    """
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

def fetch_event_odds(sport_key: str, event_id: str, markets: str):
    """
    Per-event endpoint (needed for additional markets like corners).
    """
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events/{event_id}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": markets,
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": DATE_FORMAT,
    }
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        # Keep this as WARN (coverage varies, some events may not have corners)
        print(f"[WARN] event_odds {sport_key} {event_id}: {r.status_code}")
        return None
    return r.json()

# ================= DATA BUILD =================

def flatten(data, sport_name, allowed_keys: set):
    """
    Flattens odds into rows, filtering bookmakers by KEY using allowed_keys.
    Supports:
      - h2h
      - totals
      - spreads
      - alternate_totals_corners (mapped internally to totals_corners)
    """
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
                continue

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
                    internal_market = mkey  # we may remap for nicer labels

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

                    elif mkey == "alternate_totals_corners":
                        # Total corners O/U
                        internal_market = "totals_corners"
                        if "over" in name.lower():
                            side = "Over"
                        elif "under" in name.lower():
                            side = "Under"
                        else:
                            continue
                        if point is None:
                            continue
                        line = float(point)

                    # extra safety: do not allow rows without side
                    if side is None:
                        continue

                    rows.append({
                        "sport": sport_name,
                        "event_id": gid,
                        "home": home,
                        "away": away,
                        "kickoff": kickoff,
                        "market": internal_market,  # h2h / totals / spreads / totals_corners
                        "side": side,
                        "line": line,
                        "book": book,
                        "odds": float(price),
                    })

    return pd.DataFrame(rows)

# ================= HTML UI =================

def page_shell(title: str, body_html: str, group: str) -> str:
    group = (group or "BOTH").upper()

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

  /* top bar */
  .topbar {{
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 10px;
    margin-bottom: 10px;
  }}
  .topbar label {{
    color: var(--muted);
    font-weight: 650;
    font-size: 14px;
  }}
  .topbar select {{
    background: #0B1220;
    color: var(--fg);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 8px 10px;
    font-weight: 700;
    outline: none;
  }}

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
    <div class="topbar">
      <label for="groupSelect">Bookmakers</label>
      <select id="groupSelect">
        <option value="BOTH">BOTH</option>
        <option value="UK">UK</option>
        <option value="EU">EU</option>
      </select>
    </div>

    {body_html}
  </div>

<script>
(function() {{
  var current = "{group}";
  var sel = document.getElementById("groupSelect");
  if (sel) sel.value = current;

  function swapGroup(target) {{
    var oldPath = window.location.pathname;
    var newPath = oldPath.replace(/odds_checker_(uk|eu|both)/i, "odds_checker_" + target.toLowerCase());
    if (newPath === oldPath) return;
    window.location.pathname = newPath;
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

def card(title, subtitle, href):
    return f"""
<a href="{href}">
  <div class="card">
    <div class="card-title">{html.escape(title)}</div>
    <div class="card-sub">{html.escape(subtitle)}</div>
  </div>
</a>
"""

def render_root_index(groups, group):
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
    return page_shell("Odds Checker", body, group)

def market_label(market_key: str) -> str:
    if market_key == "h2h":
        return "Match Result (1X2)"
    if market_key == "totals":
        return "Totals (Over/Under)"
    if market_key == "totals_corners":
        return "Total Corners (Over/Under)"
    if market_key == "spreads":
        return "Spreads (Handicap)"
    return market_key.upper()

def format_odds(x: float) -> str:
    try:
        return f"{float(x):.2f}".rstrip("0").rstrip(".")
    except Exception:
        return str(x)

def render_market_panels(match_df: pd.DataFrame) -> str:
    if match_df.empty:
        return "<div class='meta'>No odds available.</div>"

    out = []
    market_order = ["h2h", "totals", "totals_corners", "spreads"]
    markets = [m for m in market_order if m in set(match_df["market"].tolist())]
    for m in sorted(set(match_df["market"].tolist())):
        if m not in markets:
            markets.append(m)

    for market in markets:
        dfm = match_df[match_df["market"] == market].copy()
        if dfm.empty:
            continue

        if market == "h2h":
            side_order = ["Home", "Draw", "Away"]
        elif market in ("totals", "totals_corners"):
            side_order = ["Over", "Under"]
        else:
            side_order = ["Home", "Away"]

        combos = dfm[["line", "side"]].drop_duplicates()

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

            block_sorted = block.sort_values("odds", ascending=False)

            best_row = block_sorted.iloc[0]
            best_odds = format_odds(best_row["odds"])
            best_book = best_row["book"]

            outcome = side
            if market in ("totals", "spreads", "totals_corners") and not pd.isna(line):
                sign = ""
                if market == "spreads":
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

def render_fixture_page(match_df: pd.DataFrame, home: str, away: str, kickoff: str, updated: str, group: str) -> str:
    body = f"""
<div class="navtop"><a href="index.html">← All fixtures</a></div>
<h1>{html.escape(home)} vs {html.escape(away)}</h1>
<div class="meta">Kickoff (UTC): {html.escape(kickoff)} · Updated: {html.escape(updated)}</div>
{render_market_panels(match_df)}
"""
    return page_shell(f"{home} vs {away}", body, group)

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

    base_output_dir = Path(f"data/auto/odds_checker_{args.group.lower()}")
    base_output_dir.mkdir(parents=True, exist_ok=True)

    sport_groups = {}
    updated_stamp = now_iso()

    for sport_name, leagues in SPORTS.items():
        for league_slug, api_sport_key in leagues.items():
            data = fetch(api_sport_key)
            df = flatten(data, sport_name, allowed_keys)

            if df.empty:
                continue

            # --- Corners: soccer only, per-event odds endpoint ---
            # Only attempt if we already have some fixtures from the bulk call
            if sport_name == "Soccer":
                # Limit calls per league to keep hourly usage manageable
                event_ids = df["event_id"].dropna().unique().tolist()[:CORNERS_EVENT_CAP_PER_LEAGUE]
                corners_frames = []
                for eid in event_ids:
                    ev = fetch_event_odds(api_sport_key, eid, markets=CORNERS_MARKET)
                    if not ev:
                        continue
                    # event endpoint returns a single event object -> pass as list
                    cdf = flatten([ev], sport_name, allowed_keys)
                    if not cdf.empty:
                        corners_frames.append(cdf)
                if corners_frames:
                    df = pd.concat([df] + corners_frames, ignore_index=True)

            league_dir = base_output_dir / league_slug
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
                    updated=updated_stamp,
                    group=args.group
                )
                (league_dir / slug).write_text(fixture_html, encoding="utf-8")

            league_body = f"""
<div class="navtop"><a href="../index.html">← All sports</a></div>
<h1>{html.escape(league_slug.replace('_',' ').title())}</h1>
<div class="meta">Updated: {updated_stamp}</div>
<div class="gridcards">{''.join(rows)}</div>
"""
            (league_dir / "index.html").write_text(
                page_shell(f"{league_slug} fixtures", league_body, args.group),
                encoding="utf-8"
            )

            sport_groups.setdefault(sport_name, []).append(
                (league_slug, league_slug.replace("_", " ").title())
            )

    (base_output_dir / "index.html").write_text(
        render_root_index(sport_groups, args.group),
        encoding="utf-8"
    )

if __name__ == "__main__":
    main()

