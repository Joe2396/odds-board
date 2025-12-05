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

# ------------------ CONFIG ------------------
API_KEY = "YOUR_NEW_API_KEY_HERE"      # <--- INSERT NEW KEY
SPORT   = "soccer_epl"
REGIONS = "uk"
MARKETS = "h2h,totals,spreads"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"

OUTPUT_DIR = Path("data/auto/odds_checker")
THEME_BG = "#0F1621"
TXT      = "#E2E8F0"

POPULAR_SPREAD_LINES = { -1.0, 0.0, 1.0 }   # <--- we agreed on these
# --------------------------------------------

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

def tidy_book(bk):
    return (bk or "").replace("Sportsbook", "").strip()

# ------------------ API FETCH ------------------
def fetch_epl_odds():
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"
    params = dict(
        apiKey=API_KEY,
        regions=REGIONS,
        markets=MARKETS,
        oddsFormat=ODDS_FORMAT,
        dateFormat=DATE_FORMAT
    )
    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"HTTP {r.status_code}: {r.text}")
    return r.json()

# ------------------ PARSERS ------------------
def df_h2h(js):
    rows=[]
    for g in js:
        gid=g["id"]; t=g["commence_time"]; home=g["home_team"]; away=g["away_team"]
        for b in g.get("bookmakers",[]):
            book = tidy_book(b["title"])
            for m in b.get("markets",[]):
                if m.get("key")!="h2h": continue
                for o in m.get("outcomes",[]):
                    name=(o.get("name") or "").title()
                    price=o.get("price")
                    if not price: continue
                    if name==home: side="Home"
                    elif name==away: side="Away"
                    elif name=="Draw": side="Draw"
                    else: continue
                    rows.append({
                        "event_id":gid,"time":t,"home":home,"away":away,
                        "book":book,"side":side,"odds":float(price)
                    })
    df=pd.DataFrame(rows)
    return df[(df["odds"]>=1.01)&(df["odds"]<=1000)] if not df.empty else df

def df_totals(js):
    rows=[]
    for g in js:
        gid=g["id"]; t=g["commence_time"]; home=g["home_team"]; away=g["away_team"]
        for b in g.get("bookmakers",[]):
            book = tidy_book(b["title"])
            for m in b.get("markets",[]):
                if m.get("key")!="totals": continue
                for o in m.get("outcomes",[]):
                    name=(o.get("name") or "").title()
                    point=o.get("point"); price=o.get("price")
                    if name not in ("Over","Under") or point is None or price is None:
                        continue
                    rows.append({
                        "event_id":gid,"time":t,"home":home,"away":away,
                        "book":book,"side":name,"line":float(point),"odds":float(price)
                    })
    df=pd.DataFrame(rows)
    return df[(df["odds"]>=1.01)&(df["odds"]<=1000)] if not df.empty else df

def df_spreads(js):
    rows=[]
    for g in js:
        gid=g["id"]; t=g["commence_time"]; home=g["home_team"]; away=g["away_team"]
        for b in g.get("bookmakers",[]):
            book=tidy_book(b["title"])
            for m in b.get("markets",[]):
                if m.get("key")!="spreads": continue
                for o in m.get("outcomes",[]):
                    name=(o.get("name") or "").title()
                    line=o.get("point")
                    price=o.get("price")
                    if line is None or price is None: continue
                    line=float(line)

                    # only keep the 3 most popular lines
                    if line not in POPULAR_SPREAD_LINES: 
                        continue

                    if name==home: side="Home"
                    elif name==away: side="Away"
                    else: continue

                    rows.append({
                        "event_id":gid,"time":t,"home":home,"away":away,
                        "book":book,"side":side,"line":line,"odds":float(price)
                    })

    df=pd.DataFrame(rows)
    return df[(df["odds"]>=1.01)&(df["odds"]<=1000)] if not df.empty else df

# ------------------ HTML HELPERS ------------------
def chips(items, best_val):
    out=[]
    for bk,od in items:
        pill=(od==best_val)
        style="background:#10B98122;border:1px solid #10B98155;" if pill else \
              "background:#111827;border:1px solid #1F2937;"
        out.append(
            f"<span style='{style}border-radius:10px;padding:2px 8px;"
            f"display:inline-block;margin:2px 6px 2px 0;'>{html.escape(bk)} @ {od}</span>"
        )
    return "".join(out)

# ------------------ RENDER FIXTURE PAGE ------------------
def render_fixture_page(fx, h2h_df, totals_df, spreads_df):
    ts=now_iso()

    # Header
    out=[f"""
    <div style="color:{TXT};background:{THEME_BG};padding:24px;font-family:Inter,system-ui,Roboto,sans-serif;">
      <a href="index.html" style="color:#93C5FD;text-decoration:none;">← All fixtures</a>
      <h1 style="margin:8px 0 0 0;">{html.escape(fx['home'])} vs {html.escape(fx['away'])}</h1>
      <p style="opacity:0.8;margin:6px 0 18px 0;">Kickoff (UTC): {fx['time']} · Updated: {ts}</p>
    """]

    # ------------------ 1X2 ------------------
    if not h2h_df.empty:
        out.append("<h2>Match Result (1X2)</h2>")
        out.append("<div style='overflow:auto;border:1px solid #1F2937;border-radius:12px;margin-bottom:20px;'><table style='width:100%;border-collapse:collapse;min-width:900px;'><thead><tr style='background:#111827;'><th>Outcome</th><th>Best price</th><th>All books</th></tr></thead><tbody>")
        
        for side in ["Home","Draw","Away"]:
            rows=h2h_df[h2h_df["side"]==side]
            if rows.empty: continue
            sorted_rows = rows.sort_values("odds", ascending=False)
            best_od=sorted_rows.iloc[0]["odds"]
            best_bk=sorted_rows.iloc[0]["book"]
            pairs = sorted_rows[["book","odds"]].values.tolist()

            out.append(f"<tr><td>{side}</td><td><strong>{best_od}</strong> @ {best_bk}</td><td>{chips(pairs, best_od)}</td></tr>")
        
        out.append("</tbody></table></div>")

    # ------------------ TOTALS ------------------
    if not totals_df.empty:
        out.append("<h2>Total Goals</h2>")
        for line, sub in totals_df.groupby("line"):
            sub=sub.sort_values("odds", ascending=False)
            over = sub[sub["side"]=="Over"][["book","odds"]].values.tolist()
            under = sub[sub["side"]=="Under"][["book","odds"]].values.tolist()

            best_over = over[0][1] if over else None
            best_under = under[0][1] if under else None

            out.append(f"<div style='margin:12px 0 18px 0;'><h3>Total {line:+.1f}</h3>")
            out.append("<div style='display:grid;grid-template-columns:1fr 1fr;gap:10px;'>")

            out.append("<div>Over<br>" + (chips(over, best_over) if over else "<em>No prices</em>") + "</div>")
            out.append("<div>Under<br>" + (chips(under, best_under) if under else "<em>No prices</em>") + "</div>")
            out.append("</div></div>")

    # ------------------ SPREADS ------------------
    if not spreads_df.empty:
        out.append("<h2>Handicap (Spreads)</h2>")
        for line, sub in spreads_df.groupby("line"):
            sub=sub.sort_values("odds", ascending=False)
            home_list = sub[sub["side"]=="Home"][["book","odds"]].values.tolist()
            away_list = sub[sub["side"]=="Away"][["book","odds"]].values.tolist()
            best_home = home_list[0][1] if home_list else None
            best_away = away_list[0][1] if away_list else None

            out.append(f"<div style='margin:12px 0 18px 0;'><h3>Line {line:+.1f}</h3>")
            out.append("<div style='display:grid;grid-template-columns:1fr 1fr;gap:10px;'>")

            out.append("<div>Home<br>" + (chips(home_list, best_home) if home_list else "<em>No prices</em>") + "</div>")
            out.append("<div>Away<br>" + (chips(away_list, best_away) if away_list else "<em>No prices</em>") + "</div>")

            out.append("</div></div>")

    out.append("</div>")
    return "".join(out)

# ------------------ BUILD ALL PAGES ------------------
def main():
    js = fetch_epl_odds()
    h2h_df = df_h2h(js)
    totals_df = df_totals(js)
    spreads_df = df_spreads(js)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # fixture index
    fixtures = []
    for g in js:
        fixtures.append({
            "id":g["id"],
            "home":g["home_team"],
            "away":g["away_team"],
            "time":g["commence_time"]
        })

    # write index.html
    index_html = render_index(fixtures)
    (OUTPUT_DIR/"index.html").write_text(index_html, encoding="utf-8")

    # write per-fixture pages
    for fx in fixtures:
        page = render_fixture_page(
            fx,
            h2h_df[h2h_df["event_id"]==fx["id"]],
            totals_df[totals_df["event_id"]==fx["id"]],
            spreads_df[spreads_df["event_id"]==fx["id"]],
        )
        (OUTPUT_DIR/f"{fx['id']}.html").write_text(page, encoding="utf-8")

def render_index(fixtures):
    rows=[]
    for f in fixtures:
        rows.append(f"""
        <a href="{f['id']}.html" style="text-decoration:none;color:{TXT};">
          <div style="background:#111827;border:1px solid #1F2937;border-radius:12px;padding:14px;margin-bottom:12px;">
            <strong>{html.escape(f['home'])} vs {html.escape(f['away'])}</strong>
            <div style="opacity:0.8;">{f['time']}</div>
          </div>
        </a>
        """)
    return f"""
    <html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'></head>
    <body style="background:{THEME_BG};color:{TXT};font-family:Inter,system-ui;">
    <div style="padding:24px;">
      <h1>EPL Odds Checker</h1>
      {''.join(rows)}
    </div>
    </body></html>
    """

if __name__ == "__main__":
    main()
