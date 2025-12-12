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
    "championship": "soccer_england_championship",
    "la_liga": "soccer_spain_la_liga",
    "bundesliga": "soccer_germany_bundesliga",
    "serie_a": "soccer_italy_serie_a",
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

def fetch(markets: str):
    """Call The Odds API for the given markets string (e.g. 'h2h', 'totals', 'spreads')."""
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"
    params = dict(
        apiKey=API_KEY,
        regions=REGIONS,
        markets=markets,
        oddsFormat=ODDS_FORMAT,
        dateFormat=DATE_FORMAT,
    )
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

# ---------------- MAIN GENERATION --------------------

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching H2H…")
    raw_h2h = fetch("h2h")
    df1 = df_h2h(raw_h2h)

    print("Fetching Totals…")
    raw_totals = fetch("totals")
    df2 = df_totals(raw_totals)

    print("Fetching Spreads…")
    raw_spreads = fetch("spreads")
    df3 = df_spreads(raw_spreads)

    if df1.empty:
        print("No H2H data returned; nothing to write.")
        return

    all_games = df1[["event_id", "time", "home", "away"]].drop_duplicates()

    # Fixture pages
    for _, fx in all_games.iterrows():
        h = df1[df1["event_id"] == fx.event_id]
        t = df2[df2["event_id"] == fx.event_id] if not df2.empty else df2
        s = df3[df3["event_id"] == fx.event_id] if not df3.empty else df3
        html_out = render_fixture_page(fx, h, t, s)
        slug = f"{fx['home'].lower().replace(' ', '-')}-vs-{fx['away'].lower().replace(' ', '-')}.html"
        fn = OUTPUT_DIR / slug
        fn.write_text(html_out, encoding="utf-8")

    print(f"Wrote {len(all_games)} fixture pages")

    # Index page with dark cards grouped by date
    index_html = []
    current_date = None
    for _, fx in all_games.sort_values("time").iterrows():
        dt = (fx["time"] or "")[:10]  # YYYY-MM-DD
        if dt != current_date:
            current_date = dt
            index_html.append("<h2 style='margin:18px 0 10px 0;'>{}</h2>".format(dt))

        slug = f"{fx['home'].lower().replace(' ', '-')}-vs-{fx['away'].lower().replace(' ', '-')}.html"
        index_html.append(
            f"""
    <a href="{slug}" style="text-decoration:none;color:{TXT};">
      <div style="background:#111827;border:1px solid #1F2937;border-radius:14px;
                  padding:16px;margin:12px 0;display:flex;justify-content:space-between;
                  align-items:center;gap:10px;">
        <div>
          <div style="font-size:18px;font-weight:600;">{html.escape(fx['home'])}</div>
          <div style="opacity:0.8;">vs</div>
          <div style="font-size:18px;font-weight:600;">{html.escape(fx['away'])}</div>
        </div>
        <div style="opacity:0.7;white-space:nowrap;">{fx['time']} UTC</div>
      </div>
    </a>
    """
        )

    index_full = (
        "<!doctype html><html><head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "</head><body "
        f"style=\"background:{THEME_BG};color:{TXT};font-family:Inter,system-ui,Roboto;padding:24px;\">"
        "<h1 style='margin:0 0 6px 0;'>EPL Odds Checker</h1>"
        f"<p style='opacity:0.8;margin:0 0 16px 0;'>Click a fixture to view Match Result, Totals, and Spreads. "
        f"Updated: {now_iso()}</p>"
        f"{''.join(index_html)}"
        "</body></html>"
    )

    (OUTPUT_DIR / "index.html").write_text(index_full, encoding="utf-8")
    print("Index written.")

if __name__ == "__main__":
    main()

