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
+ per-fixture pages (FIXES 404s)
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
    "NFL": {
        "nfl": "americanfootball_nfl",
    },
    "NBA": {
        "nba": "basketball_nba",
    },
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
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

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
            book = b.get("title")
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

# ================= HTML =================

def card(title, subtitle, href):
    return f"""
<a href="{href}" style="text-decoration:none;color:{TXT};">
  <div style="background:#111827;border:1px solid #1F2937;border-radius:14px;padding:16px;margin:12px 0;">
    <div style="font-size:18px;font-weight:700;">{html.escape(title)}</div>
    <div style="opacity:0.7;margin-top:4px;">{html.escape(subtitle)}</div>
  </div>
</a>
"""

def render_index(groups):
    sections = []

    for sport, leagues in groups.items():
        blocks = []
        for league_key, league_name in leagues:
            blocks.append(card(
                league_name,
                "Open fixtures",
                f"{league_key}/index.html"
            ))

        sections.append(f"""
<h2 style="margin-top:32px;">{sport}</h2>
{''.join(blocks)}
""")

    return f"""<!doctype html>
<html>
<body style="background:{THEME_BG};color:{TXT};font-family:Inter,system-ui;padding:24px;">
  <h1>Odds Checker</h1>
  <p style="opacity:0.8;">Updated: {now_iso()}</p>
  {''.join(sections)}
</body>
</html>
"""

def render_fixture_page(df, home, away, kickoff, league_slug):
    rows = []

    for market in df["market"].unique():
        block = df[df["market"] == market]

        table_rows = []
        for _, r in block.iterrows():
            label = r["side"]
            if r["line"] is not None:
                label += f" ({r['line']})"

            table_rows.append(f"""
<tr>
<td>{r['book']}</td>
<td>{label}</td>
<td>{r['odds']}</td>
</tr>
""")

        rows.append(f"""
<h3 style="margin-top:28px;">{market.upper()}</h3>
<table style="width:100%;border-collapse:collapse;">
<tr><th align="left">Book</th><th align="left">Outcome</th><th align="left">Odds</th></tr>
{''.join(table_rows)}
</table>
""")

    return f"""<!doctype html>
<html>
<body style="background:{THEME_BG};color:{TXT};font-family:Inter,system-ui;padding:24px;">
<a href="index.html" style="color:#93C5FD;">← Back to league</a>
<h1>{home} vs {away}</h1>
<p style="opacity:0.7;">Kickoff: {kickoff} UTC</p>
{''.join(rows)}
</body>
</html>
"""

# ================= MAIN =================

def main():
    BASE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sport_groups = {}

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
                    f"{g['kickoff']} UTC",
                    slug
                ))

                match_df = df[df["event_id"] == g["event_id"]]
                fixture_html = render_fixture_page(
                    match_df,
                    g["home"],
                    g["away"],
                    g["kickoff"],
                    league_slug
                )

                (league_dir / slug).write_text(fixture_html, encoding="utf-8")

            league_html = f"""<!doctype html>
<html>
<body style="background:{THEME_BG};color:{TXT};font-family:Inter,system-ui;padding:24px;">
<a href="../index.html" style="color:#93C5FD;">← All sports</a>
<h1>{league_slug.replace('_',' ').title()} Odds Checker</h1>
{''.join(rows)}
</body>
</html>
"""
            (league_dir / "index.html").write_text(league_html, encoding="utf-8")

            sport_groups.setdefault(sport_name, []).append(
                (league_slug, league_slug.replace("_", " ").title())
            )

    (BASE_OUTPUT_DIR / "index.html").write_text(
        render_index(sport_groups),
        encoding="utf-8"
    )

if __name__ == "__main__":
    main()
