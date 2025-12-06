# -*- coding: utf-8 -*-
"""
EPL Odds Checker (1X2 + Totals + Spreads)
Outputs fixture index + per-fixture pages.
"""

import json, html
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path
import requests
import pandas as pd

# ---------------- CONFIG --------------------

API_KEY = "8e8a4a2421e95ad2fb0df450c88ef6c6"    # <--- YOUR KEY
SPORT   = "soccer_epl"
REGIONS = "uk"
MARKETS = "h2h,totals,spreads"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

OUTPUT_DIR = Path("data/auto/odds_checker")
THEME_BG = "#0F1621"
TXT = "#E2E8F0"

POPULAR_SPREAD_LINES = { -1.0, 0.0, 1.0 }  # we agreed these are the common ones

# Book renaming
def tidy_book(name: str):
    if not name:
        return "Unknown"
    MAP = {
        "Sky Bet": "SkyBet",
        "Betfair": "Betfair Sportsbook",
        "Paddy Power": "PaddyPower",
    }
    return MAP.get(name, name)

# Time formatting
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

# ==========================================================
#   FETCH RAW DATA
# ==========================================================

def fetch(mkts: str):
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"
    p = dict(
        apiKey=API_KEY,
        regions=REGIONS,
        markets=mkts,
        oddsFormat=ODDS_FORMAT,
        dateFormat=DATE_FORMAT
    )
    r = requests.get(url, params=p, timeout=TIMEOUT)
    if r.status_code != 200:
        raise SystemExit(f"HTTP {r.status_code}: {r.text}")
    return r.json()

# ==========================================================
#   DATAFRAME BUILDERS
# ==========================================================

def df_h2h(data):
    rows=[]
    for g in data:
        gid=g["id"]; t=g["commence_time"]; home=g["home_team"]; away=g["away_team"]
        for b in g.get("bookmakers",[]):
            book = tidy_book(b.get("title"))
            for m in b.get("markets",[]):
                if m.get("key")!="h2h": continue
                for o in m.get("outcomes",[]):
                    name=o.get("name","")
                    price=o.get("price")
                    if price is None: continue
                    if name.lower()==home.lower(): side="Home"
                    elif name.lower()==away.lower(): side="Away"
                    elif name.lower()=="draw": side="Draw"
                    else: continue
                    rows.append({"event_id":gid,"time":t,"home":home,"away":away,
                                 "book":book,"market":"h2h","side":side,"odds":float(price)})
    df=pd.DataFrame(rows)
    if not df.empty:
        df=df[(df["odds"]>=1.01)&(df["odds"]<=1000)]
    return df


def df_totals(data):
    rows=[]
    for g in data:
        gid=g["id"]; t=g["commence_time"]; home=g["home_team"]; away=g["away_team"]
        for b in g.get("bookmakers",[]):
            book=tidy_book(b.get("title"))
            for m in b.get("markets",[]):
                if m.get("key")!="totals": continue
                for o in m.get("outcomes",[]):
                    name=o.get("name","").title()
                    point=o.get("point"); price=o.get("price")
                    if name not in ("Over","Under") or price is None or point is None:
                        continue
                    rows.append({"event_id":gid,"time":t,"home":home,"away":away,
                                 "book":book,"market":"totals","line":float(point),
                                 "side":name,"odds":float(price)})
    df=pd.DataFrame(rows)
    if not df.empty:
        df=df[(df["odds"]>=1.01)&(df["odds"]<=1000)]
    return df


def df_spreads(data):
    rows=[]
    for g in data:
        gid=g["id"]; t=g["commence_time"]; home=g["home_team"]; away=g["away_team"]
        for b in g.get("bookmakers",[]):
            book=tidy_book(b.get("title"))
            for m in b.get("markets",[]):
                if m.get("key")!="spreads": continue
                for o in m.get("outcomes",[]):
                    name=o.get("name","")
                    line=o.get("point"); price=o.get("price")
                    if price is None or line is None: continue
                    # Only keep popular lines
                    if float(line) not in POPULAR_SPREAD_LINES:
                        continue
                    if name.lower()==home.lower(): side="Home"
                    elif name.lower()==away.lower(): side="Away"
                    else: continue
                    rows.append({"event_id":gid,"time":t,"home":home,"away":away,
                                 "book":book,"market":"spreads","line":float(line),
                                 "side":side,"odds":float(price)})
    df=pd.DataFrame(rows)
    if not df.empty:
        df=df[(df["odds"]>=1.01) & (df["odds"]<=1000)]
    return df

# Render chips
def chips(items, best):
    out=[]
    for (bk,od) in items:
        is_best = (od==best)
        style = ("background:#10B98122;border:1px solid #10B98155;"
                 if is_best else
                 "background:#111827;border:1px solid #1F2937;")
        out.append(f"<span style='{style}border-radius:10px;padding:2px 8px;display:inline-block;margin:2px 6px 2px 0;'>{html.escape(bk)} @ {od}</span>")
    return "".join(out)

# ==========================================================
#   RENDER FIXTURE PAGE
# ==========================================================

def render_fixture_page(fx, h2h, totals, spreads):
    ts=now_iso()
    out=[]

    out.append(f"""
    <div style="color:{TXT};background:{THEME_BG};padding:24px;font-family:Inter,system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
      <a href="index.html" style="color:#93C5FD;text-decoration:none;">← All fixtures</a>
      <h1 style="margin:8px 0 0 0;">{html.escape(fx['home'])} vs {html.escape(fx['away'])}</h1>
      <p style="opacity:0.8;margin:6px 0 18px 0;">Kickoff (UTC): {html.escape(fx['time'])} · Updated: {ts}</p>
    """)

    # --------------------- H2H ---------------------
    if not h2h.empty:
        out.append("<h2>Match Result (1X2)</h2>")
        out.append("""
        <div style="overflow:auto;border:1px solid #1F2937;border-radius:12px;margin-bottom:20px;">
          <table style="width:100%;min-width:900px;border-collapse:collapse;">
            <thead>
              <tr style="background:#111827;">
                <th style="padding:12px;">Outcome</th>
                <th style="padding:12px;">Best price</th>
                <th style="padding:12px;">All books</th>
              </tr>
            </thead>
            <tbody>
        """)
        for side in ["Home","Draw","Away"]:
            sub=h2h[h2h["side"]==side].sort_values("odds", ascending=False)
            if sub.empty: continue
            best=sub.iloc[0]
            all_pairs=sub[["book","odds"]].values.tolist()
            out.append(f"""
              <tr>
                <td style="padding:12px;">{side}</td>
                <td style="padding:12px;"><strong>{best['odds']}</strong> @ {best['book']}</td>
                <td style="padding:12px;">{chips(all_pairs,best['odds'])}</td>
              </tr>
            """)
        out.append("</tbody></table></div>")

    # --------------------- TOTALS ---------------------
    if not totals.empty:
        out.append("<h2>Total Goals (Over/Under)</h2>")
        out.append("<div style='border:1px solid #1F2937;border-radius:12px;padding:12px;'>")
        for line,sub in totals.groupby("line"):
            sub=sub.sort_values("odds", ascending=False)
            over=sub[sub["side"]=="Over"][["book","odds"]].values.tolist()
            under=sub[sub["side"]=="Under"][["book","odds"]].values.tolist()
            best_over = over[0][1] if over else None
            best_under = under[0][1] if under else None
            out.append(f"""
              <div style="margin:12px 0 18px 0;">
                <h3>Total {line:+.1f}</h3>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                  <div><div>Over</div>{chips(over,best_over) if over else "<em>No prices</em>"}</div>
                  <div><div>Under</div>{chips(under,best_under) if under else "<em>No prices</em>"}</div>
                </div>
              </div>
            """)
        out.append("</div>")

    # --------------------- SPREADS ---------------------
    if not spreads.empty:
        out.append("<h2>Handicap (Spreads)</h2>")
        out.append("<div style='border:1px solid #1F2937;border-radius:12px;padding:12px;'>")
        for line,sub in spreads.groupby("line"):
            sub=sub.sort_values("odds", ascending=False)
            home=sub[sub["side"]=="Home"][["book","odds"]].values.tolist()
            away=sub[sub["side"]=="Away"][["book","odds"]].values.tolist()
            best_home = home[0][1] if home else None
            best_away = away[0][1] if away else None

            out.append(f"""
              <div style="margin:12px 0 18px 0;">
                <h3>Line {line:+.1f}</h3>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                  <div><div>Home</div>{chips(home,best_home) if home else "<em>No prices</em>"}</div>
                  <div><div>Away</div>{chips(away,best_away) if away else "<em>No prices</em>"}</div>
                </div>
              </div>
            """)
        out.append("</div>")

    out.append("</div></body></html>")
    return "".join(out)

# ==========================================================
#   MAIN GENERATION
# ==========================================================

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching H2H…")
    raw = fetch("h2h")
    df1 = df_h2h(raw)

    print("Fetching Totals…")
    raw = fetch("totals")
    df2 = df_totals(raw)

    print("Fetching Spreads…")
    raw = fetch("spreads")
    df3 = df_spreads(raw)

    all_games = df1[["event_id","time","home","away"]].drop_duplicates()

    # Write fixture pages
    for _,fx in all_games.iterrows():
        h = df1[df1["event_id"]==fx.event_id]
        t = df2[df2["event_id"]==fx.event_id]
        s = df3[df3["event_id"]==fx.event_id]
        html_out = render_fixture_page(fx, h, t, s)
        fn = OUTPUT_DIR / f"{fx['home'].lower().replace(' ','-')}-vs-{fx['away'].lower().replace(' ','-')}.html"
        fn.write_text(html_out, encoding="utf-8")

    print(f"Wrote {len(all_games)} fixture pages")

    # Write index
    index=[]
    for _,fx in all_games.sort_values("time").iterrows():
        slug=f"{fx['home'].lower().replace(' ','-')}-vs-{fx['away'].lower().replace(' ','-')}.html"
        index.append(f"<li><a href='{slug}'>{html.escape(fx['home'])} vs {html.escape(fx['away'])}</a></li>")

    (OUTPUT_DIR/"index.html").write_text(
f"""
<!doctype html><html><body style="background:{THEME_BG};color:{TXT};font-family:Inter,system-ui,Roboto">
<h1>EPL Odds Checker</h1>
<ul>{''.join(index)}</ul>
</body></html>
""", encoding="utf-8")

    print("Index written.")

if __name__=="__main__":
    main()
