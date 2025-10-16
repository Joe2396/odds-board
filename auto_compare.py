# C:\epl-odds-model\src\app\auto_compare.py
import os
import time
import json
import requests
import pandas as pd
from datetime import datetime, timezone

API_KEY = "98fb91f398403151a3eece97dc514a0b"  # your key
SPORT = "soccer_epl"
REGION = "uk"
MARKET = "h2h"
ODDS_FORMAT = "decimal"

# The sportsbooks you’ve been using
BOOKMAKERS = [
    "williamhill",
    "skybet",
    "ladbrokes_uk",
    "betfair_sb_uk",
    "unibet_uk",
    "paddypower",
    "boylesports",
    "casumo",
    "betvictor",
]

OUTDIR = r"C:\epl-odds-model\data\auto"
os.makedirs(OUTDIR, exist_ok=True)

def fetch_odds() -> list:
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"
    params = {
        "regions": REGION,
        "markets": MARKET,
        "oddsFormat": ODDS_FORMAT,
        "bookmakers": ",".join(BOOKMAKERS),
        "apiKey": API_KEY,
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def to_long(events_json: list) -> pd.DataFrame:
    rows = []
    for ev in events_json:
        home = ev.get("home_team")
        away = ev.get("away_team")
        match = f"{home} vs {away}"
        start = ev.get("commence_time")
        bms = ev.get("bookmakers", [])
        for bm in bms:
            bm_key = bm.get("key")
            # markets: list with one dict where key == 'h2h'
            for m in bm.get("markets", []):
                if m.get("key") != "h2h":
                    continue
                for oc in m.get("outcomes", []):
                    rows.append({
                        "event": match,
                        "home_team": home,
                        "away_team": away,
                        "commence_time": start,
                        "bookmaker": bm_key,
                        "outcome": oc.get("name"),
                        "odds_decimal": oc.get("price"),
                    })
    df = pd.DataFrame(rows)
    # Clean up / order
    if not df.empty:
        df["commence_time"] = pd.to_datetime(df["commence_time"], utc=True)
        df = df.sort_values(["commence_time", "event", "bookmaker", "outcome"])
    return df

def long_to_wide(df: pd.DataFrame) -> pd.DataFrame:
    # Wide per outcome (rows) with columns per bookmaker
    wide = df.pivot_table(
        index=["event", "outcome", "commence_time"],
        columns="bookmaker",
        values="odds_decimal",
        aggfunc="max",
    ).reset_index()
    # Order bookmakers columns
    cols = ["event", "outcome", "commence_time"] + [c for c in BOOKMAKERS if c in wide.columns]
    wide = wide.reindex(columns=cols)
    return wide

def add_best_cols(wide: pd.DataFrame) -> pd.DataFrame:
    bm_cols = [c for c in wide.columns if c not in ("event", "outcome", "commence_time")]
    # Row-wise best odds + best_bookmaker
    wide["best_price"] = wide[bm_cols].max(axis=1, skipna=True)
    wide["best_book"] = wide[bm_cols].idxmax(axis=1)
    wide["best_minus_other"] = wide["best_price"] - wide[bm_cols].apply(
        lambda row: row[row.index != row.idxmax()].max(skipna=True), axis=1
    )
    return wide

def style_html(wide: pd.DataFrame) -> str:
    bm_cols = [c for c in wide.columns if c not in ("event", "outcome", "commence_time", "best_price", "best_book", "best_minus_other")]
    def highlight_max(s):
        is_max = s == s.max(skipna=True)
        return ["font-weight:bold; background-color:#e6ffe6" if v else "" for v in is_max]

    styled = (
        wide.rename(columns={"commence_time": "kickoff"})
            .sort_values(["kickoff", "event", "outcome"])
            .style
            .format({c: "{:.2f}" for c in bm_cols + ["best_price", "best_minus_other"]})
            .apply(highlight_max, subset=bm_cols, axis=1)
            .hide(axis="index")
    )
    return styled.to_html()

def run_once():
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    try:
        data = fetch_odds()
    except Exception as e:
        print("[ERROR] Fetch failed:", e)
        return

    df_long = to_long(data)
    long_path = os.path.join(OUTDIR, f"odds_long_{ts}.csv")
    df_long.to_csv(long_path, index=False)
    print(f"[Save] long -> {long_path} ({len(df_long)} rows)")

    if df_long.empty:
        print("[Warn] No odds returned.")
        return

    df_wide = long_to_wide(df_long)
    df_wide = add_best_cols(df_wide)

    wide_path = os.path.join(OUTDIR, f"odds_wide_{ts}.csv")
    df_wide.to_csv(wide_path, index=False)
    print(f"[Save] wide -> {wide_path} ({len(df_wide)} rows)")

    # HTML (best-highlighted)
    html = style_html(df_wide)
    html_path = os.path.join(OUTDIR, f"odds_board_{ts}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[Save] html -> {html_path}")

    # convenience file that always points to latest
    latest_html = os.path.join(OUTDIR, "latest.html")
    with open(latest_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[Save] latest -> {latest_html}")

def run_loop(interval_minutes: int = 60):
    print(f"[Loop] Refreshing every {interval_minutes} min. Ctrl+C to stop.")
    while True:
        run_once()
        time.sleep(interval_minutes * 60)

if __name__ == "__main__":
    # Option A: run once (use Windows Task Scheduler hourly)
    run_once()

    # Option B: uncomment to run forever inside Python
    # run_loop(interval_minutes=60)
