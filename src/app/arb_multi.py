# -*- coding: utf-8 -*-
"""
Football Arbitrage Finder (Multi-League) — H2H + Totals + Spreads
Single-page output (no league sub-pages):
  data/auto/arb_latest.html
"""

import html
from datetime import datetime, timezone
from pathlib import Path
import requests
import pandas as pd

# ================= CONFIG =================

API_KEY = "8e8a4a2421e95ad2fb0df450c88ef6c6"

SPORTS = {
    "Premier League": "soccer_epl",
    "La Liga": "soccer_spain_la_liga",
    "Bundesliga": "soccer_germany_bundesliga",
    "Serie A": "soccer_italy_serie_a",
    "Champions League": "soccer_uefa_champs_league",
}

REGIONS = "eu"
MARKETS = "h2h,totals,spreads"   # fetch all in one call per league
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT = 30

BANKROLL = 100.0
MIN_ROI_PCT = 1.0               # ✅ minimum ROI filter (1%)
OUTPUT_HTML = Path("data/auto/arb_latest.html")

POPULAR_SPREAD_LINES = {-1.0, 0.0, 1.0}

ODDS_MIN = 1.01
ODDS_MAX = 1000.0


# ================= HELPERS =================

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def fetch_odds_for_league(sport_key: str):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": DATE_FORMAT,
    }
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        # fail soft per league (keeps whole board alive)
        print(f"[WARN] {sport_key} HTTP {r.status_code}: {r.text[:200]}")
        return []
    return r.json()


# ================= FLATTEN =================

def flatten_all(league_name: str, data):
    """
    Flatten API JSON -> rows across h2h/totals/spreads.
    Normalizes 'side' and 'line' across markets.
    """
    rows = []

    for g in data:
        gid = g.get("id")
        home = g.get("home_team")
        away = g.get("away_team")
        kickoff = g.get("commence_time")

        if not gid or not home or not away:
            continue

        for b in g.get("bookmakers", []):
            book = b.get("title")
            for m in b.get("markets", []):
                mkey = m.get("key")
                if mkey not in ("h2h", "totals", "spreads"):
                    continue

                for o in m.get("outcomes", []):
                    price = o.get("price")
                    point = o.get("point")
                    name = (o.get("name") or "").strip()

                    if price is None:
                        continue

                    try:
                        odds = float(price)
                    except Exception:
                        continue

                    if not (ODDS_MIN <= odds <= ODDS_MAX):
                        continue

                    side = None
                    line = None

                    if mkey == "h2h":
                        # Outcomes: Home team, Away team, Draw
                        nlow = name.lower()
                        if nlow == "draw":
                            side = "Draw"
                        elif name == home or home.lower() == nlow:
                            side = "Home"
                        elif name == away or away.lower() == nlow:
                            side = "Away"
                        else:
                            continue
                        line = None

                    elif mkey == "totals":
                        # Over/Under with point line
                        nlow = name.lower()
                        if "over" in nlow:
                            side = "Over"
                        elif "under" in nlow:
                            side = "Under"
                        else:
                            continue
                        if point is None:
                            continue
                        try:
                            line = float(point)
                        except Exception:
                            continue

                    elif mkey == "spreads":
                        # Home/Away with handicap point line
                        if point is None:
                            continue
                        try:
                            line = float(point)
                        except Exception:
                            continue
                        if line not in POPULAR_SPREAD_LINES:
                            continue

                        nlow = name.lower()
                        if name == home or home.lower() == nlow:
                            side = "Home"
                        elif name == away or away.lower() == nlow:
                            side = "Away"
                        else:
                            continue

                    rows.append({
                        "league": league_name,
                        "event_id": gid,
                        "home": home,
                        "away": away,
                        "kickoff": kickoff,
                        "book": book or "",
                        "market": mkey,
                        "side": side,
                        "line": line,
                        "odds": odds,
                    })

    return pd.DataFrame(rows)


# ================= ARB BUILDERS =================

def _best_by_side(sub: pd.DataFrame) -> pd.DataFrame:
    # best odds per side (max odds)
    return (
        sub.sort_values(["odds"], ascending=False)
           .groupby("side", as_index=True)
           .first()
    )


def build_1x2_arbs(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["market"] == "h2h"].copy()
    if df.empty:
        return pd.DataFrame()

    out_rows = []
    group_cols = ["league", "event_id", "home", "away", "kickoff"]

    for _, sub in df.groupby(group_cols):
        sides = set(sub["side"].unique())
        if sides != {"Home", "Draw", "Away"}:
            continue

        best = _best_by_side(sub)
        inv_sum = (1 / best.loc["Home", "odds"]) + (1 / best.loc["Draw", "odds"]) + (1 / best.loc["Away", "odds"])
        if inv_sum >= 1:
            continue

        roi_pct = (1 - inv_sum) * 100
        if roi_pct < MIN_ROI_PCT:
            continue

        B = BANKROLL
        stake_home = (B / best.loc["Home", "odds"]) / inv_sum
        stake_draw = (B / best.loc["Draw", "odds"]) / inv_sum
        stake_away = (B / best.loc["Away", "odds"]) / inv_sum

        league, event_id, home, away, kickoff = sub.iloc[0][group_cols].tolist()
        out_rows.append({
            "league": league,
            "kickoff": kickoff,
            "fixture": f"{home} vs {away}",
            "odds_home": float(best.loc["Home", "odds"]),
            "book_home": str(best.loc["Home", "book"]),
            "odds_draw": float(best.loc["Draw", "odds"]),
            "book_draw": str(best.loc["Draw", "book"]),
            "odds_away": float(best.loc["Away", "odds"]),
            "book_away": str(best.loc["Away", "book"]),
            "roi_pct": round(roi_pct, 2),
            "stake_home": round(stake_home, 2),
            "stake_draw": round(stake_draw, 2),
            "stake_away": round(stake_away, 2),
        })

    if not out_rows:
        return pd.DataFrame()
    return pd.DataFrame(out_rows).sort_values("roi_pct", ascending=False)


def build_totals_arbs(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["market"] == "totals"].copy()
    if df.empty:
        return pd.DataFrame()

    out_rows = []
    group_cols = ["league", "event_id", "home", "away", "kickoff", "line"]

    for _, sub in df.groupby(group_cols):
        sides = set(sub["side"].unique())
        if sides != {"Over", "Under"}:
            continue

        best = _best_by_side(sub)
        inv_sum = (1 / best.loc["Over", "odds"]) + (1 / best.loc["Under", "odds"])
        if inv_sum >= 1:
            continue

        roi_pct = (1 - inv_sum) * 100
        if roi_pct < MIN_ROI_PCT:
            continue

        B = BANKROLL
        stake_over = (B / best.loc["Over", "odds"]) / inv_sum
        stake_under = (B / best.loc["Under", "odds"]) / inv_sum

        league, event_id, home, away, kickoff, line = sub.iloc[0][group_cols].tolist()
        out_rows.append({
            "league": league,
            "kickoff": kickoff,
            "fixture": f"{home} vs {away}",
            "line": float(line),
            "over_odds": float(best.loc["Over", "odds"]),
            "over_book": str(best.loc["Over", "book"]),
            "under_odds": float(best.loc["Under", "odds"]),
            "under_book": str(best.loc["Under", "book"]),
            "roi_pct": round(roi_pct, 2),
            "stake_over": round(stake_over, 2),
            "stake_under": round(stake_under, 2),
        })

    if not out_rows:
        return pd.DataFrame()
    return pd.DataFrame(out_rows).sort_values("roi_pct", ascending=False)


def build_spreads_arbs(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["market"] == "spreads"].copy()
    if df.empty:
        return pd.DataFrame()

    out_rows = []
    group_cols = ["league", "event_id", "home", "away", "kickoff", "line"]

    for _, sub in df.groupby(group_cols):
        sides = set(sub["side"].unique())
        if sides != {"Home", "Away"}:
            continue

        best = _best_by_side(sub)
        inv_sum = (1 / best.loc["Home", "odds"]) + (1 / best.loc["Away", "odds"])
        if inv_sum >= 1:
            continue

        roi_pct = (1 - inv_sum) * 100
        if roi_pct < MIN_ROI_PCT:
            continue

        B = BANKROLL
        stake_home = (B / best.loc["Home", "odds"]) / inv_sum
        stake_away = (B / best.loc["Away", "odds"]) / inv_sum

        league, event_id, home, away, kickoff, line = sub.iloc[0][group_cols].tolist()
        out_rows.append({
            "league": league,
            "kickoff": kickoff,
            "fixture": f"{home} vs {away}",
            "line": float(line),
            "home_odds": float(best.loc["Home", "odds"]),
            "home_book": str(best.loc["Home", "book"]),
            "away_odds": float(best.loc["Away", "odds"]),
            "away_book": str(best.loc["Away", "book"]),
            "roi_pct": round(roi_pct, 2),
            "stake_home": round(stake_home, 2),
            "stake_away": round(stake_away, 2),
        })

    if not out_rows:
        return pd.DataFrame()
    return pd.DataFrame(out_rows).sort_values("roi_pct", ascending=False)


# ================= HTML (dark table like your screenshot) =================

def section(title: str, subtitle: str) -> str:
    return f"""
    <div style="margin-top:24px;">
      <h2 style="margin:0 0 4px 0;font-size:20px;">{html.escape(title)}</h2>
      <p style="margin:0 0 10px 0;opacity:0.8;font-size:13px;">{html.escape(subtitle)}</p>
    </div>
    """


def table(headers, rows_html: str, min_width_px: int = 900) -> str:
    ths = "".join(
        f"<th style='text-align:left;padding:10px;border-bottom:1px solid #1F2937;font-size:13px;'>{html.escape(h)}</th>"
        for h in headers
    )
    return f"""
    <div style="overflow:auto;border:1px solid #1F2937;border-radius:12px;">
      <table style="width:100%;border-collapse:collapse;min-width:{min_width_px}px;font-size:13px;">
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


def render_board(arbs_1x2: pd.DataFrame, arbs_totals: pd.DataFrame, arbs_spreads: pd.DataFrame) -> str:
    ts = now_iso()
    header = f"""
    <div style="color:#E2E8F0;background:#0F1621;padding:24px;font-family:Inter,system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
      <h1 style="margin:0 0 6px 0;font-size:24px;">Football Multi-League Arbitrage Board</h1>
      <p style="opacity:0.8;margin:0 0 16px 0;font-size:13px;">
        Last updated: {html.escape(ts)} · Display bankroll: £{BANKROLL:.0f} · Minimum ROI: {MIN_ROI_PCT:.0f}% · Markets: 1X2, Totals, Spreads
      </p>
    """

    body = ""

    # 1X2
    body += section("Match Result (1X2) Arbitrage", "Best cross-book 1X2 opportunities (filtered).")
    if arbs_1x2.empty:
        body += "<p style='opacity:0.7;font-size:13px;'>No 1X2 arbitrage opportunities ≥ minimum ROI right now.</p>"
    else:
        rows = []
        for _, r in arbs_1x2.iterrows():
            rows.append(f"""
            <tr>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{html.escape(str(r['league']))}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{html.escape(str(r['fixture']))}</td>
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
            """)

        body += table(
            ["League", "Fixture", "Home", "Draw", "Away", "ROI", "Suggested Stakes"],
            "".join(rows),
            min_width_px=1050
        )

    # Totals
    body += section("Goals Totals (Over/Under) Arbitrage", "Over & Under across books (filtered).")
    if arbs_totals.empty:
        body += "<p style='opacity:0.7;font-size:13px;'>No totals arbitrage opportunities ≥ minimum ROI right now.</p>"
    else:
        rows = []
        for _, r in arbs_totals.iterrows():
            line_txt = f"{float(r['line']):.1f}"
            rows.append(f"""
            <tr>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{html.escape(str(r['league']))}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{html.escape(str(r['fixture']))}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{html.escape(line_txt)}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{r['over_odds']} @ {html.escape(str(r['over_book']))}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{r['under_odds']} @ {html.escape(str(r['under_book']))}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;text-align:right;">{r['roi_pct']}%</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">
                Over: £{r['stake_over']}<br>
                Under: £{r['stake_under']}
              </td>
            </tr>
            """)

        body += table(
            ["League", "Fixture", "Line", "Best Over", "Best Under", "ROI", "Suggested Stakes"],
            "".join(rows),
            min_width_px=1050
        )

    # Spreads
    body += section("Handicap / Spreads Arbitrage", "Popular handicap lines only (-1, 0, +1) (filtered).")
    if arbs_spreads.empty:
        body += "<p style='opacity:0.7;font-size:13px;'>No spreads arbitrage opportunities ≥ minimum ROI right now.</p>"
    else:
        rows = []
        for _, r in arbs_spreads.iterrows():
            line = float(r["line"])
            line_txt = f"{line:+.1f}"
            rows.append(f"""
            <tr>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{html.escape(str(r['league']))}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{html.escape(str(r['fixture']))}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{html.escape(line_txt)}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{r['home_odds']} @ {html.escape(str(r['home_book']))}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">{r['away_odds']} @ {html.escape(str(r['away_book']))}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;text-align:right;">{r['roi_pct']}%</td>
              <td style="padding:8px 10px;border-bottom:1px solid #111827;">
                Home: £{r['stake_home']}<br>
                Away: £{r['stake_away']}
              </td>
            </tr>
            """)

        body += table(
            ["League", "Fixture", "Line", "Best Home", "Best Away", "ROI", "Suggested Stakes"],
            "".join(rows),
            min_width_px=1050
        )

    body += f"""
      <p style="opacity:0.7;margin-top:16px;font-size:11px;">
        Stakes are illustrative for a £{BANKROLL:.0f} bankroll. Always confirm exact market and line before placing bets.
      </p>
    """

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'></head>"
        f"<body>{header}{body}</div></body></html>"
    )


# ================= MAIN =================

def main():
    all_frames = []

    for league, sport_key in SPORTS.items():
        data = fetch_odds_for_league(sport_key)
        df = flatten_all(league, data)
        if not df.empty:
            all_frames.append(df)

    if not all_frames:
        html_text = render_board(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_HTML.write_text(html_text, encoding="utf-8")
        print(f"Wrote: {OUTPUT_HTML}")
        return

    full_df = pd.concat(all_frames, ignore_index=True)

    arbs_1x2 = build_1x2_arbs(full_df)
    arbs_totals = build_totals_arbs(full_df)
    arbs_spreads = build_spreads_arbs(full_df)

    html_text = render_board(arbs_1x2, arbs_totals, arbs_spreads)

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html_text, encoding="utf-8")
    print(f"Wrote: {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
