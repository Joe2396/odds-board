# -*- coding: utf-8 -*-
"""
EPL Goals Totals (Over/Under) Arbitrage Finder – UK books via The Odds API.
Outputs: data/auto/arb_goals_latest.html
"""

import json, html, sys, time
from pathlib import Path
from datetime import datetime, timezone
import requests
import pandas as pd

# ====== CONFIG ======
API_KEY = "98fb91f398403151a3eece97dc514a0b"  # consider rotating later
SPORT = "soccer_epl"
REGIONS = "uk"                 # UK books
MARKETS = "totals"             # goals O/U
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
BANKROLL = 100.0               # display-only bankroll for stake splits
STALE_MINUTES = 240            # ignore markets older than this (if timestamps present)
OUTPUT_HTML = Path("data/auto/arb_goals_latest.html")
TIMEOUT = 30

BOOK_PRIORITY = [
    "PaddyPower","Betfair","Betfair Sportsbook","William Hill",
    "Ladbrokes","SkyBet","Unibet","BetVictor","BoyleSports","Casumo"
]

# ====== HELPERS ======
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

def fetch_epl_totals():
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"
    params = dict(
        apiKey=API_KEY, regions=REGIONS, markets=MARKETS,
        oddsFormat=ODDS_FORMAT, dateFormat=DATE_FORMAT
    )
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise SystemExit(f"HTTP {r.status_code}: {r.text}")
    return r.json()

def json_to_long(df_json):
    """
    Flatten API JSON to rows: one row per (game, bookmaker, line, Over/Under)
    """
    rows = []
    for game in df_json:
        gid = game.get("id")
        commence = game.get("commence_time")
        home = game.get("home_team")
        away = game.get("away_team")
        for b in game.get("bookmakers", []):
            book = b.get("title")
            last = b.get("last_update") or game.get("commence_time")
            for m in b.get("markets", []):
                if m.get("key") != "totals":
                    continue
                # Outcomes look like: {"name": "Over", "price": 1.95, "point": 2.5}
                # and {"name": "Under", "price": 1.95, "point": 2.5}
                for o in m.get("outcomes", []):
                    out = (o.get("name") or "").strip().title()
                    if out not in ("Over","Under"):
                        continue
                    line = o.get("point")
                    price = o.get("price")
                    if price is None or line is None: 
                        continue
                    rows.append({
                        "event_id": gid,
                        "commence_time": commence,
                        "home_team": home,
                        "away_team": away,
                        "bookmaker": book,
                        "line": float(line),
                        "side": out,          # Over / Under
                        "odds": float(price),
                        "last_update": last
                    })
    return pd.DataFrame(rows)

def best_pairs(df):
    """
    For each (event, line) choose best Over and best Under across books.
    """
    if df.empty: 
        return df

    df = df.copy()
    df["book_order"] = df["bookmaker"].apply(lambda b: BOOK_PRIORITY.index(b) if b in BOOK_PRIORITY else len(BOOK_PRIORITY))
    # split
    over = (df[df["side"]=="Over"]
            .sort_values(["odds","book_order"], ascending=[False, True])
            .groupby(["event_id","commence_time","home_team","away_team","line"], as_index=False)
            .first()
            .rename(columns={"bookmaker":"over_book","odds":"over_odds"})
           )
    under = (df[df["side"]=="Under"]
             .sort_values(["odds","book_order"], ascending=[False, True])
             .groupby(["event_id","commence_time","home_team","away_team","line"], as_index=False)
             .first()
             .rename(columns={"bookmaker":"under_book","odds":"under_odds"})
            )
    out = pd.merge(over, under, on=["event_id","commence_time","home_team","away_team","line"], how="inner")

    # arb calc
    out["sum_imp"] = 1.0/out["over_odds"] + 1.0/out["under_odds"]
    out["is_arb"] = out["sum_imp"] < 1.0
    B = BANKROLL
    out["stake_over"]  = ((B / out["over_odds"]) / out["sum_imp"]).round(2)
    out["stake_under"] = ((B / out["under_odds"]) / out["sum_imp"]).round(2)
    out["roi_pct"] = ((1.0 - out["sum_imp"]) * 100.0).round(2)
    out = out[out["is_arb"]].sort_values("roi_pct", ascending=False)
    return out

def render_html(arbs: pd.DataFrame):
    ts = now_iso()
    header = f"""
    <div style="color:#E2E8F0;background:#0F1621;padding:24px;font-family:Inter,system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
      <h2 style="margin:0 0 8px 0;">EPL Goals Totals Arbitrage</h2>
      <p style="opacity:0.8;margin:0 0 16px 0;">Last updated: {html.escape(ts)} · Display bankroll: £{BANKROLL:.0f}</p>
    """
    if arbs.empty:
        body = header + "<p>No O/U arbitrage right now. Check back soon.</p></div>"
        return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'></head><body>{body}</body></html>"

    # rows
    trs = []
    for _, r in arbs.iterrows():
        fixture = f"{r['home_team']} vs {r['away_team']}"
        line = f"{r['line']:+.1f} goals"
        row = f"""
        <tr>
          <td>{html.escape(fixture)}</td>
          <td>{html.escape(line)}</td>
          <td><strong>Over</strong><br>{r['over_odds']} @ {html.escape(str(r['over_book']))}</td>
          <td><strong>Under</strong><br>{r['under_odds']} @ {html.escape(str(r['under_book']))}</td>
          <td style="text-align:right;">{r['roi_pct']}%</td>
          <td>Over: £{r['stake_over']}<br>Under: £{r['stake_under']}</td>
        </tr>
        """
        trs.append(row)

    table = f"""
    {header}
      <div style="overflow:auto;border:1px solid #1F2937;border-radius:12px;">
        <table style="width:100%;border-collapse:collapse;min-width:900px;">
          <thead>
            <tr style="background:#111827;">
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Fixture</th>
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Line</th>
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Best Over</th>
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Best Under</th>
              <th style="text-align:right;padding:12px;border-bottom:1px solid #1F2937;">ROI</th>
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Suggested Stakes</th>
            </tr>
          </thead>
          <tbody>
            {''.join(trs)}
          </tbody>
        </table>
      </div>
      <p style="opacity:0.7;margin-top:12px;font-size:12px;">
        Stakes are illustrative for a £{BANKROLL:.0f} bankroll. Verify line/market match exactly before placing bets.
      </p>
    </div>
    """
    return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'></head><body>{table}</body></html>"

def main():
    data = fetch_epl_totals()
    df = json_to_long(data)

    if df.empty:
        html_text = render_html(pd.DataFrame())
    else:
        # (Optional) drop stale by last_update if present
        if "last_update" in df.columns and df["last_update"].notna().any():
            ts = pd.to_datetime(df["last_update"], errors="coerce", utc=True)
            cutoff = pd.Timestamp.utcnow() - pd.Timedelta(minutes=STALE_MINUTES)
            df = df[ts.isna() | (ts >= cutoff)]
        # price sanity
        df = df[(df["odds"] >= 1.01) & (df["odds"] <= 1000)]
        arbs = best_pairs(df)
        html_text = render_html(arbs)

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html_text, encoding="utf-8")
    print(f"Wrote: {OUTPUT_HTML}")

if __name__ == "__main__":
    main()
