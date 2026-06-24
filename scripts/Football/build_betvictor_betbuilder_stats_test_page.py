#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = (
    ROOT
    / "football"
    / "data"
    / "betvictor_worldcup_betbuilder_stats_fast_test_v2_nav_fix.json"
)
OUT_PATH = (
    ROOT
    / "football"
    / "data"
    / "betvictor_betbuilder_stats_fast_test_view.html"
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def threshold_number(value: Any) -> int:
    match = re.fullmatch(r"(\d+)\+", clean(value))
    return int(match.group(1)) if match else 999999


def render_market(market: dict[str, Any]) -> str:
    name = html.escape(clean(market.get("market")))
    audit = market.get("selection_audit", {})
    selections = sorted(
        market.get("selections", []),
        key=lambda row: threshold_number(row.get("threshold")),
    )

    rows = "".join(
        "<tr>"
        f"<td>{html.escape(clean(selection.get('threshold')))}</td>"
        f"<td>{html.escape(clean(selection.get('odds')))}</td>"
        "</tr>"
        for selection in selections
    )

    conflicts = int(audit.get("conflict_count", 0) or 0)
    order_errors = int(
        audit.get("odds_order_violation_count", 0) or 0
    )
    gaps = int(audit.get("ladder_gap_count", 0) or 0)
    gap_values = ", ".join(audit.get("ladder_gaps", []))

    status_class = (
        "bad"
        if conflicts or order_errors
        else ("warn" if gaps else "good")
    )

    gap_note = (
        '<div class="gap-note">'
        f"Missing integer thresholds: {html.escape(gap_values)}"
        "</div>"
        if gap_values
        else ""
    )

    return f'''
<section class="market-card">
  <div class="market-header">
    <h3>{name}</h3>
    <span class="status {status_class}">
      {len(selections)} prices | {conflicts} conflicts |
      {order_errors} order errors | {gaps} gaps
    </span>
  </div>
  {gap_note}
  <table>
    <thead>
      <tr><th>Threshold</th><th>BetVictor odds</th></tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</section>
'''


def render_fixture(fixture: dict[str, Any]) -> str:
    match_name = clean(fixture.get("match"))
    kickoff = clean(fixture.get("kickoff"))
    source_url = clean(fixture.get("source_url"))
    fixture_search = html.escape(match_name.lower(), quote=True)

    source_link = (
        f'<a class="source-link" href="{html.escape(source_url, quote=True)}" '
        'target="_blank" rel="noopener noreferrer">'
        "Open BetVictor event</a>"
        if source_url
        else '<span class="missing">No source URL</span>'
    )

    markets = "".join(
        render_market(market)
        for market in fixture.get("markets", [])
    )

    return f'''
<details class="fixture-card" open data-search="{fixture_search}">
  <summary>
    <div>
      <strong>{html.escape(match_name)}</strong>
      <span class="kickoff">{html.escape(kickoff)}</span>
    </div>
    <div class="fixture-meta">
      {fixture.get("market_count", 0)} markets
    </div>
  </summary>
  <div class="fixture-actions">{source_link}</div>
  <div class="markets-grid">{markets}</div>
</details>
'''


def main() -> None:
    if not SOURCE_PATH.exists():
        raise SystemExit(f"Missing test JSON:\n{SOURCE_PATH}")

    data = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    fixtures = data.get("matches", [])
    market_count = sum(
        int(fixture.get("market_count", 0) or 0)
        for fixture in fixtures
    )

    fixture_html = "".join(
        render_fixture(fixture)
        for fixture in fixtures
    )

    page = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BetVictor Bet Builder Stats Test</title>
<style>
:root {{
  color-scheme: dark;
  font-family: Arial, Helvetica, sans-serif;
  background: #0e141a;
  color: #edf2f7;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #0e141a; }}
header {{
  position: sticky;
  top: 0;
  z-index: 20;
  padding: 18px 22px;
  background: rgba(14, 20, 26, 0.97);
  border-bottom: 1px solid #2d3748;
}}
h1 {{ margin: 0 0 7px; font-size: 24px; }}
.meta {{
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  color: #a0aec0;
  font-size: 14px;
}}
input {{
  margin-top: 13px;
  width: min(620px, 100%);
  padding: 11px 13px;
  border: 1px solid #4a5568;
  border-radius: 8px;
  background: #1a202c;
  color: #fff;
  font-size: 15px;
}}
main {{ max-width: 1500px; margin: 0 auto; padding: 18px; }}
.fixture-card {{
  margin-bottom: 16px;
  border: 1px solid #2d3748;
  border-radius: 10px;
  background: #161d24;
  overflow: hidden;
}}
.fixture-card summary {{
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  gap: 18px;
  padding: 15px 18px;
  background: #1d2731;
}}
.fixture-card summary strong {{ font-size: 18px; }}
.kickoff {{
  margin-left: 12px;
  color: #a0aec0;
  font-size: 13px;
}}
.fixture-meta {{
  color: #a0aec0;
  font-size: 13px;
}}
.fixture-actions {{ padding: 12px 18px 0; }}
.source-link {{
  display: inline-block;
  padding: 8px 11px;
  border-radius: 7px;
  background: #08783e;
  color: white;
  text-decoration: none;
  font-weight: 700;
}}
.source-link:hover {{ background: #0a9450; }}
.markets-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
  gap: 13px;
  padding: 14px 18px 18px;
}}
.market-card {{
  border: 1px solid #2d3748;
  border-radius: 8px;
  background: #111820;
  overflow: hidden;
}}
.market-header {{
  padding: 12px;
  border-bottom: 1px solid #2d3748;
}}
.market-header h3 {{
  margin: 0 0 8px;
  font-size: 16px;
}}
.status {{
  display: inline-block;
  padding: 4px 7px;
  border-radius: 999px;
  font-size: 12px;
}}
.status.good {{ background: #164e32; color: #b7f7d0; }}
.status.warn {{ background: #634d13; color: #ffe59a; }}
.status.bad {{ background: #642121; color: #ffb8b8; }}
.gap-note {{
  padding: 8px 12px;
  background: #342b13;
  color: #ffe59a;
  font-size: 12px;
}}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{
  padding: 8px 11px;
  text-align: left;
  border-bottom: 1px solid #26313d;
}}
th {{ color: #a0aec0; font-size: 12px; }}
tr:last-child td {{ border-bottom: none; }}
.fixture-card.hidden {{ display: none; }}
.missing {{ color: #f6ad55; }}
</style>
</head>
<body>
<header>
  <h1>BetVictor Bet Builder Stats</h1>
  <div class="meta">
    <span>Generated: {html.escape(clean(data.get("generated_at")))}</span>
    <span>{len(fixtures)} fixtures</span>
    <span>{market_count} markets</span>
  </div>
  <input id="search" type="search"
    placeholder="Search fixture..." autocomplete="off">
</header>
<main>{fixture_html}</main>
<script>
const input = document.getElementById("search");

input.addEventListener("input", () => {{
  const query = input.value.trim().toLowerCase();

  document.querySelectorAll(".fixture-card").forEach(card => {{
    const visible = !query || card.dataset.search.includes(query);
    card.classList.toggle("hidden", !visible);

    if (visible && query) {{
      card.open = true;
    }}
  }});
}});
</script>
</body>
</html>
'''

    OUT_PATH.write_text(page, encoding="utf-8")

    print("Built BetVictor Bet Builder test data page:")
    print(OUT_PATH)
    print(f"Fixtures: {len(fixtures)}")
    print(f"Markets: {market_count}")
    print("Production JSON modified: NO")


if __name__ == "__main__":
    main()
