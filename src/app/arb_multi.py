# -*- coding: utf-8 -*-
"""
Multi-League Multi-Market Arbitrage Finder – EU books via The Odds API.

Markets:
- Match Result (1X2 / h2h)
- Goals Totals (Over/Under)
"""

import html
from pathlib import Path
from datetime import datetime, timezone
import requests
import pandas as pd

# ===== CONFIG =====
API_KEY = "YOUR_API_KEY"
REGIONS = "eu"
MARKETS = "h2h,totals"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"

BANKROLL = 100.0
STALE_MIN = 240
TIMEOUT = 20

OUTPUT_DIR = Path("data/auto/arbitrage")

LEAGUES = {
    "Premier League": "soccer_epl",
    "La Liga": "soccer_spain_la_liga",
    "Bundesliga": "soccer_germany_bundesliga",
    "Serie A": "soccer_italy_serie_a",
    "Champions League": "soccer_uefa_champs_league",
}

BOOK_PRIORITY = [
    "PaddyPower", "Betfair", "Betfair Sportsbook", "William Hill",
    "Ladbrokes", "SkyBet", "Unibet", "BetVictor", "BoyleSports", "Casumo"
]

# ===== HELPERS =====
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def fetch_all(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = dict(
        apiKey=API_KEY,
        regions=REGIONS,
        markets=MARKETS,
        oddsFormat=ODDS_FORMAT,
        dateFormat=DATE_FORMAT,
    )
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise SystemExit(f"{sport_key} → HTTP {r.status_code}: {r.text}")
    return r.json()


def json_to_long(df_json):
    rows = []
    for game in df_json:
        gid = game.get("id")
        commence = game.get("commence_time")
        home = game.get("home_team")
        away = game.get("away_team")
        for b in game.get("bookmakers", []):
            book = b.get("title")
            last = b.get("last_update") or commence
            for m in b.get("markets", []):
                if m.get("key") not in ("h2h", "totals"):
                    continue
                for o in m.get("outcomes", []):
                    if o.get("price") is None:
                        continue
                    rows.append({
                        "event_id": gid,
                        "commence_time": commence,
                        "home_team": home,
                        "away_team": away,
                        "bookmaker": book,
                        "market": m.get("key"),
                        "outcome": o.get("name"),
                        "line": o.get("point"),
                        "odds": float(o.get("price")),
                        "last_update": last,
                    })
    return pd.DataFrame(rows)


def _book_order(book):
    return BOOK_PRIORITY.index(book) if book in BOOK_PRIORITY else len(BOOK_PRIORITY)

# ===== ARBITRAGE LOGIC (UNCHANGED) =====
def parse_1x2(df):
    if df.empty:
        return df
    df = df[df["market"] == "h2h"].copy()
    if df.empty:
        return df

    df["book_order"] = df["bookmaker"].apply(_book_order)

    def classify(row):
        if row["outcome"] == "Draw":
            return "draw"
        if row["outcome"] == row["home_team"]:
            return "home"
        if row["outcome"] == row["away_team"]:
            return "away"
        return None

    df["side"] = df.apply(classify, axis=1)
    df = df[df["side"].notna()]

    best = (
        df.sort_values(["odds", "book_order"], ascending=[False, True])
        .groupby(["event_id", "commence_time", "home_team", "away_team", "side"])
        .first()
        .reset_index()
    )

    pivot = best.pivot(
        index=["event_id", "commence_time", "home_team", "away_team"],
        columns="side",
        values=["odds", "bookmaker"],
    )
    pivot.columns = [f"{a}_{b}" for a, b in pivot.columns]
    pivot = pivot.dropna().reset_index()

    pivot["sum_imp"] = (
        1 / pivot["odds_home"]
        + 1 / pivot["odds_draw"]
        + 1 / pivot["odds_away"]
    )
    pivot = pivot[pivot["sum_imp"] < 1]

    B = BANKROLL
    pivot["stake_home"] = (B / pivot["odds_home"] / pivot["sum_imp"]).round(2)
    pivot["stake_draw"] = (B / pivot["odds_draw"] / pivot["sum_imp"]).round(2)
    pivot["stake_away"] = (B / pivot["odds_away"] / pivot["sum_imp"]).round(2)
    pivot["roi_pct"] = ((1 - pivot["sum_imp"]) * 100).round(2)

    return pivot.sort_values("roi_pct", ascending=False)


def parse_totals(df):
    if df.empty:
        return df
    df = df[df["market"] == "totals"].copy()
    df = df.dropna(subset=["line"])

    df["side"] = df["outcome"].str.lower().apply(
        lambda x: "over" if "over" in x else "under"
    )

    grouped = ["event_id", "commence_time", "home_team", "away_team", "line"]

    over = df[df["side"] == "over"].sort_values("odds", ascending=False).groupby(grouped).first().reset_index()
    under = df[df["side"] == "under"].sort_values("odds", ascending=False).groupby(grouped).first().reset_index()

    out = over.merge(under, on=grouped, suffixes=("_over", "_under"))
    out["sum_imp"] = 1 / out["odds_over"] + 1 / out["odds_under"]
    out = out[out["sum_imp"] < 1]

    B = BANKROLL
    out["stake_over"] = (B / out["odds_over"] / out["sum_imp"]).round(2)
    out["stake_under"] = (B / out["odds_under"] / out["sum_imp"]).round(2)
    out["roi_pct"] = ((1 - out["sum_imp"]) * 100).round(2)

    return out.sort_values("roi_pct", ascending=False)

# ===== HTML =====
def render_page(league, arbs_1x2, arbs_totals):
    ts = now_iso()
    return f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="background:#0F1621;color:#E2E8F0;font-family:Inter,system-ui;padding:24px;">
<h1>{league} Arbitrage</h1>
<p style="opacity:.7">Last updated {ts} · Bankroll £{BANKROLL:.0f}</p>
<h2>1X2</h2>
<pre>{arbs_1x2.to_string(index=False) if not arbs_1x2.empty else "No opportunities"}</pre>
<h2>Totals</h2>
<pre>{arbs_totals.to_string(index=False) if not arbs_totals.empty else "No opportunities"}</pre>
</body>
</html>
"""


def render_index():
    links = "".join(
        f"<li><a href='{k.lower().replace(' ','_')}.html'>{k}</a></li>"
        for k in LEAGUES
    )
    return f"""
<!doctype html>
<html>
<body style="background:#0F1621;color:#E2E8F0;padding:24px;">
<h1>Arbitrage Boards</h1>
<ul>{links}</ul>
</body>
</html>
"""

# ===== MAIN =====
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for league, sport_key in LEAGUES.items():
        print(f"Processing {league}")
        data = fetch_all(sport_key)
        df = json_to_long(data)

        if not df.empty:
            ts = pd.to_datetime(df["last_update"], errors="coerce", utc=True)
            cutoff = pd.Timestamp.utcnow() - pd.Timedelta(minutes=STALE_MIN)
            df = df[ts.isna() | (ts >= cutoff)]
            df = df[(df["odds"] >= 1.01) & (df["odds"] <= 1000)]

        arbs_1x2 = parse_1x2(df)
        arbs_totals = parse_totals(df)

        slug = league.lower().replace(" ", "_")
        (OUTPUT_DIR / f"{slug}.html").write_text(
            render_page(league, arbs_1x2, arbs_totals),
            encoding="utf-8"
        )

    (OUTPUT_DIR / "index.html").write_text(render_index(), encoding="utf-8")
    print("Arbitrage boards generated.")


if __name__ == "__main__":
    main()
