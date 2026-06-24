#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "football" / "data" / "betvictor_player_tackles.json"
OUT_PATH = ROOT / "football" / "data" / "betvictor_player_tackles_view.html"


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value: Any) -> str:
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def threshold_number(value: Any) -> int | None:
    match = re.fullmatch(r"(\d+)\+", clean(value))
    return int(match.group(1)) if match else None


def is_tackles_market(market: dict[str, Any]) -> bool:
    return normalize(
        market.get("normalized_market")
        or market.get("market")
    ) == "player_tackles"


def extract_fixture(match: dict[str, Any]) -> dict[str, Any] | None:
    market = next(
        (
            item
            for item in match.get("markets", [])
            if is_tackles_market(item)
        ),
        None,
    )

    if market is None:
        return None

    players: dict[str, dict[int, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    player_names: dict[str, str] = {}

    for selection in market.get("selections", []):
        player = clean(selection.get("player"))
        threshold = threshold_number(selection.get("threshold"))
        odds = clean(selection.get("odds")).upper()

        if not player or threshold is None or not odds:
            continue

        key = normalize(player)
        player_names[key] = player

        if odds not in players[key][threshold]:
            players[key][threshold].append(odds)

    thresholds = sorted(
        {
            threshold
            for player_rows in players.values()
            for threshold in player_rows
        }
    )

    player_rows = []

    for key in sorted(
        players,
        key=lambda item: player_names[item].lower(),
    ):
        player_rows.append(
            {
                "player": player_names[key],
                "prices": {
                    threshold: " / ".join(players[key][threshold])
                    for threshold in sorted(players[key])
                },
            }
        )

    return {
        "match": clean(match.get("match")),
        "kickoff": clean(
            match.get("kickoff")
            or match.get("start_time")
            or match.get("commence_time")
        ),
        "source_url": clean(
            match.get("source_url")
            or match.get("url")
            or market.get("source_url")
            or market.get("url")
        ),
        "selection_count": len(market.get("selections", [])),
        "player_count": len(player_rows),
        "thresholds": thresholds,
        "players": player_rows,
    }


def render_fixture(fixture: dict[str, Any]) -> str:
    match_name = html.escape(fixture["match"])
    kickoff = html.escape(fixture["kickoff"])
    source_url = html.escape(fixture["source_url"], quote=True)
    fixture_search = html.escape(
        fixture["match"].lower(),
        quote=True,
    )

    if source_url:
        source_link = (
            f'<a class="source-link" href="{source_url}" '
            'target="_blank" rel="noopener noreferrer">'
            "Open BetVictor source</a>"
        )
    else:
        source_link = '<span class="source-missing">No source URL</span>'

    headers = "".join(
        f"<th>{threshold}+</th>"
        for threshold in fixture["thresholds"]
    )

    body_rows = []

    for player in fixture["players"]:
        search_text = html.escape(
            f'{fixture["match"]} {player["player"]}'.lower(),
            quote=True,
        )
        cells = "".join(
            (
                f'<td>{html.escape(player["prices"].get(threshold, ""))}</td>'
            )
            for threshold in fixture["thresholds"]
        )

        body_rows.append(
            f'<tr class="player-row" data-search="{search_text}">'
            f'<td class="player-name">{html.escape(player["player"])}</td>'
            f"{cells}</tr>"
        )

    kickoff_html = (
        f'<span class="kickoff">{kickoff}</span>'
        if kickoff
        else ""
    )

    return f'''
<details class="fixture-card" open data-fixture="{fixture_search}">
  <summary>
    <div>
      <strong>{match_name}</strong>
      {kickoff_html}
    </div>
    <div class="summary-meta">
      <span>{fixture["player_count"]} players</span>
      <span>{fixture["selection_count"]} prices</span>
    </div>
  </summary>

  <div class="fixture-actions">{source_link}</div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th class="player-column">Player</th>
          {headers}
        </tr>
      </thead>
      <tbody>
        {''.join(body_rows)}
      </tbody>
    </table>
  </div>
</details>
'''


def main() -> None:
    if not SOURCE_PATH.exists():
        raise SystemExit(
            f"Missing BetVictor tackles JSON:\n{SOURCE_PATH}"
        )

    data = json.loads(
        SOURCE_PATH.read_text(encoding="utf-8")
    )

    fixtures = []

    for match in data.get("matches", []):
        fixture = extract_fixture(match)

        if fixture is not None:
            fixtures.append(fixture)

    fixture_html = "".join(
        render_fixture(fixture)
        for fixture in fixtures
    )

    generated_at = clean(
        data.get("generated_at")
        or data.get("scraped_at")
        or datetime.now().isoformat(timespec="seconds")
    )
    total_players = sum(
        fixture["player_count"]
        for fixture in fixtures
    )
    total_prices = sum(
        fixture["selection_count"]
        for fixture in fixtures
    )

    page = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BetVictor Player Tackles Data</title>
<style>
:root {{
  color-scheme: dark;
  font-family: Arial, Helvetica, sans-serif;
  background: #0f1419;
  color: #edf2f7;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #0f1419; }}
header {{
  position: sticky;
  top: 0;
  z-index: 20;
  padding: 18px 22px;
  background: rgba(15, 20, 25, 0.97);
  border-bottom: 1px solid #2d3748;
}}
h1 {{ margin: 0 0 8px; font-size: 24px; }}
.meta {{
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  color: #a0aec0;
  font-size: 14px;
}}
.controls {{ margin-top: 14px; }}
input {{
  width: min(600px, 100%);
  padding: 11px 13px;
  border: 1px solid #4a5568;
  border-radius: 8px;
  background: #1a202c;
  color: #fff;
  font-size: 15px;
}}
main {{ max-width: 1500px; margin: 0 auto; padding: 18px; }}
.fixture-card {{
  margin-bottom: 14px;
  border: 1px solid #2d3748;
  border-radius: 10px;
  background: #171d24;
  overflow: hidden;
}}
.fixture-card summary {{
  cursor: pointer;
  padding: 15px 18px;
  display: flex;
  justify-content: space-between;
  gap: 18px;
  background: #1d2630;
}}
.fixture-card summary strong {{ font-size: 18px; }}
.kickoff {{
  margin-left: 12px;
  color: #a0aec0;
  font-size: 13px;
}}
.summary-meta {{
  display: flex;
  gap: 12px;
  color: #a0aec0;
  white-space: nowrap;
  font-size: 13px;
}}
.fixture-actions {{ padding: 12px 18px 0; }}
.source-link {{
  display: inline-block;
  padding: 8px 11px;
  border-radius: 7px;
  background: #08783e;
  color: #fff;
  text-decoration: none;
  font-weight: 700;
}}
.source-link:hover {{ background: #0a9450; }}
.source-missing {{ color: #f6ad55; }}
.table-wrap {{ overflow-x: auto; padding: 12px 18px 18px; }}
table {{
  width: 100%;
  border-collapse: collapse;
  min-width: 760px;
}}
th, td {{
  border-bottom: 1px solid #2d3748;
  padding: 9px 10px;
  text-align: center;
  white-space: nowrap;
}}
th {{ background: #222c37; }}
.player-column, .player-name {{
  position: sticky;
  left: 0;
  text-align: left;
  background: #171d24;
}}
th.player-column {{ background: #222c37; }}
td:empty::after {{ content: "—"; color: #4a5568; }}
.player-row.hidden, .fixture-card.hidden {{ display: none; }}
</style>
</head>
<body>
<header>
  <h1>BetVictor Player Tackles</h1>
  <div class="meta">
    <span>Generated: {html.escape(generated_at)}</span>
    <span>{len(fixtures)} fixtures</span>
    <span>{total_players} player rows</span>
    <span>{total_prices} prices</span>
  </div>
  <div class="controls">
    <input id="search" type="search"
      placeholder="Search fixture or player…"
      autocomplete="off">
  </div>
</header>

<main>
{fixture_html}
</main>

<script>
const input = document.getElementById("search");

input.addEventListener("input", () => {{
  const query = input.value.trim().toLowerCase();

  document.querySelectorAll(".fixture-card").forEach(card => {{
    const fixtureMatches =
      !query || card.dataset.fixture.includes(query);
    let visibleRows = 0;

    card.querySelectorAll(".player-row").forEach(row => {{
      const visible =
        fixtureMatches || !query || row.dataset.search.includes(query);
      row.classList.toggle("hidden", !visible);
      if (visible) visibleRows += 1;
    }});

    card.classList.toggle("hidden", visibleRows === 0);
    if (visibleRows > 0 && query) card.open = true;
  }});
}});
</script>
</body>
</html>
'''

    OUT_PATH.write_text(page, encoding="utf-8")

    print("Built BetVictor tackles data page:")
    print(OUT_PATH)
    print(f"Fixtures: {len(fixtures)}")
    print(f"Player rows: {total_players}")
    print(f"Prices: {total_prices}")
    print("Production JSON modified: NO")


if __name__ == "__main__":
    main()
