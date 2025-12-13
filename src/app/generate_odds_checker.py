# -*- coding: utf-8 -*-
"""
BeatTheBooks Odds Checker
- Soccer: multi-league (1X2 + Totals + Spreads)
- NFL: single league (Moneyline + Totals + Spreads)

Outputs:
  data/auto/odds_checker/index.html                     (sport selector landing)
  data/auto/odds_checker/soccer/index.html              (soccer league picker)
  data/auto/odds_checker/soccer/<league>/index.html     (soccer fixtures for league)
  data/auto/odds_checker/soccer/<league>/<fixture>.html (soccer per-fixture)
  data/auto/odds_checker/nfl/index.html                 (nfl fixtures)
  data/auto/odds_checker/nfl/<fixture>.html             (nfl per-fixture)
"""

import html
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# ---------------- CONFIG --------------------

API_KEY = "8e8a4a2421e95ad2fb0df450c88ef6c6"

SOCCER_LEAGUES = {
    "premier_league": "soccer_epl",
    "la_liga": "soccer_spain_la_liga",
    "bundesliga": "soccer_germany_bundesliga",
    "serie_a": "soccer_italy_serie_a",
    "champions_league": "soccer_uefa_champs_league",
}

NFL_SPORT_KEY = "americanfootball_nfl"

REGIONS = "eu"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

BASE_OUTPUT_DIR = Path("data/auto/odds_checker")
THEME_BG = "#0F1621"
TXT = "#E2E8F0"

# Popular spread lines — keep soccer as-is; make NFL reasonable.
POPULAR_SPREAD_LINES_BY_SPORT = {
    "soccer": {-1.0, 0.0, 1.0},
    # NFL commonly centers around 3 and 7. Keep it tidy (you can expand later).
    "nfl": {-7.5, -3.5, 0.0, 3.5, 7.5},
}

# ---------------- HELPERS --------------------

def tidy_book(name: str) -> str:
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

def slugify_team(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^\w\s-]", " ", s, flags=re.UNICODE)  # removes / etc
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "team"

def fixture_slug(home: str, away: str) -> str:
    return f"{slugify_team(home)}-vs-{slugify_team(away)}.html"

def fetch(sport_key: str, mkts: str):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = dict(
        apiKey=API_KEY,
        regions=REGIONS,
        markets=mkts,
        oddsFormat=ODDS_FORMAT,
        dateFormat=DATE_FORMAT,
    )
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"{sport_key} {mkts} HTTP {r.status_code}: {r.text}")
    return r.json()

# ---------------- SPORT HEADER --------------------

def sport_header(active: str, base_prefix: str = "") -> str:
    """
    active: "soccer" or "nfl"
    base_prefix: prefix path from current page to odds_checker root, e.g.
      - on root index: ""
      - on soccer index: "../"
      - on soccer league pages: "../../"
      - on nfl pages: "../"
    """
    def tab(label, href, is_active):
        style = (
            "background:#10B98122;border:1px solid #10B98155;"
            if is_active
            else "background:#111827;border:1px solid #1F2937;"
        )
        return (
            f"<a href='{href}' style='text-decoration:none;color:{TXT};'>"
            f"<span style='{style}border-radius:999px;padding:6px 12px;display:inline-block;margin-right:8px;font-size:13px;'>"
            f"{html.escape(label)}</span></a>"
        )

    soccer_href = f"{base_prefix}soccer/index.html"
    nfl_href = f"{base_prefix}nfl/index.html"

    return f"""
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;">
      {tab("Soccer", soccer_href, active == "soccer")}
      {tab("NFL", nfl_href, active == "nfl")}
    </div>
    """

# ---------------- DF BUILDERS --------------------

def df_h2h(data, *, sport: str):
    """
    Soccer: Home/Away/Draw
    NFL: Home/Away (no Draw)
    """
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
                    home_l = (home or "").lower()
                    away_l = (away or "").lower()

                    if name_l == home_l:
                        side = "Home"
                    elif name_l == away_l:
                        side = "Away"
                    elif sport == "soccer" and name_l == "draw":
                        side = "Draw"
                    else:
                        continue

                    rows.append(
                        dict(
                            event_id=gid,
                            time=t,
                            home=home,
                            away=away,
                            book=book,
                            market="h2h",
                            side=side,
                            odds=float(price),
                        )
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
                    try:
                        line = float(point)
                        odds = float(price)
                    except Exception:
                        continue
                    rows.append(
                        dict(
                            event_id=gid,
                            time=t,
                            home=home,
                            away=away,
                            book=book,
                            market="totals",
                            line=line,
                            side=name,
                            odds=odds,
                        )
                    )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df[(df["odds"] >= 1.01) & (df["odds"] <= 1000)]
    return df

def df_spreads(data, *, sport: str):
    rows = []
    allowed_lines = POPULAR_SPREAD_LINES_BY_SPORT.get(sport, set())

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
                        odds = float(price)
                    except Exception:
                        continue

                    # Keep popular lines only (consistent with your current approach)
                    if allowed_lines and line_f not in allowed_lines:
                        continue

                    name_l = name.lower()
                    if home and name_l == home.lower():
                        side = "Home"
                    elif away and name_l == away.lower():
                        side = "Away"
                    else:
                        continue

                    rows.append(
                        dict(
                            event_id=gid,
                            time=t,
                            home=home,
                            away=away,
                            book=book,
                            market="spreads",
                            line=line_f,
                            side=side,
                            odds=odds,
                        )
                    )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df[(df["odds"] >= 1.01) & (df["odds"] <= 1000)]
    return df

# ---------------- RENDERING --------------------

def chips(items, best):
    out = []
    for (bk, od) in items:
        is_best = (od == best)
        style = (
            "background:#10B98122;border:1px solid #10B98155;"
            if is_best
            else "background:#111827;border:1px solid #1F2937;"
        )
        out.append(
            f"<span style='{style}border-radius:10px;padding:2px 8px;display:inline-block;margin:2px 6px 2px 0;'>"
            f"{html.escape(str(bk))} @ {od}</span>"
        )
    return "".join(out)

def render_fixture_page(fx, h2h_df, totals_df, spreads_df, *, sport: str, back_href: str, base_prefix: str):
    ts = now_iso()

    # Market label + sides list differ by sport
    if sport == "nfl":
        h2h_title = "Moneyline"
        sides = ["Home", "Away"]
    else:
        h2h_title = "Match Result (1X2)"
        sides = ["Home", "Draw", "Away"]

    out = []
    out.append(
        f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'></head><body>
<div style="color:{TXT};background:{THEME_BG};padding:24px;font-family:Inter,system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
  {sport_header(sport, base_prefix=base_prefix)}
  <a href="{html.escape(back_href)}" style="color:#93C5FD;text-decoration:none;">← Back</a>
  <h1 style="margin:8px 0 0 0;">{html.escape(fx['home'])} vs {html.escape(fx['away'])}</h1>
  <p style="opacity:0.8;margin:6px 0 18px 0;">Kickoff (UTC): {html.escape(str(fx['time']))} · Updated: {ts}</p>
"""
    )

    # H2H
    if not h2h_df.empty:
        out.append(f"<h2 style='margin:8px 0 8px 0;'>{h2h_title}</h2>")
        out.append(
            """
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
        for side in sides:
            sub = h2h_df[h2h_df["side"] == side].sort_values("odds", ascending=False)
            if sub.empty:
                continue
            best = sub.iloc[0]
            all_pairs = sub[["book", "odds"]].values.tolist()
            out.append(
                f"""
              <tr>
                <td style="padding:12px;border-bottom:1px solid #1F2937;">{side}</td>
                <td style="padding:12px;border-bottom:1px solid #1F2937;"><strong>{best['odds']}</strong> @ {html.escape(str(best['book']))}</td>
                <td style="padding:12px;border-bottom:1px solid #1F2937;">{chips(all_pairs, best['odds'])}</td>
              </tr>
"""
            )
        out.append("</tbody></table></div>")

    # Totals
    if not totals_df.empty:
        out.append("<h2 style='margin:8px 0 8px 0;'>Totals (Over/Under)</h2>")
        out.append("<div style='border:1px solid #1F2937;border-radius:12px;padding:12px;'>")
        for line, sub in totals_df.groupby("line"):
            sub = sub.sort_values("odds", ascending=False)
            over = sub[sub["side"] == "Over"][["book", "odds"]].values.tolist()
            under = sub[sub["side"] == "Under"][["book", "odds"]].values.tolist()
            best_over = over[0][1] if over else None
            best_under = under[0][1] if under else None
            out.append(
                f"""
              <div style="margin:12px 0 18px 0;">
                <h3 style="margin:0 0 8px 0;">Total {float(line):.1f}</h3>
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
        out.append("</div>")

    # Spreads
    if not spreads_df.empty:
        out.append("<h2 style='margin:8px 0 8px 0;'>Spreads</h2>")
        out.append("<div style='border:1px solid #1F2937;border-radius:12px;padding:12px;'>")
        for line, sub in spreads_df.groupby("line"):
            sub = sub.sort_values("odds", ascending=False)
            home = sub[sub["side"] == "Home"][["book", "odds"]].values.tolist()
            away = sub[sub["side"] == "Away"][["book", "odds"]].values.tolist()
            best_home = home[0][1] if home else None
            best_away = away[0][1] if away else None
            out.append(
                f"""
              <div style="margin:12px 0 18px 0;">
                <h3 style="margin:0 0 8px 0;">Line {float(line):+.1f}</h3>
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
        out.append("</div>")

    out.append("</div></body></html>")
    return "".join(out)

def render_soccer_league_index(league_name: str, league_games: pd.DataFrame) -> str:
    index_html = []
    current_date = None

    for _, fx in league_games.sort_values("time").iterrows():
        dt = (fx["time"] or "")[:10]
        if dt != current_date:
            current_date = dt
            index_html.append(f"<h2 style='margin:24px 0 8px 0;'>{html.escape(dt)}</h2>")

        slug = fixture_slug(fx["home"], fx["away"])
        index_html.append(
            f"""
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
    gap:16px;
  ">
    <div>
      <div style="font-size:18px;font-weight:600;">{html.escape(fx['home'])}</div>
      <div style="opacity:0.7;">vs</div>
      <div style="font-size:18px;font-weight:600;">{html.escape(fx['away'])}</div>
    </div>
    <div style="opacity:0.6;font-size:14px;white-space:nowrap;">
      {html.escape(str(fx['time']))} UTC
    </div>
  </div>
</a>
"""
        )

    title = league_name.replace("_", " ").title()
    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="background:{THEME_BG};color:{TXT};font-family:Inter,system-ui,Roboto;padding:24px;">
  {sport_header("soccer", base_prefix="../")}
  <a href="../index.html" style="color:#93C5FD;text-decoration:none;">← Soccer leagues</a>
  <h1 style="margin:10px 0 6px 0;">{html.escape(title)} Odds Checker</h1>
  <p style="opacity:0.8;margin:0 0 16px 0;">Updated: {now_iso()}</p>
  {''.join(index_html)}
</body>
</html>
"""

def render_soccer_root_index(leagues_written):
    items = []
    for league_name in leagues_written:
        title = league_name.replace("_", " ").title()
        items.append(
            f"""
<a href="{league_name}/index.html" style="text-decoration:none;color:{TXT};">
  <div style="background:#111827;border:1px solid #1F2937;border-radius:14px;padding:16px;margin:12px 0;">
    <div style="font-size:18px;font-weight:700;">{html.escape(title)}</div>
    <div style="opacity:0.7;margin-top:4px;">Open fixtures</div>
  </div>
</a>
"""
        )

    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="background:{THEME_BG};color:{TXT};font-family:Inter,system-ui,Roboto;padding:24px;">
  {sport_header("soccer", base_prefix="../")}
  <a href="../index.html" style="color:#93C5FD;text-decoration:none;">← Back to sports</a>
  <h1 style="margin:0 0 6px 0;">Soccer Odds Checker</h1>
  <p style="opacity:0.8;margin:0 0 16px 0;">Updated: {now_iso()}</p>
  {''.join(items)}
</body>
</html>
"""

def render_nfl_index(games: pd.DataFrame) -> str:
    index_html = []
    current_date = None

    for _, fx in games.sort_values("time").iterrows():
        dt = (fx["time"] or "")[:10]
        if dt != current_date:
            current_date = dt
            index_html.append(f"<h2 style='margin:24px 0 8px 0;'>{html.escape(dt)}</h2>")

        slug = fixture_slug(fx["home"], fx["away"])
        index_html.append(
            f"""
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
    gap:16px;
  ">
    <div>
      <div style="font-size:18px;font-weight:600;">{html.escape(fx['home'])}</div>
      <div style="opacity:0.7;">vs</div>
      <div style="font-size:18px;font-weight:600;">{html.escape(fx['away'])}</div>
    </div>
    <div style="opacity:0.6;font-size:14px;white-space:nowrap;">
      {html.escape(str(fx['time']))} UTC
    </div>
  </div>
</a>
"""
        )

    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="background:{THEME_BG};color:{TXT};font-family:Inter,system-ui,Roboto;padding:24px;">
  {sport_header("nfl", base_prefix="../")}
  <a href="../index.html" style="color:#93C5FD;text-decoration:none;">← Back to sports</a>
  <h1 style="margin:0 0 6px 0;">NFL Odds Checker</h1>
  <p style="opacity:0.8;margin:0 0 16px 0;">Updated: {now_iso()}</p>
  {''.join(index_html) if index_html else "<p style='opacity:0.7;'>No NFL fixtures available right now.</p>"}
</body>
</html>
"""

def render_main_index() -> str:
    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="background:{THEME_BG};color:{TXT};font-family:Inter,system-ui,Roboto;padding:24px;">
  <h1 style="margin:0 0 6px 0;">Odds Checker</h1>
  <p style="opacity:0.8;margin:0 0 16px 0;">Updated: {now_iso()}</p>
  {sport_header("soccer", base_prefix="")}
  <div style="opacity:0.8;font-size:13px;margin-top:6px;">
    Select a sport to view fixtures and odds.
  </div>
</body>
</html>
"""

# ---------------- MAIN --------------------

def main():
    BASE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- Write main sport selector landing ---
    (BASE_OUTPUT_DIR / "index.html").write_text(render_main_index(), encoding="utf-8")

    # ---------------- SOCCER ----------------
    soccer_root = BASE_OUTPUT_DIR / "soccer"
    soccer_root.mkdir(parents=True, exist_ok=True)

    all_h2h = []
    all_totals = []
    all_spreads = []

    for league_name, league_key in SOCCER_LEAGUES.items():
        print(f"\n=== SOCCER {league_name.upper()} ===")
        try:
            raw = fetch(league_key, "h2h")
            df_h = df_h2h(raw, sport="soccer")
            if not df_h.empty:
                df_h["league"] = league_name
                all_h2h.append(df_h)

            raw = fetch(league_key, "totals")
            df_t = df_totals(raw)
            if not df_t.empty:
                df_t["league"] = league_name
                all_totals.append(df_t)

            raw = fetch(league_key, "spreads")
            df_s = df_spreads(raw, sport="soccer")
            if not df_s.empty:
                df_s["league"] = league_name
                all_spreads.append(df_s)

        except Exception as e:
            print(f"[SKIP SOCCER] {league_name}: {e}")

    if all_h2h:
        df_h2h_all = pd.concat(all_h2h, ignore_index=True)
        df_totals_all = pd.concat(all_totals, ignore_index=True) if all_totals else pd.DataFrame()
        df_spreads_all = pd.concat(all_spreads, ignore_index=True) if all_spreads else pd.DataFrame()

        all_games = (
            df_h2h_all[["event_id", "time", "home", "away", "league"]]
            .drop_duplicates()
            .sort_values("time")
        )

        # fixture pages (per league)
        for _, fx in all_games.iterrows():
            league_dir = soccer_root / fx["league"]
            league_dir.mkdir(parents=True, exist_ok=True)

            h = df_h2h_all[df_h2h_all["event_id"] == fx.event_id]
            t = df_totals_all[df_totals_all["event_id"] == fx.event_id] if not df_totals_all.empty else df_totals_all
            s = df_spreads_all[df_spreads_all["event_id"] == fx.event_id] if not df_spreads_all.empty else df_spreads_all

            html_out = render_fixture_page(
                fx, h, t, s,
                sport="soccer",
                back_href="index.html",
                base_prefix="../../"  # from soccer/<league>/<fixture>.html to odds_checker root
            )
            (league_dir / fixture_slug(fx["home"], fx["away"])).write_text(html_out, encoding="utf-8")

        # league index pages + soccer league picker
        leagues_written = []
        for league_name in SOCCER_LEAGUES.keys():
            league_games = all_games[all_games["league"] == league_name]
            if league_games.empty:
                continue
            league_dir = soccer_root / league_name
            league_dir.mkdir(parents=True, exist_ok=True)
            (league_dir / "index.html").write_text(
                render_soccer_league_index(league_name, league_games),
                encoding="utf-8",
            )
            leagues_written.append(league_name)

        (soccer_root / "index.html").write_text(
            render_soccer_root_index(leagues_written),
            encoding="utf-8",
        )
    else:
        # Still write soccer index (empty state) so the tab works
        (soccer_root / "index.html").write_text(
            render_soccer_root_index([]),
            encoding="utf-8",
        )

    # ---------------- NFL ----------------
    nfl_root = BASE_OUTPUT_DIR / "nfl"
    nfl_root.mkdir(parents=True, exist_ok=True)

    print("\n=== NFL ===")
    try:
        raw = fetch(NFL_SPORT_KEY, "h2h")
        nfl_h2h = df_h2h(raw, sport="nfl")

        raw = fetch(NFL_SPORT_KEY, "totals")
        nfl_totals = df_totals(raw)

        raw = fetch(NFL_SPORT_KEY, "spreads")
        nfl_spreads = df_spreads(raw, sport="nfl")

        if not nfl_h2h.empty:
            nfl_games = (
                nfl_h2h[["event_id", "time", "home", "away"]]
                .drop_duplicates()
                .sort_values("time")
            )

            # Write NFL fixture pages
            for _, fx in nfl_games.iterrows():
                h = nfl_h2h[nfl_h2h["event_id"] == fx.event_id]
                t = nfl_totals[nfl_totals["event_id"] == fx.event_id] if not nfl_totals.empty else nfl_totals
                s = nfl_spreads[nfl_spreads["event_id"] == fx.event_id] if not nfl_spreads.empty else nfl_spreads

                html_out = render_fixture_page(
                    fx, h, t, s,
                    sport="nfl",
                    back_href="index.html",
                    base_prefix="../"  # from nfl/<fixture>.html to odds_checker root
                )
                (nfl_root / fixture_slug(fx["home"], fx["away"])).write_text(html_out, encoding="utf-8")

            # Write NFL index
            (nfl_root / "index.html").write_text(render_nfl_index(nfl_games), encoding="utf-8")
        else:
            (nfl_root / "index.html").write_text(render_nfl_index(pd.DataFrame()), encoding="utf-8")

    except Exception as e:
        print(f"[SKIP NFL] {e}")
        (nfl_root / "index.html").write_text(render_nfl_index(pd.DataFrame()), encoding="utf-8")

    print("Done.")

if __name__ == "__main__":
    main()
