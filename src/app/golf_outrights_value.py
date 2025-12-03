# -*- coding: utf-8 -*-
"""
PGA Golf Value Outrights Board – finds +EV outrights vs market consensus.

Sport: golf_pga (PGA Tour, including majors when available)
Output: data/auto/golf_outrights_latest.html
"""

from pathlib import Path
from datetime import datetime, timezone
import html
import requests
import pandas as pd

# ====== CONFIG ======
API_KEY = "98fb91f398403151a3eece97dc514a0b"   # <- put your key here
SPORT = "golf_pga"                   # PGA Tour only
REGIONS = "uk"                       # adjust if you want other regions
MARKETS = "outrights"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
OUTPUT_HTML = Path("data/auto/golf_outrights_latest.html")
TIMEOUT = 30

MIN_EDGE_PCT = 2.0                   # minimum edge to display
MAX_ROWS = 200                       # just to keep the table a sane size

BOOK_PRIORITY = [
    "Betfair", "Betfair Sportsbook", "PaddyPower",
    "William Hill", "Ladbrokes", "Unibet", "SkyBet",
    "BetVictor", "BoyleSports", "LeoVegas"
]


# ====== HELPERS ======
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def fetch_golf_outrights():
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"
    params = dict(
        apiKey=API_KEY,
        regions=REGIONS,
        markets=MARKETS,
        oddsFormat=ODDS_FORMAT,
        dateFormat=DATE_FORMAT,
    )

    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
    except Exception as e:
        print(f"[golf] Request error: {e}")
        return []

    if r.status_code != 200:
        print(f"[golf] HTTP {r.status_code}: {r.text}")
        # DO NOT crash the workflow — just return no data
        return []

    try:
        return r.json()
    except Exception as e:
        print(f"[golf] JSON decode error: {e}")
        return []



def json_to_long(data) -> pd.DataFrame:
    """
    Flatten The Odds API JSON to one row per (tournament, golfer, bookmaker).
    """
    rows = []
    for ev in data:
        event_id = ev.get("id")
        # Tournament name – The Odds API usually has sport_title or league or similar
        tourney = ev.get("sport_title") or ev.get("league") or ev.get("home_team") or "Tournament"
        commence = ev.get("commence_time")

        for b in ev.get("bookmakers", []):
            book = b.get("title")
            for m in b.get("markets", []):
                if m.get("key") != "outrights":
                    continue
                for o in m.get("outcomes", []):
                    name = (o.get("name") or o.get("description") or "").strip()
                    price = o.get("price")
                    if not name or price is None:
                        continue
                    try:
                        odds = float(price)
                        if odds <= 1.0 or odds > 1001:
                            continue
                    except (TypeError, ValueError):
                        continue

                    rows.append(
                        {
                            "event_id": event_id,
                            "tournament": tourney,
                            "commence_time": commence,
                            "golfer": name,
                            "bookmaker": book,
                            "odds": odds,
                        }
                    )

    return pd.DataFrame(rows)


def compute_value(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each (event, golfer), compute:
      - best odds + book
      - market consensus probability & fair odds
      - edge% of best odds vs fair odds
    """
    if df.empty:
        return df

    df = df.copy()
    df["imp_prob"] = 1.0 / df["odds"]

    # Priority list so Betfair etc win ties
    df["book_order"] = df["bookmaker"].apply(
        lambda b: BOOK_PRIORITY.index(b) if b in BOOK_PRIORITY else len(BOOK_PRIORITY)
    )

    # Best odds per golfer
    best = (
        df.sort_values(["odds", "book_order"], ascending=[False, True])
        .groupby(["event_id", "tournament", "golfer"], as_index=False)
        .first()
        .rename(columns={"bookmaker": "best_book", "odds": "best_odds"})
    )

    # Consensus probability = mean of implied probs
    grouped = df.groupby(["event_id", "tournament", "golfer"], as_index=False)
    stats = grouped["imp_prob"].mean().rename(columns={"imp_prob": "consensus_prob"})

    out = pd.merge(best, stats, on=["event_id", "tournament", "golfer"], how="inner")

    # Sanity
    out = out[(out["consensus_prob"] > 0) & (out["consensus_prob"] < 1)]

    out["fair_odds"] = 1.0 / out["consensus_prob"]
    out["edge_pct"] = ((out["best_odds"] / out["fair_odds"]) - 1.0) * 100.0
    out["best_imp_prob"] = 1.0 / out["best_odds"]

    # Only +EV rows
    out = out[out["edge_pct"] >= MIN_EDGE_PCT]
    out = out.sort_values("edge_pct", ascending=False).head(MAX_ROWS)
    return out


def render_html(df: pd.DataFrame) -> str:
    ts = now_iso()
    header = f"""
    <div style="color:#E2E8F0;background:#0F1621;padding:24px;
                font-family:Inter,system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
      <h1 style="margin:0 0 6px 0;">PGA Golf Value Outrights Board</h1>
      <p style="opacity:0.8;margin:0 0 16px 0;">
        Last updated: {html.escape(ts)} · Sport: PGA Tour (golf_pga) ·
        Showing outrights with edge ≥ {MIN_EDGE_PCT:.1f}% vs market consensus.
      </p>
    """

    if df.empty:
        body = header + "<p>No clear +EV outrights right now. Check back later.</p></div>"
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'></head>"
            f"<body>{body}</body></html>"
        )

    rows_html = []
    for _, r in df.iterrows():
        tourney = html.escape(str(r["tournament"]))
        golfer = html.escape(str(r["golfer"]))
        best = f"{r['best_odds']:.2f} @ {html.escape(str(r['best_book']))}"
        fair = f"{r['fair_odds']:.2f}"
        edge = f"{r['edge_pct']:.2f}%"
        best_p = f"{r['best_imp_prob']*100:.2f}%"
        fair_p = f"{r['consensus_prob']*100:.2f}%"

        rows_html.append(
            f"""
        <tr>
          <td>{tourney}</td>
          <td>{golfer}</td>
          <td>{best}</td>
          <td>{fair}</td>
          <td style="text-align:right;">{edge}</td>
          <td>{best_p} vs {fair_p}</td>
        </tr>
        """
        )

    table = f"""
    {header}
      <div style="overflow:auto;border:1px solid #1F2937;border-radius:12px;">
        <table style="width:100%;border-collapse:collapse;min-width:900px;">
          <thead>
            <tr style="background:#111827;">
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Tournament</th>
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Golfer</th>
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Best Odds</th>
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Consensus Odds</th>
              <th style="text-align:right;padding:12px;border-bottom:1px solid #1F2937;">Edge</th>
              <th style="text-align:left;padding:12px;border-bottom:1px solid #1F2937;">Implied Win %</th>
            </tr>
          </thead>
          <tbody>
            {''.join(rows_html)}
          </tbody>
        </table>
      </div>
      <p style="opacity:0.7;margin-top:12px;font-size:12px;">
        Edges are based on a simple market-consensus price and do not guarantee profit.
        Always confirm odds and availability before betting.
      </p>
    </div>
    """

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'></head>"
        f"<body>{table}</body></html>"
    )


def main():
    data = fetch_golf_outrights()
    df = json_to_long(data)

    if df.empty:
        html_text = render_html(df)
    else:
        values = compute_value(df)
        html_text = render_html(values)

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html_text, encoding="utf-8")
    print(f"Wrote: {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
