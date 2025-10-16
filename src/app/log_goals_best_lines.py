# -*- coding: utf-8 -*-
"""
EPL Goals Totals (Over/Under) – Best Lines Logger (with all-book odds display)
"""

import html
from pathlib import Path
from datetime import datetime, timezone
import requests
import pandas as pd

# ====== CONFIG ======
API_KEY = "98fb91f398403151a3eece97dc514a0b"
SPORT = "soccer_epl"
REGIONS = "uk"
MARKETS = "totals"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

OUTPUT_DIR = Path("data/auto")
CSV_PATH = OUTPUT_DIR / "goals_best_lines_latest.csv"
HTML_PATH = OUTPUT_DIR / "goals_best_lines_latest.html"

BOOK_PRIORITY = [
    "PaddyPower","Betfair","Betfair Sportsbook","William Hill",
    "Ladbrokes","SkyBet","Unibet","BetVictor","BoyleSports","Casumo",
    "LeoVegas","Matchbook"  # add any others you’re seeing
]

def now_utc_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

def fetch_totals():
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"
    params = dict(
        apiKey=API_KEY, regions=REGIONS, markets=MARKETS,
        oddsFormat=ODDS_FORMAT, dateFormat=DATE_FORMAT
    )
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise SystemExit(f"HTTP {r.status_code}: {r.text}")
    return r.json()

def to_long(json_data: list) -> pd.DataFrame:
    rows = []
    for game in json_data:
        gid = game.get("id")
        commence = game.get("commence_time")
        home = game.get("home_team")
        away = game.get("away_team")
        for b in game.get("bookmakers", []):
            book = b.get("title")
            last = b.get("last_update") or commence
            for m in b.get("markets", []):
                if m.get("key") != "totals":
                    continue
                for o in m.get("outcomes", []):
                    name = (o.get("name") or "").strip().title()
                    if name not in ("Over", "Under"):
                        continue
                    line = o.get("point")
                    price = o.get("price")
                    if line is None or price is None:
                        continue
                    rows.append({
                        "event_id": gid,
                        "commence_time": commence,
                        "home_team": home,
                        "away_team": away,
                        "bookmaker": book,
                        "line": float(line),
                        "side": name,              # Over / Under
                        "odds": float(price),
                        "last_update": last
                    })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df[(df["odds"] >= 1.01) & (df["odds"] <= 1000)]
    return df

def summarize(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: 
        return df

    # book order for tie-breaks
    df["book_order"] = df["bookmaker"].apply(
        lambda b: BOOK_PRIORITY.index(b) if b in BOOK_PRIORITY else len(BOOK_PRIORITY)
    )

    key = ["event_id","commence_time","home_team","away_team","line"]

    # Best Over/Under tables
    over_best = (df[df["side"]=="Over"]
                 .sort_values(["odds","book_order"], ascending=[False, True])
                 .groupby(key, as_index=False)
                 .first()
                 .rename(columns={"bookmaker":"over_book","odds":"over_odds"}))

    under_best = (df[df["side"]=="Under"]
                  .sort_values(["odds","book_order"], ascending=[False, True])
                  .groupby(key, as_index=False)
                  .first()
                  .rename(columns={"bookmaker":"under_book","odds":"under_odds"}))

    base = pd.merge(over_best, under_best, on=key, how="inner")

    # Build “all odds” lists per side
    def pack_all(group, side):
        g = group[group["side"]==side].copy()
        # sort high to low odds, then by book priority
        g = g.sort_values(["odds","book_order"], ascending=[False, True])
        return [{"book": r.bookmaker, "odds": r.odds} for r in g.itertuples()]

    records = []
    for grp_vals, grp_df in df.groupby(key, as_index=False):
        # grp_vals is a Series matching key columns
        event = {k: grp_vals[k] for k in key} if isinstance(grp_vals, pd.Series) else dict(zip(key, grp_vals))
        rec = {**event}
        over_all = pack_all(grp_df, "Over")
        under_all = pack_all(grp_df, "Under")
        rec["over_all"] = over_all
        rec["under_all"] = under_all
        records.append(rec)
    all_df = pd.DataFrame(records)

    # merge best with the all-odds blobs
    out = pd.merge(base, all_df, on=key, how="left")

    # diagnostics
    out["sum_implied"] = 1.0/out["over_odds"] + 1.0/out["under_odds"]
    out["margin_pct"] = (out["sum_implied"] - 1.0) * 100.0
    out["is_arb"] = out["sum_implied"] < 1.0

    # tidy
    out["line"] = out["line"].round(2)
    out["sum_implied"] = out["sum_implied"].round(4)
    out["margin_pct"] = out["margin_pct"].round(2)

    # order tightest first
    out = out.sort_values(["margin_pct","commence_time","home_team","line"], ascending=[True, True, True, True])
    return out

def odds_list_html(items, best_value):
    # Render list of "Book @ 2.05" with the top one highlighted
    chips = []
    for i, it in enumerate(items):
        txt = f"{html.escape(it['book'])} @ {it['odds']}"
        if it["odds"] == best_value and i == 0:
            chips.append(f"<span style='background:#10B98122;border:1px solid #10B98155;border-radius:10px;padding:2px 8px;display:inline-block;margin:2px 6px 2px 0;'><strong>{txt}</strong></span>")
        else:
            chips.append(f"<span style='background:#111827;border:1px solid #1F2937;border-radius:10px;padding:2px 8px;display:inline-block;margin:2px 6px 2px 0;'>{txt}</span>")
    return "".join(chips)

def render_html(df: pd.DataFrame) -> str:
    ts = now_utc_iso()
    header = f"""
    <div style="color:#E2E8F0;background:#0F1621;padding:24px;font-family:Inter,system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
      <h2 style="margin:0 0 8px 0;">EPL Goals Totals — Best Lines (All Books)</h2>
      <p style="opacity:0.8;margin:0 0 16px 0;">Last updated: {html.escape(ts)}</p>
    """
    if df.empty:
        body = header + "<p>No totals available right now.</p></div>"
        return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'></head><body>{body}</body></html>"

    rows = []
    for _, r in df.iterrows():
        fixture = f"{r['home_team']} vs {r['away_team']}"
        line = f"{r['line']:+.1f} goals"

        over_all_html = odds_list_html(r["over_all"], r["over_odds"])
        under_all_html = odds_list_html(r["under_all"], r["under_odds"])

        rows.append(f"""
          <tr>
            <td>{html.escape(r['commence_time'])}</td>
            <td>{html.escape(fixture)}</td>
            <td>{html.escape(line)}</td>
            <td><strong>{r['over_odds']}</strong> @ {html.escape(str(r['over_book']))}</td>
            <td><strong>{r['under_odds']}</strong> @ {html.escape(str(r['under_book']))}</td>
            <td style="text-align:right;">{r['sum_implied']}</td>
            <td style="text-align:right;">{r['margin_pct']}%</td>
            <td style="max-width:420px;">{over_all_html}</td>
            <td style="max-width:420px;">{under_all_html}</td>
          </tr>
        """)

    table = f"""
    {header}
      <div style="overflow:auto;border:1px solid #1F2937;border-radius:12px;">
        <table style="width:100%;border-collapse:collapse;min-width:1200px;">
          <thead>
            <tr style="background:#111827;">
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Commence (UTC)</th>
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Fixture</th>
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Line</th>
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Best Over</th>
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Best Under</th>
              <th style="text-align:right;padding:12px;border-bottom:1px solid #1F2937;">Σ implied</th>
              <th style="text-align:right;padding:12px;border-bottom:1px solid #1F2937;">Margin</th>
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">All Over (sorted)</th>
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">All Under (sorted)</th>
            </tr>
          </thead>
          <tbody>
            {''.join(rows)}
          </tbody>
        </table>
      </div>
      <p style="opacity:0.7;margin-top:12px;font-size:12px;">
        Lists show all bookmakers’ prices, highest highlighted. Margin = (1/Over + 1/Under - 1). Negative = arbitrage.
      </p>
    </div>
    """
    return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'></head><body>{table}</body></html>"

def main():
    json_data = fetch_totals()
    df_long = to_long(json_data)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if df_long.empty:
        pd.DataFrame().to_csv(CSV_PATH, index=False, encoding="utf-8")
        HTML_PATH.write_text(render_html(pd.DataFrame()), encoding="utf-8")
        print(f"Wrote empty outputs to: {CSV_PATH} and {HTML_PATH}")
        return

    summary = summarize(df_long)

    # Flatten “all odds” lists into string columns for the CSV
    def fmt(items): 
        return "; ".join([f"{i['book']}@{i['odds']}" for i in items])

    csv_df = summary.drop(columns=["over_all","under_all"]).copy()
    csv_df["over_all"] = summary["over_all"].apply(fmt)
    csv_df["under_all"] = summary["under_all"].apply(fmt)

    csv_df.to_csv(CSV_PATH, index=False, encoding="utf-8")
    HTML_PATH.write_text(render_html(summary), encoding="utf-8")
    print(f"Wrote:\n  {CSV_PATH}\n  {HTML_PATH}")

if __name__ == "__main__":
    main()
