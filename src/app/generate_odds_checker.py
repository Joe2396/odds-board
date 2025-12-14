# -*- coding: utf-8 -*-
"""
Multi-Sport Odds Checker (Soccer + NFL + NBA)
Outputs:
  data/auto/odds_checker/index.html
  data/auto/odds_checker/<league>/index.html
  data/auto/odds_checker/<league>/<fixture>.html
"""

import html
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# ================= CONFIG =================

API_KEY = "8e8a4a2421e95ad2fb0df450c88ef6c6"

LEAGUES = {
    "epl": "soccer_epl",
    "la_liga": "soccer_spain_la_liga",
    "bundesliga": "soccer_germany_bundesliga",
    "serie_a": "soccer_italy_serie_a",
    "ucl": "soccer_uefa_champs_league",
    "nfl": "americanfootball_nfl",
    "nba": "basketball_nba",  # ✅ NEW
}

REGIONS = "eu"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

BASE_OUTPUT_DIR = Path("data/auto/odds_checker")

THEME_BG = "#0F1621"
TXT = "#E2E8F0"

# Allow ALL spread lines (important for NFL/NBA)
POPULAR_SPREAD_LINES = None

ODDS_MIN = 1.01
ODDS_MAX = 1000.0

# ================= HELPERS =================

def tidy_book(name: str) -> str:
    if not name:
        return "Unknown"
    MAP = {
        "Sky Bet": "SkyBet",
        "Betfair": "Betfair Sportsbook",
        "Paddy Power": "PaddyPower",
    }
    return MAP.get(name, name)

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

def slugify_team(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^\w\s-]", " ", s, flags=re.UNICODE)
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "team"

def fixture_slug(home: str, away: str) -> str:
    return f"{slugify_team(home)}-vs-{slugify_team(away)}.html"

# ================= API =================

def fetch(league_key: str, mkts: str):
    url = f"https://api.the-odds-api.com/v4/sports/{league_key}/odds"
    params = dict(
        apiKey=API_KEY,
        regions=REGIONS,
        markets=mkts,
        oddsFormat=ODDS_FORMAT,
        dateFormat=DATE_FORMAT,
    )
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"{league_key} {mkts} HTTP {r.status_code}: {r.text}")
    return r.json()

# ================= DATAFRAMES =================

def df_h2h(data):
    rows = []
    for g in data:
        gid = g.get("id")
        t = g.get("commence_time")
        home = g.get("home_team")
        away = g.get("away_team")

        for b in g.get("bookmakers", []):
            book = tidy_book(b.get("title"))
            for m in b.get("markets", []):
                if m.get("key") != "h2h":
                    continue
                for o in m.get("outcomes", []):
                    name = (o.get("name") or "").strip()
                    price = o.get("price")
                    if price is None:
                        continue

                    nlow = name.lower()
                    if home and nlow == home.lower():
                        side = "Home"
                    elif away and nlow == away.lower():
                        side = "Away"
                    elif nlow == "draw":
                        side = "Draw"
                    else:
                        continue

                    odds = float(price)
                    if not (ODDS_MIN <= odds <= ODDS_MAX):
                        continue

                    rows.append(dict(
                        event_id=gid,
                        time=t,
                        home=home,
                        away=away,
                        book=book,
                        market="h2h",
                        side=side,
                        odds=odds,
                    ))
    return pd.DataFrame(rows)

def df_totals(data):
    rows = []
    for g in data:
        gid = g.get("id")
        t = g.get("commence_time")
        home = g.get("home_team")
        away = g.get("away_team")

        for b in g.get("bookmakers", []):
            book = tidy_book(b.get("title"))
            for m in b.get("markets", []):
                if m.get("key") != "totals":
                    continue
                for o in m.get("outcomes", []):
                    name = (o.get("name") or "").title()
                    point = o.get("point")
                    price = o.get("price")
                    if name not in ("Over", "Under") or point is None or price is None:
                        continue

                    odds = float(price)
                    if not (ODDS_MIN <= odds <= ODDS_MAX):
                        continue

                    rows.append(dict(
                        event_id=gid,
                        time=t,
                        home=home,
                        away=away,
                        book=book,
                        market="totals",
                        line=float(point),
                        side=name,
                        odds=odds,
                    ))
    return pd.DataFrame(rows)

def df_spreads(data):
    rows = []
    for g in data:
        gid = g.get("id")
        t = g.get("commence_time")
        home = g.get("home_team")
        away = g.get("away_team")

        for b in g.get("bookmakers", []):
            book = tidy_book(b.get("title"))
            for m in b.get("markets", []):
                if m.get("key") != "spreads":
                    continue
                for o in m.get("outcomes", []):
                    name = (o.get("name") or "").strip()
                    point = o.get("point")
                    price = o.get("price")
                    if point is None or price is None:
                        continue

                    odds = float(price)
                    if not (ODDS_MIN <= odds <= ODDS_MAX):
                        continue

                    line = float(point)
                    if POPULAR_SPREAD_LINES and line not in POPULAR_SPREAD_LINES:
                        continue

                    nlow = name.lower()
                    if home and nlow == home.lower():
                        side = "Home"
                    elif away and nlow == away.lower():
                        side = "Away"
                    else:
                        continue

                    rows.append(dict(
                        event_id=gid,
                        time=t,
                        home=home,
                        away=away,
                        book=book,
                        market="spreads",
                        line=line,
                        side=side,
                        odds=odds,
                    ))
    return pd.DataFrame(rows)

# ================= HTML HELPERS =================

def chips(items, best):
    out = []
    for bk, od in items:
        is_best = (od == best)
        style = (
            "background:#10B98122;border:1px solid #10B98155;"
            if is_best else
            "background:#111827;border:1px solid #1F2937;"
        )
        out.append(
            f"<span style='{style}border-radius:10px;padding:2px 8px;"
            f"display:inline-block;margin:2px 6px 2px 0;'>"
            f"{html.escape(str(bk))} @ {od}</span>"
        )
    return "".join(out)

# ================= RENDERERS =================

def render_fixture_page(fx, h2h, totals, spreads):
    ts = now_iso()
    parts = [f"""
<!doctype html><html><head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
</head><body>
<div style="color:{TXT};background:{THEME_BG};padding:24px;
font-family:Inter,system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
<a href="index.html" style="color:#93C5FD;text-decoration:none;">← All fixtures</a>
<h1>{html.escape(fx['home'])} vs {html.escape(fx['away'])}</h1>
<p style="opacity:0.8;">Kickoff (UTC): {html.escape(fx['time'])} · Updated: {ts}</p>
"""]

    def render_table(title, headers, rows):
        if not rows:
            return f"<p style='opacity:0.7;'>No {title.lower()} prices.</p>"
        ths = "".join(f"<th style='padding:10px;text-align:left;'>{h}</th>" for h in headers)
        trs = "".join(rows)
        return f"""
<h2>{title}</h2>
<div style="overflow:auto;border:1px solid #1F2937;border-radius:12px;">
<table style="width:100%;border-collapse:collapse;min-width:900px;">
<thead><tr style="background:#111827;">{ths}</tr></thead>
<tbody>{trs}</tbody>
</table>
</div>
"""

    # H2H
    rows = []
    for side in ["Home", "Draw", "Away"]:
        sub = h2h[h2h["side"] == side].sort_values("odds", ascending=False)
        if sub.empty:
            continue
        best = sub.iloc[0]
        rows.append(
            f"<tr><td>{side}</td>"
            f"<td><strong>{best['odds']}</strong> @ {html.escape(best['book'])}</td>"
            f"<td>{chips(sub[['book','odds']].values.tolist(), best['odds'])}</td></tr>"
        )
    parts.append(render_table("Match Result (1X2)", ["Outcome", "Best", "All Books"], rows))

    # Totals
    if not totals.empty:
        for line, sub in totals.groupby("line"):
            rows = []
            for side in ["Over", "Under"]:
                ss = sub[sub["side"] == side].sort_values("odds", ascending=False)
                if ss.empty:
                    continue
                best = ss.iloc[0]
                rows.append(
                    f"<tr><td>{side}</td>"
                    f"<td><strong>{best['odds']}</strong> @ {html.escape(best['book'])}</td>"
                    f"<td>{chips(ss[['book','odds']].values.tolist(), best['odds'])}</td></tr>"
                )
            parts.append(render_table(f"Totals {line}", ["Side", "Best", "All Books"], rows))

    # Spreads
    if not spreads.empty:
        for line, sub in spreads.groupby("line"):
            rows = []
            for side in ["Home", "Away"]:
                ss = sub[sub["side"] == side].sort_values("odds", ascending=False)
                if ss.empty:
                    continue
                best = ss.iloc[0]
                rows.append(
                    f"<tr><td>{side}</td>"
                    f"<td><strong>{best['odds']}</strong> @ {html.escape(best['book'])}</td>"
                    f"<td>{chips(ss[['book','odds']].values.tolist(), best['odds'])}</td></tr>"
                )
            parts.append(render_table(f"Spread {line:+}", ["Side", "Best", "All Books"], rows))

    parts.append("</div></body></html>")
    return "".join(parts)

def render_league_index(name, games):
    items = []
    for _, fx in games.sort_values("time").iterrows():
        items.append(f"""
<a href="{fixture_slug(fx['home'], fx['away'])}" style="color:{TXT};text-decoration:none;">
<div style="background:#111827;border:1px solid #1F2937;border-radius:14px;padding:16px;margin:12px 0;">
<strong>{html.escape(fx['home'])}</strong> vs <strong>{html.escape(fx['away'])}</strong><br>
<span style="opacity:0.7;">{html.escape(fx['time'])} UTC</span>
</div></a>
""")
    return f"""
<!doctype html><html><body style="background:{THEME_BG};color:{TXT};padding:24px;font-family:Inter;">
<a href="../index.html" style="color:#93C5FD;">← All sports</a>
<h1>{name.replace('_',' ').title()} Odds Checker</h1>
{''.join(items)}
</body></html>
"""

def render_root_index(leagues):
    return f"""
<!doctype html><html><body style="background:{THEME_BG};color:{TXT};padding:24px;font-family:Inter;">
<h1>Odds Checker</h1>
<p style="opacity:0.8;">Updated: {now_iso()}</p>
{''.join(
    f"<a href='{l}/index.html' style='color:{TXT};text-decoration:none;'><div style='background:#111827;padding:16px;border-radius:14px;margin:12px 0;'>{l.replace('_',' ').title()}</div></a>"
    for l in leagues
)}
</body></html>
"""

# ================= MAIN =================

def main():
    BASE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_h2h, all_totals, all_spreads = [], [], []

    for league, key in LEAGUES.items():
        try:
            raw = fetch(key, "h2h")
            h = df_h2h(raw)
            if not h.empty:
                h["league"] = league
                all_h2h.append(h)

            raw = fetch(key, "totals")
            t = df_totals(raw)
            if not t.empty:
                t["league"] = league
                all_totals.append(t)

            raw = fetch(key, "spreads")
            s = df_spreads(raw)
            if not s.empty:
                s["league"] = league
                all_spreads.append(s)

        except Exception as e:
            print(f"[SKIP] {league}: {e}")

    if not all_h2h:
        return

    df_h2h_all = pd.concat(all_h2h)
    df_totals_all = pd.concat(all_totals) if all_totals else pd.DataFrame()
    df_spreads_all = pd.concat(all_spreads) if all_spreads else pd.DataFrame()

    games = df_h2h_all[["event_id","time","home","away","league"]].drop_duplicates()

    written = []
    for league in LEAGUES:
        lg = games[games["league"] == league]
        if lg.empty:
            continue
        out_dir = BASE_OUTPUT_DIR / league
        out_dir.mkdir(parents=True, exist_ok=True)

        for _, fx in lg.iterrows():
            h = df_h2h_all[df_h2h_all["event_id"] == fx.event_id]
            t = df_totals_all[df_totals_all["event_id"] == fx.event_id] if not df_totals_all.empty else pd.DataFrame()
            s = df_spreads_all[df_spreads_all["event_id"] == fx.event_id] if not df_spreads_all.empty else pd.DataFrame()
            (out_dir / fixture_slug(fx["home"], fx["away"])).write_text(
                render_fixture_page(fx, h, t, s), encoding="utf-8"
            )

        (out_dir / "index.html").write_text(render_league_index(league, lg), encoding="utf-8")
        written.append(league)

    (BASE_OUTPUT_DIR / "index.html").write_text(render_root_index(written), encoding="utf-8")

if __name__ == "__main__":
    main()

