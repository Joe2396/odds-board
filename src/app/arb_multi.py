# -*- coding: utf-8 -*-
"""
EPL Multi-Market Arbitrage Finder – UK books via The Odds API.

Markets covered in this version:
- Match Result (1X2 / h2h)
- Goals Totals (Over/Under)

Output: data/auto/arb_latest.html
"""

import html
from pathlib import Path
from datetime import datetime, timezone
import requests
import pandas as pd

# ===== CONFIG =====
API_KEY = "8e8a4a2421e95ad2fb0df450c88ef6c6"
SPORT = "soccer_epl"
REGIONS = "uk"
# IMPORTANT: ONLY markets supported by /odds here
MARKETS = "h2h,totals"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"

BANKROLL = 100.0            # bankroll used for stake splits
STALE_MIN = 240             # ignore very old markets (if timestamps present)
OUTPUT_HTML = Path("data/auto/arb_latest.html")
TIMEOUT = 20

BOOK_PRIORITY = [
    "PaddyPower", "Betfair", "Betfair Sportsbook", "William Hill",
    "Ladbrokes", "SkyBet", "Unibet", "BetVictor", "BoyleSports", "Casumo"
]


# ===== HELPERS =====
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def fetch_all():
    """
    Fetch EPL odds for supported markets using The Odds API.
    """
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"
    params = dict(
        apiKey=API_KEY,
        regions=REGIONS,
        markets=MARKETS,
        oddsFormat=ODDS_FORMAT,
        dateFormat=DATE_FORMAT,
    )
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise SystemExit(f"HTTP {r.status_code}: {r.text}")
    return r.json()


def json_to_long(df_json):
    """
    Flatten API JSON to rows:
      one row per (event, bookmaker, market, outcome).
    """
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
                mkey = m.get("key")
                if mkey not in ("h2h", "totals"):
                    continue
                for o in m.get("outcomes", []):
                    price = o.get("price")
                    name = o.get("name")
                    line = o.get("point")
                    if price is None:
                        continue
                    rows.append(
                        {
                            "event_id": gid,
                            "commence_time": commence,
                            "home_team": home,
                            "away_team": away,
                            "bookmaker": book,
                            "market": mkey,
                            "outcome": name,
                            "line": line,
                            "odds": float(price),
                            "last_update": last,
                        }
                    )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _book_order(book: str) -> int:
    return BOOK_PRIORITY.index(book) if book in BOOK_PRIORITY else len(BOOK_PRIORITY)


# ===== 1X2 ARBITRAGE (H2H) =====
def parse_1x2(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df[df["market"] == "h2h"].copy()
    if df.empty:
        return df

    df["book_order"] = df["bookmaker"].apply(_book_order)

    # Outcomes: home, away, draw (names are usually the team names or "Draw")
    def classify_side(row):
        name = (row["outcome"] or "").strip()
        if name.lower() == "draw":
            return "draw"
        if name == row["home_team"]:
            return "home"
        if name == row["away_team"]:
            return "away"
        # fallback: best guess using substring
        nlow = name.lower()
        if row["home_team"] and row["home_team"].lower() in nlow:
            return "home"
        if row["away_team"] and row["away_team"].lower() in nlow:
            return "away"
        return "other"

    df["side"] = df.apply(classify_side, axis=1)
    df = df[df["side"].isin(["home", "draw", "away"])]

    if df.empty:
        return df

    grouped_cols = ["event_id", "commence_time", "home_team", "away_team"]

    best = (
        df.sort_values(["odds", "book_order"], ascending=[False, True])
        .groupby(grouped_cols + ["side"], as_index=False)
        .first()
    )

    # pivot into columns for home/draw/away
    pivot = best.pivot_table(
        index=grouped_cols,
        columns="side",
        values=["odds", "bookmaker"],
        aggfunc="first",
    )

    # flatten column MultiIndex
    pivot.columns = [f"{a}_{b}" for a, b in pivot.columns.to_flat_index()]
    pivot = pivot.reset_index()

    # require all three legs present
    required_cols = ["odds_home", "odds_draw", "odds_away"]
    for c in required_cols:
        if c not in pivot.columns:
            return pd.DataFrame()
    pivot = pivot.dropna(subset=required_cols)

    # arb calc
    pivot["sum_imp"] = (
        1.0 / pivot["odds_home"] + 1.0 / pivot["odds_draw"] + 1.0 / pivot["odds_away"]
    )
    pivot["is_arb"] = pivot["sum_imp"] < 1.0
    if not pivot["is_arb"].any():
        return pd.DataFrame()

    B = BANKROLL
    pivot["stake_home"] = ((B / pivot["odds_home"]) / pivot["sum_imp"]).round(2)
    pivot["stake_draw"] = ((B / pivot["odds_draw"]) / pivot["sum_imp"]).round(2)
    pivot["stake_away"] = ((B / pivot["odds_away"]) / pivot["sum_imp"]).round(2)
    pivot["roi_pct"] = ((1.0 - pivot["sum_imp"]) * 100.0).round(2)

    pivot["book_home"] = pivot.get("bookmaker_home", "")
    pivot["book_draw"] = pivot.get("bookmaker_draw", "")
    pivot["book_away"] = pivot.get("bookmaker_away", "")

    cols = [
        "event_id",
        "commence_time",
        "home_team",
        "away_team",
        "odds_home",
        "odds_draw",
        "odds_away",
        "book_home",
        "book_draw",
        "book_away",
        "stake_home",
        "stake_draw",
        "stake_away",
        "roi_pct",
    ]
    return pivot[cols].sort_values("roi_pct", ascending=False)


# ===== TOTALS ARBITRAGE (OVER/UNDER) =====
def parse_totals(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df[df["market"] == "totals"].copy()
    if df.empty:
        return df

    df["book_order"] = df["bookmaker"].apply(_book_order)

    # classify over/under
    def side_from_name(name: str) -> str:
        n = (name or "").strip().lower()
        if "over" in n:
            return "over"
        if "under" in n:
            return "under"
        return "other"

    df["side"] = df["outcome"].apply(side_from_name)
    df = df[df["side"].isin(["over", "under"])]
    df = df.dropna(subset=["line"])

    grouped = ["event_id", "commence_time", "home_team", "away_team", "line"]

    over = (
        df[df["side"] == "over"]
        .sort_values(["odds", "book_order"], ascending=[False, True])
        .groupby(grouped, as_index=False)
        .first()
        .rename(columns={"bookmaker": "over_book", "odds": "over_odds"})
    )

    under = (
        df[df["side"] == "under"]
        .sort_values(["odds", "book_order"], ascending=[False, True])
        .groupby(grouped, as_index=False)
        .first()
        .rename(columns={"bookmaker": "under_book", "odds": "under_odds"})
    )

    out = pd.merge(
        over,
        under,
        on=["event_id", "commence_time", "home_team", "away_team", "line"],
        how="inner",
    )

    if out.empty:
        return out

    out["sum_imp"] = 1.0 / out["over_odds"] + 1.0 / out["under_odds"]
    out["is_arb"] = out["sum_imp"] < 1.0
    out = out[out["is_arb"]]
    if out.empty:
        return out

    B = BANKROLL
    out["stake_over"] = ((B / out["over_odds"]) / out["sum_imp"]).round(2)
    out["stake_under"] = ((B / out["under_odds"]) / out["sum_imp"]).round(2)
    out["roi_pct"] = ((1.0 - out["sum_imp"]) * 100.0).round(2)

    return out.sort_values("roi_pct", ascending=False)


# ===== HTML RENDERING =====
def section(title: str, subtitle: str) -> str:
    return f"""
    <div style="margin-top:24px;">
      <h2 style="margin:0 0 4px 0;font-size:20px;">{html.escape(title)}</h2>
      <p style="margin:0 0 10px 0;opacity:0.8;font-size:13px;">{html.escape(subtitle)}</p>
    </div>
    """


def table(headers, rows_html: str) -> str:
    ths = "".join(
        f"<th style='text-align:left;padding:10px;border-bottom:1px solid #1F2937;font-size:13px;'>{html.escape(h)}</th>"
        for h in headers
    )
    return f"""
    <div style="overflow:auto;border:1px solid #1F2937;border-radius:12px;">
      <table style="width:100%;border-collapse:collapse;min-width:900px;font-size:13px;">
        <thead>
          <tr style="background:#111827;">
            {ths}
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </div>
    """


def render(arbs_1x2: pd.DataFrame, arbs_totals: pd.DataFrame) -> str:
    ts = now_iso()
    header = f"""
    <div style="color:#E2E8F0;background:#0F1621;padding:24px;font-family:Inter,system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
      <h1 style="margin:0 0 6px 0;font-size:24px;">EPL Multi-Market Arbitrage Board</h1>
      <p style="opacity:0.8;margin:0 0 16px 0;font-size:13px;">
        Last updated: {html.escape(ts)} · Display bankroll: £{BANKROLL:.0f} · Markets: Match Result & Goals Totals
      </p>
    """

    body = ""

    # ---- 1X2 section ----
    body += section("Match Result (1X2) Arbitrage", "Best cross-book 1X2 opportunities.")
    if arbs_1x2.empty:
        body += "<p style='opacity:0.7;font-size:13px;'>No 1X2 arbitrage opportunities right now.</p>"
    else:
        rows = []
        for _, r in arbs_1x2.iterrows():
            fixture = f"{r['home_team']} vs {r['away_team']}"
            row = f"""
            <tr>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{html.escape(fixture)}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{r['odds_home']} @ {html.escape(str(r['book_home']))}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{r['odds_draw']} @ {html.escape(str(r['book_draw']))}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{r['odds_away']} @ {html.escape(str(r['book_away']))}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;text-align:right;">{r['roi_pct']}%</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">
                Home: £{r['stake_home']}<br>
                Draw: £{r['stake_draw']}<br>
                Away: £{r['stake_away']}
              </td>
            </tr>
            """
            rows.append(row)

        body += table(
            ["Fixture", "Home", "Draw", "Away", "ROI", "Suggested Stakes"],
            "".join(rows),
        )

    # ---- Totals section ----
    body += section(
        "Goals Totals (Over/Under) Arbitrage",
        "Lines where Over & Under across books lock in a profit.",
    )

    if arbs_totals.empty:
        body += "<p style='opacity:0.7;font-size:13px;'>No goals totals arbitrage opportunities right now.</p>"
    else:
        rows = []
        for _, r in arbs_totals.iterrows():
            fixture = f"{r['home_team']} vs {r['away_team']}"
            line = f"{r['line']:+.1f} goals"
            row = f"""
            <tr>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{html.escape(fixture)}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{html.escape(line)}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{r['over_odds']} @ {html.escape(str(r['over_book']))}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{r['under_odds']} @ {html.escape(str(r['under_book']))}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;text-align:right;">{r['roi_pct']}%</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">
                Over: £{r['stake_over']}<br>
                Under: £{r['stake_under']}
              </td>
            </tr>
            """
            rows.append(row)

        body += table(
            ["Fixture", "Line", "Best Over", "Best Under", "ROI", "Suggested Stakes"],
            "".join(rows),
        )

    body += """
      <p style="opacity:0.7;margin-top:16px;font-size:11px;">
        Stakes are illustrative for a £{bank} bankroll. Always confirm exact market and line before placing bets.
      </p>
    """.format(
        bank=BANKROLL
    )

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'></head>"
        f"<body>{header}{body}</div></body></html>"
    )


# ===== MAIN =====
def main():
    data = fetch_all()
    df = json_to_long(data)

    if df.empty:
        html_text = render(pd.DataFrame(), pd.DataFrame())
    else:
        # drop stale by last_update if present
        if "last_update" in df.columns and df["last_update"].notna().any():
            ts = pd.to_datetime(df["last_update"], errors="coerce", utc=True)
            cutoff = pd.Timestamp.utcnow() - pd.Timedelta(minutes=STALE_MIN)
            df = df[ts.isna() | (ts >= cutoff)]

        # price sanity
        df = df[(df["odds"] >= 1.01) & (df["odds"] <= 1000)]

        arbs_1x2 = parse_1x2(df)
        arbs_totals = parse_totals(df)

        html_text = render(arbs_1x2, arbs_totals)

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html_text, encoding="utf-8")
    print(f"Wrote: {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
