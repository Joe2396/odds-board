# C:\epl-odds-model\src\app\odds_board.py
# Build an OddsChecker-style board + a top summary of best odds (Home/Draw/Away).

import os
import sys
import time
import json
from datetime import datetime, timezone
from typing import Dict, List

import requests
import pandas as pd

API_URL = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"
# Put your key here OR pass --api-key on the command line, OR set env ODDS_API_KEY
API_KEY = os.getenv("ODDS_API_KEY", "").strip()

# bookmaker_key -> display name
BOOKS: Dict[str, str] = {
    "skybet": "Sky Bet",
    "ladbrokes": "Ladbrokes",
    "williamhill": "William Hill",
    "betfair_sb_uk": "Betfair",
    "unibet_uk": "Unibet",
    "betvictor": "BetVictor",
    "boylesports": "BoyleSports",
    "casumo": "Casumo",
    # Add more here later…
}

REGION = "uk"
MARKET = "h2h"           # 1X2
ODDS_FORMAT = "decimal"  # we’ll keep everything decimal for math

OUT_DIR = os.path.join("data", "boards")


def fetch_book(book_key: str, book_name: str, api_key: str) -> pd.DataFrame:
    params = {
        "regions": REGION,
        "markets": MARKET,
        "oddsFormat": ODDS_FORMAT,
        "bookmakers": book_key,
        "apiKey": api_key,
    }
    print(f"[Fetch] {book_name:12s} -> {API_URL} params={params}")
    r = requests.get(API_URL, params=params, timeout=15)
    if r.status_code != 200:
        print(f"[Fetch] {book_name}: HTTP {r.status_code} | body: {r.text[:300]}")
        return pd.DataFrame()

    try:
        events = r.json()
    except json.JSONDecodeError:
        print(f"[Fetch] {book_name}: JSON decode error")
        return pd.DataFrame()

    rows: List[Dict] = []
    for ev in events:
        home = ev.get("home_team")
        away = ev.get("away_team")
        event_name = f"{home} vs {away}"
        commence = ev.get("commence_time")

        # Each event has bookmakers list; but since we filtered by one bookmaker,
        # there should be at most one entry with markets.
        for bm in ev.get("bookmakers", []):
            for mk in bm.get("markets", []):
                if mk.get("key") != MARKET:
                    continue
                for oc in mk.get("outcomes", []):
                    outcome = oc.get("name")   # e.g., "Arsenal", "Draw"
                    price = oc.get("price")
                    if outcome and price:
                        rows.append({
                            "event": event_name,
                            "home_team": home,
                            "away_team": away,
                            "commence_time": commence,
                            "outcome": outcome,
                            "bookmaker": book_name,
                            "odds_decimal": float(price),
                            "implied_prob": (1.0 / float(price)) if float(price) > 0 else None
                        })

    df = pd.DataFrame(rows)
    if not df.empty:
        # Sort for consistent display
        df["commence_time"] = pd.to_datetime(df["commence_time"], utc=True, errors="coerce")
        df = df.sort_values(["commence_time", "event", "bookmaker", "outcome"]).reset_index(drop=True)
    print(f"[Fetch] {book_name}: rows={len(df)}")
    return df


def build_board(all_df: pd.DataFrame) -> pd.DataFrame:
    """
    Pivot to bookmaker-wide grid: rows = event, columns = outcome within bookmaker.
    For a clean OddsChecker-style grid we pivot to columns=bookmaker, values=odds_decimal,
    but we keep one table per outcome. Then we'll concatenate.
    """
    # Wide grid: index=(event, commence), columns=bookmaker, values=odds_decimal,
    # but keep outcome as the first column for rendering.
    wide = (
        all_df
        .pivot_table(index=["event", "home_team", "away_team", "commence_time", "outcome"],
                     columns="bookmaker",
                     values="odds_decimal",
                     aggfunc="max")
        .reset_index()
    )
    # Sort outcomes in Home / Draw / Away order per match
    def outcome_sort_key(row):
        home = row["home_team"]
        away = row["away_team"]
        oc = row["outcome"]
        # desired order: home team name, Draw, away team name
        if oc == home:
            return 0
        if oc == "Draw":
            return 1
        if oc == away:
            return 2
        return 3

    wide = wide.sort_values(["commence_time", "event"], kind="mergesort")
    wide = wide.sort_values(by=["event", "outcome"], key=lambda s: s.apply(lambda _: 0), kind="mergesort")
    wide["_order"] = wide.apply(outcome_sort_key, axis=1)
    wide = wide.sort_values(["commence_time", "event", "_order"]).drop(columns=["_order"]).reset_index(drop=True)
    return wide


def best_price_summary(all_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each event, find the best price & book for Home / Draw / Away.
    """
    records = []
    for (event, home, away, commence), grp in all_df.groupby(["event", "home_team", "away_team", "commence_time"]):
        # map “logical outcomes”
        wanted = {home: "Home", "Draw": "Draw", away: "Away"}
        for logical, label in [(home, "Home"), ("Draw", "Draw"), (away, "Away")]:
            g = grp[grp["outcome"] == logical]
            if g.empty:
                records.append({
                    "event": event,
                    "commence_time": commence,
                    "side": label,
                    "best_odds": None,
                    "best_book": None
                })
                continue
            idx = g["odds_decimal"].idxmax()
            row = g.loc[idx]
            records.append({
                "event": event,
                "commence_time": commence,
                "side": label,
                "best_odds": row["odds_decimal"],
                "best_book": row["bookmaker"]
            })
    out = pd.DataFrame(records).pivot(index=["event", "commence_time"], columns="side", values=["best_odds", "best_book"])
    out.columns = [f"{lvl2}_{lvl1}" for lvl1, lvl2 in out.columns]  # e.g. Home_best_odds
    out = out.reset_index().sort_values(["commence_time", "event"])
    return out


def style_html(summary: pd.DataFrame, wide: pd.DataFrame) -> str:
    """
    Return an HTML page string with top summary table and bottom odds grid.
    """
    # Make copies for display
    sum_disp = summary.copy()
    sum_disp["commence_time"] = sum_disp["commence_time"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d %H:%M UTC")

    wide_disp = wide.copy()
    wide_disp["commence_time"] = wide_disp["commence_time"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d %H:%M UTC")

    # Prepare a Styler for wide grid where per event/outcome the max across bookmakers is highlighted
    book_cols = [c for c in wide_disp.columns if c not in ["event", "home_team", "away_team", "commence_time", "outcome"]]

    def highlight_row_max(row: pd.Series):
        vals = row[book_cols].astype(float, errors="ignore")
        try:
            m = vals.max()
        except Exception:
            return [""] * len(row)
        styles = []
        for c in row.index:
            if c in book_cols and pd.notnull(row[c]) and float(row[c]) == m:
                styles.append("border:2px solid #2ecc71; border-radius:6px;")
            else:
                styles.append("")
        return styles

    sty_wide = (
        wide_disp
        .style
        .set_properties(subset=book_cols, **{"text-align": "center", "padding": "6px"})
        .hide(axis="index")
        .apply(highlight_row_max, axis=1)
        .format(precision=2, na_rep="")
    )

    sty_sum = (
        sum_disp
        .style
        .hide(axis="index")
        .set_properties(**{"text-align": "center", "padding": "6px", "font-weight": "600"})
        .format(precision=2, na_rep="")
    )

    html_head = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Odds Board</title>
<style>
body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; }
h1 { margin: 0 0 12px 0; }
h2 { margin: 28px 0 8px 0; font-size: 18px; }
.small { color:#555; font-size: 12px; margin-bottom: 16px; }
table { border-collapse: separate !important; border-spacing: 0; }
th, td { border: 1px solid #eee; }
th { background:#fafafa; }
.event-header { margin-top: 12px; }
</style>
</head>
<body>
<h1>Odds Board</h1>
<div class="small">Updated: """ + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") + """</div>
<h2>Best Odds per Outcome</h2>
"""

    html = html_head + sty_sum.to_html() + "<h2 class='event-header'>Full Market (H2H)</h2>" + sty_wide.to_html() + "</body></html>"
    return html


def main():
    global API_KEY

    # allow --api-key XXXX
    if "--api-key" in sys.argv:
        try:
            API_KEY = sys.argv[sys.argv.index("--api-key") + 1]
        except Exception:
            pass

    if not API_KEY:
        print("ERROR: Provide an Odds API key via env ODDS_API_KEY or --api-key <KEY>.")
        sys.exit(1)

    frames = []
    for key, name in BOOKS.items():
        df = fetch_book(key, name, API_KEY)
        if not df.empty:
            frames.append(df)

    if not frames:
        print("No data returned from any bookmaker.")
        sys.exit(0)

    all_df = pd.concat(frames, ignore_index=True)

    # Build tables
    wide = build_board(all_df)
    summary = best_price_summary(all_df)

    # Console preview
    pd.set_option("display.width", 180)
    print("\n[Preview] Best per match (first 6 rows):")
    print(summary.head(6).to_string(index=False))

    print("\n[Preview] Wide grid (first 15 rows):")
    print(wide.head(15).to_string(index=False))

    # Save outputs
    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    html_path = os.path.join(OUT_DIR, f"odds_board_{stamp}.html")
    sum_csv = os.path.join(OUT_DIR, f"odds_summary_{stamp}.csv")
    wide_csv = os.path.join(OUT_DIR, f"odds_wide_{stamp}.csv")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(style_html(summary, wide))

    summary.to_csv(sum_csv, index=False)
    wide.to_csv(wide_csv, index=False)

    print(f"\n[Save] HTML  -> {html_path}")
    print(f"[Save] CSV   -> {sum_csv}")
    print(f"[Save] CSV   -> {wide_csv}")


if __name__ == "__main__":
    main()
