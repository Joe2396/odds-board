# -*- coding: utf-8 -*-
"""
Builds an EPL "Odds Checker" sitelet:
- Index page (card list of fixtures)
- Per-fixture pages with: Match Result (1X2) odds + Total Goals odds (by line)
Outputs to: data/auto/odds_checker/
"""

import html, re, unicodedata
from pathlib import Path
from datetime import datetime, timezone
import requests
import pandas as pd
from collections import defaultdict

# ----- CONFIG -----
API_KEY = "8e8a4a2421e95ad2fb0df450c88ef6c6"  # rotate later if needed
SPORT = "soccer_epl"
REGIONS = "uk"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

OUT_DIR = Path("data/auto/odds_checker")
THEME_BG = "#0F1621"
TXT = "#E2E8F0"

# Normalize a few bookmaker titles so they group nicely
BOOK_NAME_MAP = {
    "Sky Bet": "SkyBet",
    "Betfair": "Betfair Sportsbook",  # keep exchange separate if needed
    "Paddy Power": "PaddyPower",
}
BOOK_PRIORITY = [
    "PaddyPower","Betfair Sportsbook","William Hill","Ladbrokes","SkyBet",
    "Unibet","BetVictor","BoyleSports","Casumo","Grosvenor","LeoVegas","Matchbook",
    "Coral","Smarkets","888sport","LiveScore Bet","Virgin Bet","Betway"
]

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

def fetch(markets):
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"
    params = dict(apiKey=API_KEY, regions=REGIONS, markets=",".join(markets),
                  oddsFormat=ODDS_FORMAT, dateFormat=DATE_FORMAT)
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise SystemExit(f"HTTP {r.status_code}: {r.text}")
    return r.json()

def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii","ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text

def tidy_book(name):
    return BOOK_NAME_MAP.get(name, name)

# ---------- Build DataFrames ----------
def df_h2h(json_data):
    rows=[]
    for g in json_data:
        gid=g["id"]; t=g["commence_time"]; home=g["home_team"]; away=g["away_team"]
        for b in g.get("bookmakers",[]):
            book=tidy_book(b.get("title"))
            for m in b.get("markets",[]):
                if m.get("key")!="h2h": continue
                for o in m.get("outcomes",[]):
                    name=o.get("name")
                    price=o.get("price")
                    if not name or price is None: continue
                    if name==home: side="Home"
                    elif name==away: side="Away"
                    elif name.lower()=="draw": side="Draw"
                    else: continue
                    rows.append({"event_id":gid,"time":t,"home":home,"away":away,
                                 "book":book,"market":"h2h","side":side,"odds":float(price)})
    df=pd.DataFrame(rows)
    if not df.empty:
        df=df[(df["odds"]>=1.01)&(df["odds"]<=1000)]
    return df

def df_totals(json_data):
    rows=[]
    for g in json_data:
        gid=g["id"]; t=g["commence_time"]; home=g["home_team"]; away=g["away_team"]
        for b in g.get("bookmakers",[]):
            book=tidy_book(b.get("title"))
            for m in b.get("markets",[]):
                if m.get("key")!="totals": continue
                for o in m.get("outcomes",[]):
                    name=(o.get("name") or "").title()
                    point=o.get("point"); price=o.get("price")
                    if name not in ("Over","Under") or point is None or price is None: continue
                    rows.append({"event_id":gid,"time":t,"home":home,"away":away,
                                 "book":book,"market":"totals","line":float(point),
                                 "side":name,"odds":float(price)})
    df=pd.DataFrame(rows)
    if not df.empty:
        df=df[(df["odds"]>=1.01)&(df["odds"]<=1000)]
    return df

# ---------- Rendering helpers ----------
def chips(all_items, best_val):
    # Render chips like "Book @ 2.05", best highlighted
    chips=[]
    for i,(bk,od) in enumerate(all_items):
        pill = (i==0 and od==best_val)
        style = "background:#10B98122;border:1px solid #10B98155;" if pill else "background:#111827;border:1px solid #1F2937;"
        chips.append(f"<span style='{style}border-radius:10px;padding:2px 8px;display:inline-block;margin:2px 6px 2px 0;'>{html.escape(bk)} @ {od}</span>")
    return "".join(chips)

def render_fixture_page(fx, h2h_rows, totals_rows):
    ts=now_iso()
    header=f"""
    <div style="color:{TXT};background:{THEME_BG};padding:24px;font-family:Inter,system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
      <a href="index.html" style="color:#93C5FD;text-decoration:none;">← All fixtures</a>
      <h1 style="margin:8px 0 0 0;">{html.escape(fx['home'])} vs {html.escape(fx['away'])}</h1>
      <p style="opacity:0.8;margin:6px 0 18px 0;">Kickoff (UTC): {html.escape(fx['time'])} · Updated: {ts}</p>
    """

    # 1X2 table
    h2h_html=""
    if not h2h_rows.empty:
        all_map=defaultdict(list)
        for _,r in h2h_rows.sort_values(["side","odds"], ascending=[True,False]).iterrows():
            all_map[r["side"]].append((r["book"], r["odds"]))
        best = (h2h_rows.sort_values(["side","odds"], ascending=[True,False])
                .groupby("side", as_index=False).first()
                .rename(columns={"book":"best_book","odds":"best_odds"}))
        tr=[]
        for side in ["Home","Draw","Away"]:
            row=h2h_rows[h2h_rows["side"]==side]
            if row.empty: continue
            b=best[best["side"]==side].iloc[0]
            tr.append(f"""
              <tr>
                <td>{side}</td>
                <td><strong>{b['best_odds']}</strong> @ {html.escape(str(b['best_book']))}</td>
                <td style="max-width:720px;">{chips(all_map[side], b['best_odds'])}</td>
              </tr>
            """)
        h2h_html=f"""
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
            <tbody>{''.join(tr)}</tbody>
          </table>
        </div>
        """

    # Totals block (grouped by exact line)
    totals_html=""
    if not totals_rows.empty:
        blocks=[]
        for line, sub in totals_rows.groupby("line"):
            sub=sub.copy()
            over_list = sub[sub["side"]=="Over"].sort_values("odds", ascending=False)[["book","odds"]].values.tolist()
            under_list = sub[sub["side"]=="Under"].sort_values("odds", ascending=False)[["book","odds"]].values.tolist()
            best_over = over_list[0][1] if over_list else None
            best_under = under_list[0][1] if under_list else None
            blocks.append(f"""
              <div style="margin:12px 0 18px 0;">
                <h3 style="margin:0 0 8px 0;">Total Goals {line:+.1f}</h3>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                  <div>
                    <div style="opacity:0.8;margin-bottom:6px;">Over</div>
                    {chips(over_list, best_over) if over_list else "<em>No prices</em>"}
                  </div>
                  <div>
                    <div style="opacity:0.8;margin-bottom:6px;">Under</div>
                    {chips(under_list, best_under) if under_list else "<em>No prices</em>"}
                  </div>
                </div>
              </div>
            """)
        totals_html=f"""
        <h2 style="margin:8px 0 8px 0;">Total Goals (Over/Under)</h2>
        <div style="border:1px solid #1F2937;border-radius:12px;padding:12px;">
          {''.join(blocks)}
        </div>
        """

    body = header + h2h_html + totals_html + "</div>"
    return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'></head><body>{body}</body></html>"

def render_index(fixtures):
    ts = now_iso()

    # group fixtures by YYYY-MM-DD
    by_date = {}
    for fx in sorted(fixtures, key=lambda x: (x["time"][:10], x["time"])):
        by_date.setdefault(fx["time"][:10], []).append(fx)

    def card(fx):
        return f"""
        <a href="{html.escape(fx['slug'])}.html" style="text-decoration:none;color:inherit;">
          <div style="background:#111827;border:1px solid #1F2937;border-radius:14px;padding:14px;display:flex;justify-content:space-between;align-items:center;gap:10px;">
            <div>
              <div style="font-weight:600">{html.escape(fx['home'])}</div>
              <div style="opacity:0.85">vs</div>
              <div style="font-weight:600">{html.escape(fx['away'])}</div>
            </div>
            <div style="opacity:0.85;white-space:nowrap;">{html.escape(fx['time'])} UTC</div>
          </div>
        </a>
        """

    sections = []
    for date, games in by_date.items():
        sections.append(f"""
          <h2 style="margin:18px 0 10px 0;">{html.escape(date)}</h2>
          <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;">
            {''.join(card(fx) for fx in games)}
          </div>
        """)

    page = f"""
    <div style="color:{TXT};background:{THEME_BG};padding:24px;font-family:Inter,system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
      <h1 style="margin:0 0 6px 0;">EPL Odds Checker</h1>
      <p style="opacity:0.8;margin:0 0 16px 0;">Click a fixture to view Match Result & Total Goals odds. Updated: {ts}</p>
      {''.join(sections)}
    </div>
    """
    return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'></head><body>{page}</body></html>"

# ---------- Main ----------
def main():
    # Pull both markets
    data = fetch(["h2h","totals"])
    # Build DataFrames
    df1 = df_h2h(data)
    df2 = df_totals(data)

    # Fixture list from union of both
    all_games = pd.concat(
        [df1[["event_id","time","home","away"]],
         df2[["event_id","time","home","away"]]],
        ignore_index=True
    ).drop_duplicates()

    fixtures=[]
    for _,g in all_games.iterrows():
        slug = f"{g['time'][:10]}-{slugify(g['home'])}-vs-{slugify(g['away'])}"
        fixtures.append({"event_id":g["event_id"],"time":g["time"],"home":g["home"],"away":g["away"],"slug":slug})

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Per-fixture pages
    for fx in fixtures:
        h2h_rows = df1[df1["event_id"]==fx["event_id"]][["side","book","odds"]]
        totals_rows = df2[df2["event_id"]==fx["event_id"]][["line","side","book","odds"]]
        page = render_fixture_page(fx, h2h_rows, totals_rows)
        (OUT_DIR / f"{fx['slug']}.html").write_text(page, encoding="utf-8")

    # Index page
    index_html = render_index(fixtures)
    (OUT_DIR / "index.html").write_text(index_html, encoding="utf-8")
    print(f"Wrote {len(fixtures)} fixture pages + index to {OUT_DIR}")

if __name__ == "__main__":
    main()

