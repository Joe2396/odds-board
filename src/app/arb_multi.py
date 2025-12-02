# -*- coding: utf-8 -*-
"""
EPL Multi-Market Arbitrage Finder – UK books via The Odds API.
Markets: 1X2 · BTTS · Double Chance · Totals
Output: data/auto/arb_latest.html
"""

import json, html
from pathlib import Path
from datetime import datetime, timezone
import requests
import pandas as pd

# ===== CONFIG =====
API_KEY = "98fb91f398403151a3eece97dc514a0b"
SPORT = "soccer_epl"
REGIONS = "uk"
MARKETS = "h2h,btts,totals"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
BANKROLL = 100.0
STALE_MIN = 240
OUTPUT_HTML = Path("data/auto/arb_latest.html")
TIMEOUT = 20

BOOK_PRIORITY = [
    "PaddyPower","Betfair","Betfair Sportsbook","William Hill",
    "Ladbrokes","SkyBet","Unibet","BetVictor","BoyleSports","Casumo"
]

# ===== Helpers =====

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

def fetch_all():
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"
    params = dict(
        apiKey=API_KEY,
        regions=REGIONS,
        markets=MARKETS,
        oddsFormat=ODDS_FORMAT,
        dateFormat=DATE_FORMAT
    )
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise SystemExit(f"[ERROR] HTTP {r.status_code}: {r.text}")
    return r.json()

def book_order(name):
    return BOOK_PRIORITY.index(name) if name in BOOK_PRIORITY else len(BOOK_PRIORITY)

# ===== Market Parsers =====

def parse_1x2(data):
    """Extract 1X2 markets (h2h)"""
    rows = []
    for g in data:
        for b in g.get("bookmakers", []):
            for m in b.get("markets", []):
                if m.get("key") != "h2h":
                    continue
                outcomes = m.get("outcomes", [])
                if len(outcomes) != 3:
                    continue
                for o in outcomes:
                    rows.append({
                        "event_id": g["id"],
                        "start": g["commence_time"],
                        "home": g["home_team"],
                        "away": g["away_team"],
                        "book": b["title"],
                        "label": o["name"],   # Home / Draw / Away
                        "odds": o["price"]
                    })
    return pd.DataFrame(rows)

def parse_btts(data):
    rows = []
    for g in data:
        for b in g.get("bookmakers", []):
            for m in b.get("markets", []):
                if m.get("key") != "btts":
                    continue
                for o in m.get("outcomes", []):
                    if o["name"].lower() not in ("yes","no"):
                        continue
                    rows.append({
                        "event_id": g["id"],
                        "start": g["commence_time"],
                        "home": g["home_team"],
                        "away": g["away_team"],
                        "book": b["title"],
                        "label": o["name"].title(),  # Yes / No
                        "odds": o["price"]
                    })
    return pd.DataFrame(rows)

def parse_totals(data):
    rows = []
    for g in data:
        for b in g.get("bookmakers", []):
            for m in b.get("markets", []):
                if m.get("key") != "totals":
                    continue
                for o in m.get("outcomes", []):
                    if o["name"] not in ("Over","Under"):
                        continue
                    rows.append({
                        "event_id": g["id"],
                        "start": g["commence_time"],
                        "home": g["home_team"],
                        "away": g["away_team"],
                        "book": b["title"],
                        "label": o["name"],
                        "line": o["point"],
                        "odds": o["price"]
                    })
    return pd.DataFrame(rows)

# ===== Arbitrage Calculators =====

def arb_1x2(df):
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["prio"] = df["book"].apply(book_order)

    # best odds per outcome
    best = df.sort_values(["odds","prio"], ascending=[False,True]) \
             .groupby(["event_id","start","home","away","label"], as_index=False) \
             .first()

    # pivot → Home, Draw, Away
    wide = best.pivot(index=["event_id","start","home","away"],
                      columns="label", values=["odds","book"]).reset_index()

    if ("odds","Home") not in wide or ("odds","Draw") not in wide or ("odds","Away") not in wide:
        return pd.DataFrame()

    wide["sum_imp"] = 1/wide[("odds","Home")] + 1/wide[("odds","Draw")] + 1/wide[("odds","Away")]
    arbs = wide[wide["sum_imp"] < 1]

    if arbs.empty:
        return arbs

    arbs["roi"] = ((1 - arbs["sum_imp"]) * 100).round(2)
    return arbs.sort_values("roi", ascending=False)

def arb_btts(df):
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["prio"] = df["book"].apply(book_order)

    best = df.sort_values(["odds","prio"], ascending=[False,True]) \
             .groupby(["event_id","start","home","away","label"], as_index=False) \
             .first()

    wide = best.pivot(index=["event_id","start","home","away"],
                      columns="label", values=["odds","book"]).reset_index()

    if ("odds","Yes") not in wide or ("odds","No") not in wide:
        return pd.DataFrame()

    wide["sum_imp"] = 1/wide[("odds","Yes")] + 1/wide[("odds","No")]
    arbs = wide[wide["sum_imp"] < 1]

    if arbs.empty:
        return arbs

    arbs["roi"] = ((1 - arbs["sum_imp"]) * 100).round(2)
    return arbs.sort_values("roi", ascending=False)

def arb_double_chance(df_1x2):
    # Double Chance derived from 1X2 odds
    if df_1x2.empty:
        return pd.DataFrame()

    df = df_1x2.copy()
    df["prio"] = df["book"].apply(book_order)
    best = df.sort_values(["odds","prio"], ascending=[False,True]) \
             .groupby(["event_id","start","home","away","label"], as_index=False) \
             .first()

    wide = best.pivot(index=["event_id","start","home","away"],
                      columns="label", values=["odds","book"]).reset_index()

    if ("odds","Home") not in wide or ("odds","Draw") not in wide or ("odds","Away") not in wide:
        return pd.DataFrame()

    rows = []

    for _, r in wide.iterrows():
        # DC markets:
        # 1X = Home or Draw → price = max(Home, Draw)
        # 12 = Home or Away → price = max(Home, Away)
        # X2 = Draw or Away → price = max(Draw, Away)

        dc = {
            "1X": max(r[("odds","Home")], r[("odds","Draw")]),
            "12": max(r[("odds","Home")], r[("odds","Away")]),
            "X2": max(r[("odds","Draw")], r[("odds","Away")]),
        }

        # 2-way arbitrage across DC options
        for m1, m2 in [("1X","12"), ("1X","X2"), ("12","X2")]:
            o1, o2 = dc[m1], dc[m2]
            imp = 1/o1 + 1/o2
            if imp < 1:
                rows.append({
                    "event_id": r["event_id"],
                    "start": r["start"],
                    "home": r["home"],
                    "away": r["away"],
                    "opt1": m1, "odds1": o1,
                    "opt2": m2, "odds2": o2,
                    "roi": round((1-imp)*100,2)
                })

    return pd.DataFrame(rows).sort_values("roi", ascending=False)

def arb_totals(df):
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["prio"] = df["book"].apply(book_order)

    # best Over/Under for each line
    over = df[df["label"]=="Over"].sort_values(["odds","prio"], ascending=[False,True]) \
                                 .groupby(["event_id","start","home","away","line"], as_index=False).first()
    under = df[df["label"]=="Under"].sort_values(["odds","prio"], ascending=[False,True]) \
                                   .groupby(["event_id","start","home","away","line"], as_index=False).first()

    merged = over.merge(under, on=["event_id","start","home","away","line"], suffixes=("_o","_u"))
    merged["sum_imp"] = 1/merged["odds_o"] + 1/merged["odds_u"]
    arbs = merged[merged["sum_imp"] < 1]

    if arbs.empty:
        return arbs

    arbs["roi"] = ((1-arbs["sum_imp"])*100).round(2)
    return arbs.sort_values("roi", ascending=False)

# ===== HTML Renderer =====

def render(arbs_1x2, arbs_btts, arbs_dc, arbs_tot):
    ts = now_iso()

    def section(title, html_body):
        return f"""
        <h2 style='margin-top:24px;margin-bottom:12px;'>{title}</h2>
        {html_body}
        """

    def table(headers, rows_html):
        return f"""
        <div style='overflow:auto;border:1px solid #1F2937;border-radius:12px;margin-bottom:20px;'>
          <table style='width:100%;border-collapse:collapse;min-width:700px;'>
            <thead><tr style='background:#111827;'>
              {''.join(f"<th style='padding:10px;text-align:left;border-bottom:1px solid #1F2937;'>{h}</th>" for h in headers)}
            </tr></thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
        """

    out = f"""
    <!doctype html><html><head>
    <meta charset='utf-8'>
    <meta name='viewport' content='width=device-width,initial-scale=1'>
    </head>
    <body style='color:#E2E8F0;background:#0F1621;padding:24px;font-family:Inter,system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'>
    <h1 style='margin-top:0;'>EPL Multi-Market Arbitrage</h1>
    <p style='opacity:0.8'>Last update: {ts}</p>
    """

    # 1X2
    if not arbs_1x2.empty:
        rows = ""
        for _, r in arbs_1x2.iterrows():
            rows += f"""
            <tr>
              <td>{r['home']} vs {r['away']}</td>
              <td>{r[('odds','Home')]:.2f}</td>
              <td>{r[('odds','Draw')]:.2f}</td>
              <td>{r[('odds','Away')]:.2f}</td>
              <td>{r['roi']}%</td>
            </tr>"""
        out += section("Match Result (1X2) Arbitrage",
                       table(["Fixture","Home","Draw","Away","ROI"], rows))

    # BTTS
    if not arbs_btts.empty:
        rows = ""
        for _, r in arbs_btts.iterrows():
            rows += f"""
            <tr>
              <td>{r['home']} vs {r['away']}</td>
              <td>{r[('odds','Yes')]:.2f}</td>
              <td>{r[('odds','No')]:.2f}</td>
              <td>{r['roi']}%</td>
            </tr>"""
        out += section("Both Teams To Score (BTTS) Arbitrage",
                       table(["Fixture","Yes","No","ROI"], rows))

    # Double Chance
    if not arbs_dc.empty:
        rows = ""
        for _, r in arbs_dc.iterrows():
            rows += f"""
            <tr>
              <td>{r['home']} vs {r['away']}</td>
              <td>{r['opt1']} @ {r['odds1']:.2f}</td>
              <td>{r['opt2']} @ {r['odds2']:.2f}</td>
              <td>{r['roi']}%</td>
            </tr>"""
        out += section("Double Chance Arbitrage",
                       table(["Fixture","Option 1","Option 2","ROI"], rows))

    # Totals
    if not arbs_tot.empty:
        rows = ""
        for _, r in arbs_tot.iterrows():
            rows += f"""
            <tr>
              <td>{r['home']} vs {r['away']}</td>
              <td>{r['line']}</td>
              <td>{r['odds_o']:.2f}</td>
              <td>{r['odds_u']:.2f}</td>
              <td>{r['roi']}%</td>
            </tr>"""
        out += section("Totals Over/Under Arbitrage",
                       table(["Fixture","Line","Over","Under","ROI"], rows))

    out += "</body></html>"
    return out

# ===== Main =====

def main():
    data = fetch_all()

    df1x2   = parse_1x2(data)
    dfbtts  = parse_btts(data)
    dftot   = parse_totals(data)

    arbs1   = arb_1x2(df1x2)
    arbsbt  = arb_btts(dfbtts)
    arbsdc  = arb_double_chance(df1x2)
    arbstot = arb_totals(dftot)

    html_out = render(arbs1, arbsbt, arbsdc, arbstot)

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html_out, encoding="utf-8")
    print(f"Wrote: {OUTPUT_HTML}")

if __name__ == "__main__":
    main()
