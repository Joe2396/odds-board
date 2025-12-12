# -*- coding: utf-8 -*-
"""
EPL Odds Checker (1X2 + Totals + Spreads)
Outputs fixture index + per-fixture pages.
"""

import html
from datetime import datetime, timezone
from pathlib import Path
import requests
import pandas as pd

# ---------------- CONFIG --------------------

API_KEY = "8e8a4a2421e95ad2fb0df450c88ef6c6"    # your API key
LEAGUES = {
    "epl": "soccer_epl",
    "championship": "soccer_england_efl_championship",
    "la_liga": "soccer_spain_la_liga",
    "bundesliga": "soccer_germany_bundesliga",
    "serie_a": "soccer_italy_serie_a",
}

REGIONS = "eu"  # EU books (you asked for this)
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

BASE_OUTPUT_DIR = Path("data/auto/odds_checker")
THEME_BG = "#0F1621"
TXT = "#E2E8F0"

# Only show these spread lines (most popular handicap lines)
POPULAR_SPREAD_LINES = {-1.0, 0.0, 1.0}

# ---------------- HELPERS --------------------

def tidy_book(name: str) -> str:
    """Normalise bookmaker names a bit."""
    if not name:
        return "Unknown"
    mapping = {
        "Sky Bet": "SkyBet",
        "Betfair": "Betfair Sportsbook",
        "Paddy Power": "PaddyPower",
    }
    return mapping.get(name, name)

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

def fetch(league_key: str, mkts: str):
    url = f"https://api.the-odds-api.com/v4/sports/{league_key}/odds"

    params = dict(
        apiKey=API_KEY,
        regions=REGIONS,
        markets=mkts,          # ✅ FIXED
        oddsFormat=ODDS_FORMAT,
        dateFormat=DATE_FORMAT,
    )

    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise SystemExit(f"HTTP {r.status_code}: {r.text}")
    return r.json()

    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
    except Exception as e:
        print(f"[fetch] Request error for markets={markets}: {e}")
        return []
    if r.status_code != 200:
        print(f"[fetch] HTTP {r.status_code} for markets={markets}: {r.text}")
        return []
    try:
        return r.json()
    except Exception as e:
        print(f"[fetch] JSON decode error for markets={markets}: {e}")
        return []

# ---------------- DATAFRAME BUILDERS --------------------

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
                    name_l = name.lower()
                    if home and name_l == home.lower():
                        side = "Home"
                    elif away and name_l == away.lower():
                        side = "Away"
                    elif name_l == "draw":
                        side = "Draw"
                    else:
                        continue
                    rows.append(
                        {
                            "event_id": gid,
                            "time": t,
                            "home": home,
                            "away": away,
                            "book": book,
                            "market": "h2h",
                            "side": side,
                            "odds": float(price),
                        }
                    )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df[(df["odds"] >= 1.01) & (df["odds"] <= 1000)]
    return df

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
                    rows.append(
                        {
                            "event_id": gid,
                            "time": t,
                            "home": home,
                            "away": away,
                            "book": book,
                            "market": "totals",
                            "line": float(point),
                            "side": name,
                            "odds": float(price),
                        }
                    )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df[(df["odds"] >= 1.01) & (df["odds"] <= 1000)]
    return df

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
                    line = o.get("point")
                    price = o.get("price")
                    if line is None or price is None:
                        continue
                    try:
                        line_f = float(line)
                    except (TypeError, ValueError):
                        continue
                    # only keep our "popular" handicap lines
                    if line_f not in POPULAR_SPREAD_LINES:
                        continue
                    name_l = name.lower()
                    if home and name_l == home.lower():
                        side = "Home"
                    elif away and name_l == away.lower():
                        side = "Away"
                    else:
                        continue
                    rows.append(
                        {
                            "event_id": gid,
                            "time": t,
                            "home": home,
                            "away": away,
                            "book": book,
                            "market": "spreads",
                            "line": line_f,
                            "side": side,
                            "odds": float(price),
                        }
                    )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df[(df["odds"] >= 1.01) & (df["odds"] <= 1000)]
    return df

# ---------------- RENDER HELPERS --------------------

def chips(items, best_odds):
    """Render bookmaker @ odds pills, highlighting the best."""
    pills = []
    for (bk, od) in items:
        is_best = (od == best_odds)
        base = (
            "background:#10B98122;border:1px solid #10B98155;"
            if is_best
            else "background:#111827;border:1px solid #1F2937;"
        )
        pills.append(
            f"<span style='{base}border-radius:10px;padding:2px 8px;"
            f"display:inline-block;margin:2px 6px 2px 0;'>{html.escape(bk)} @ {od}</span>"
        )
    return "".join(pills)

def render_fixture_page(fx, h2h, totals, spreads):
    ts = now_iso()
    parts = []

    # HTML head
    parts.append(
        "<!doctype html><html><head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "</head><body>"
    )

    # Header
    parts.append(
        f"""
    <div style="color:{TXT};background:{THEME_BG};padding:24px;
                font-family:Inter,system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
      <a href="index.html" style="color:#93C5FD;text-decoration:none;">← All fixtures</a>
      <h1 style="margin:8px 0 0 0;">{html.escape(fx['home'])} vs {html.escape(fx['away'])}</h1>
      <p style="opacity:0.8;margin:6px 0 18px 0;">
        Kickoff (UTC): {html.escape(fx['time'])} · Updated: {ts}
      </p>
    """
    )

    # ----- Match Result (1X2) -----
    if not h2h.empty:
        parts.append(
            """
        <h2 style="margin:8px 0 8px 0;">Match Result (1X2)</h2>
        <div style="overflow:auto;border:1px solid #1F2937;border-radius:12px;margin-bottom:20px;">
          <table style="width:100%;border-collapse:collapse;min-width:900px;">
            <thead>
              <tr style="background:#111827;">
                <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Outcome</th>
                <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Best price</th>
                <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">All books (sorted)</th>
              </tr>
            </thead>
            <tbody>
        """
        )
        for side in ["Home", "Draw", "Away"]:
            sub = h2h[h2h["side"] == side].sort_values("odds", ascending=False)
            if sub.empty:
                continue
            best = sub.iloc[0]
            all_pairs = sub[["book", "odds"]].values.tolist()
            parts.append(
                f"""
              <tr>
                <td style="padding:12px;">{side}</td>
                <td style="padding:12px;"><strong>{best['odds']}</strong> @ {html.escape(str(best['book']))}</td>
                <td style="padding:12px;max-width:720px;">{chips(all_pairs, best['odds'])}</td>
              </tr>
            """
            )
        parts.append("</tbody></table></div>")

    # ----- Totals -----
    if not totals.empty:
        parts.append(
            """
        <h2 style="margin:8px 0 8px 0;">Total Goals (Over/Under)</h2>
        <div style="border:1px solid #1F2937;border-radius:12px;padding:12px;">
        """
        )
        for line, sub in totals.groupby("line"):
            sub = sub.sort_values("odds", ascending=False)
            over = sub[sub["side"] == "Over"][["book", "odds"]].values.tolist()
            under = sub[sub["side"] == "Under"][["book", "odds"]].values.tolist()
            best_over = over[0][1] if over else None
            best_under = under[0][1] if under else None
            parts.append(
                f"""
          <div style="margin:12px 0 18px 0;">
            <h3 style="margin:0 0 8px 0;">Total Goals {line:+.1f}</h3>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
              <div>
                <div style="opacity:0.8;margin-bottom:6px;">Over</div>
                {chips(over, best_over) if over else "<em>No prices</em>"}
              </div>
              <div>
                <div style="opacity:0.8;margin-bottom:6px;">Under</div>
                {chips(under, best_under) if under else "<em>No prices</em>"}
              </div>
            </div>
          </div>
        """
            )
        parts.append("</div>")

    # ----- Spreads -----
    if not spreads.empty:
        parts.append(
            """
        <h2 style="margin:8px 0 8px 0;">Handicap (Spreads)</h2>
        <div style="border:1px solid #1F2937;border-radius:12px;padding:12px;">
        """
        )
        for line, sub in spreads.groupby("line"):
            sub = sub.sort_values("odds", ascending=False)
            home = sub[sub["side"] == "Home"][["book", "odds"]].values.tolist()
            away = sub[sub["side"] == "Away"][["book", "odds"]].values.tolist()
            best_home = home[0][1] if home else None
            best_away = away[0][1] if away else None
            parts.append(
                f"""
          <div style="margin:12px 0 18px 0;">
            <h3 style="margin:0 0 8px 0;">Line {line:+.1f}</h3>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
              <div>
                <div style="opacity:0.8;margin-bottom:6px;">Home</div>
                {chips(home, best_home) if home else "<em>No prices</em>"}
              </div>
              <div>
                <div style="opacity:0.8;margin-bottom:6px;">Away</div>
                {chips(away, best_away) if away else "<em>No prices</em>"}
              </div>
            </div>
          </div>
        """
            )
        parts.append("</div>")

    parts.append("</div></body></html>")
    return "".join(parts)

def main():
    BASE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_h2h = []
    all_totals = []
    all_spreads = []

    # --------------------------------------------------
    # FETCH DATA FOR EACH LEAGUE
    # --------------------------------------------------
    for league_name, league_key in LEAGUES.items():
        print(f"\n=== {league_name.upper()} ===")

        print("Fetching H2H…")
        raw = fetch(league_key, "h2h")
        df_h = df_h2h(raw)
        if not df_h.empty:
            df_h["league"] = league_name
            all_h2h.append(df_h)

        print("Fetching Totals…")
        raw = fetch(league_key, "totals")
        df_t = df_totals(raw)
        if not df_t.empty:
            df_t["league"] = league_name
            all_totals.append(df_t)

        print("Fetching Spreads…")
        raw = fetch(league_key, "spreads")
        df_s = df_spreads(raw)
        if not df_s.empty:
            df_s["league"] = league_name
            all_spreads.append(df_s)

    if not all_h2h:
        print("No data returned at all. Exiting.")
        return

    df_h2h_all = pd.concat(all_h2h, ignore_index=True)
    df_totals_all = pd.concat(all_totals, ignore_index=True) if all_totals else pd.DataFrame()
    df_spreads_all = pd.concat(all_spreads, ignore_index=True) if all_spreads else pd.DataFrame()

    # --------------------------------------------------
    # FIXTURE PAGES (PER MATCH)
    # --------------------------------------------------
    all_games = (
        df_h2h_all[["event_id", "time", "home", "away", "league"]]
        .drop_duplicates()
        .sort_values("time")
    )

    for _, fx in all_games.iterrows():
        league_dir = BASE_OUTPUT_DIR / fx["league"]
        league_dir.mkdir(parents=True, exist_ok=True)

        h = df_h2h_all[df_h2h_all["event_id"] == fx.event_id]
        t = df_totals_all[df_totals_all["event_id"] == fx.event_id] if not df_totals_all.empty else df_totals_all
        s = df_spreads_all[df_spreads_all["event_id"] == fx.event_id] if not df_spreads_all.empty else df_spreads_all

        html_out = render_fixture_page(fx, h, t, s)

        slug = f"{fx['home'].lower().replace(' ','-')}-vs-{fx['away'].lower().replace(' ','-')}.html"
        (league_dir / slug).write_text(html_out, encoding="utf-8")

    print(f"Wrote {len(all_games)} fixture pages")

    # --------------------------------------------------
    # INDEX PAGES (DARK CARD LAYOUT PER LEAGUE)
    # --------------------------------------------------
    for league_name in LEAGUES.keys():
        league_games = all_games[all_games["league"] == league_name]
        if league_games.empty:
            continue

        index_html = []
        current_date = None

        for _, fx in league_games.iterrows():
            dt = fx["time"][:10]  # YYYY-MM-DD
            if dt != current_date:
                current_date = dt
                index_html.append(f"<h2 style='margin:24px 0 8px 0;'>{dt}</h2>")

            slug = f"{fx['home'].lower().replace(' ','-')}-vs-{fx['away'].lower().replace(' ','-')}.html"

            index_html.append(f"""
            <a href="{slug}" style="text-decoration:none;color:{TXT};">
              <div style="
                background:#111827;
                border:1px solid #1F2937;
                border-radius:14px;
                padding:16px;
                margin:12px 0;
                display:flex;
                justify-content:space-between;
                align-items:center;
              ">
                <div>
                  <div style="font-size:18px;font-weight:600;">{html.escape(fx['home'])}</div>
                  <div style="opacity:0.7;">vs</div>
                  <div style="font-size:18px;font-weight:600;">{html.escape(fx['away'])}</div>
                </div>
                <div style="opacity:0.6;font-size:14px;">
                  {fx['time']} UTC
                </div>
              </div>
            </a>
            """)

        league_dir = BASE_OUTPUT_DIR / league_name
        league_dir.mkdir(parents=True, exist_ok=True)

        (league_dir / "index.html").write_text(
            f"""<!doctype html>
<html>
<body style="background:{THEME_BG};color:{TXT};font-family:Inter,system-ui,Roboto;padding:24px;">
<h1>{league_name.replace('_',' ').title()} Odds Checker</h1>
<p>Updated: {now_iso()}</p>
{''.join(index_html)}
</body>
</html>
""",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()



