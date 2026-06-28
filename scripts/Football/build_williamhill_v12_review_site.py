#!/usr/bin/env python3
"""
Build a standalone local review website for the William Hill V12 TEST3 output.

Default input:
  football/data/williamhill_worldcup_props_FAST_TEST3_V12_IMPACT_SUB_TAB.json

Default output:
  football/debug/williamhill_v12_review_site/index.html

This script is read-only with respect to scraper/production JSON.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]

DEFAULT_INPUT = (
    ROOT
    / "football"
    / "data"
    / "williamhill_worldcup_props_FAST_TEST3_V12_IMPACT_SUB_TAB.json"
)
DEFAULT_OUTPUT_DIR = ROOT / "football" / "debug" / "williamhill_v12_review_site"

REQUIRED_MARKETS = [
    ("first_goalscorer", "First Goalscorer"),
    ("anytime_goalscorer", "Anytime Goalscorer"),
    ("scorer_2_plus", "To Score 2+"),
    ("player_shots_on_target", "Player Shots On Target"),
    ("player_shots", "Player Shots"),
    ("player_tackles", "Player Tackles"),
    ("player_fouls_committed", "Player Fouls Committed"),
    ("player_fouls_won", "Player Fouls Won"),
    ("player_cards", "Player Cards"),
    ("player_assists", "Player Assists"),
]

NORMALIZED_ALIASES = {
    "anytime_scorer": "anytime_goalscorer",
    "anytime_goalscorer": "anytime_goalscorer",
    "to_score_2": "scorer_2_plus",
    "to_score_2_plus": "scorer_2_plus",
    "player_card": "player_cards",
    "player_shown_a_card": "player_cards",
}


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value: Any) -> str:
    text = clean(value).lower().replace("&", "and").replace("?", "")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return NORMALIZED_ALIASES.get(text, text)


def esc(value: Any) -> str:
    return html.escape(clean(value), quote=True)


def as_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        rows = data.get("matches", [])
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def market_key(market: dict[str, Any]) -> str:
    return normalize(market.get("normalized_market") or market.get("market"))


def get_markets(match: dict[str, Any]) -> list[dict[str, Any]]:
    markets = match.get("markets", [])
    return [m for m in markets if isinstance(m, dict)] if isinstance(markets, list) else []


def get_selections(market: dict[str, Any]) -> list[dict[str, Any]]:
    rows = market.get("selections", [])
    return [s for s in rows if isinstance(s, dict)] if isinstance(rows, list) else []


def selection_player(selection: dict[str, Any]) -> str:
    player = clean(selection.get("player"))
    if player:
        return player

    label = clean(selection.get("selection"))
    # Conservative fallback. The scraper should normally supply `player`.
    patterns = [
        r"\s+(?:First Goalscorer|Anytime Goalscorer|To Score 2\+)$",
        r"\s+\d+\+$",
    ]
    for pattern in patterns:
        candidate = re.sub(pattern, "", label, flags=re.I).strip()
        if candidate != label and candidate:
            return candidate
    return ""


def selection_threshold(selection: dict[str, Any]) -> str:
    return clean(selection.get("threshold"))


def selection_line(selection: dict[str, Any]) -> str:
    return clean(selection.get("line"))


def selection_odds(selection: dict[str, Any]) -> str:
    return clean(selection.get("odds")).upper()


def key_without_odds(selection: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        selection_player(selection).lower(),
        selection_threshold(selection).lower(),
        selection_line(selection).lower(),
        normalize(selection.get("prop_type")),
    )


def exact_key(selection: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return key_without_odds(selection) + (selection_odds(selection),)


def mapping_issue(selection: dict[str, Any]) -> str:
    threshold = selection_threshold(selection)
    line = selection_line(selection)

    match = re.fullmatch(r"(\d+)\+", threshold)
    if not match:
        return ""

    expected = int(match.group(1)) - 0.5
    try:
        actual = float(line)
    except (TypeError, ValueError):
        return f"{threshold} should use line {expected:g}, but line is missing/invalid"

    if not math.isclose(expected, actual, abs_tol=1e-9):
        return f"{threshold} should use line {expected:g}, got {actual:g}"
    return ""


def suspicious_player_name(selection: dict[str, Any]) -> str:
    player = selection_player(selection)
    if not player:
        return "Missing player field"

    low = player.lower()
    forbidden = [
        " over ",
        " at least ",
        " shots on target",
        " shot on target",
        " shots",
        " tackle",
        " foul",
        " shown a card",
        " to score",
        " goalscorer",
    ]
    if any(token in f" {low} " for token in forbidden):
        return f"Player field may include market wording: {player}"
    return ""


def duplicate_count(selections: list[dict[str, Any]]) -> int:
    keys = [exact_key(s) for s in selections]
    return sum(count - 1 for count in Counter(keys).values() if count > 1)


def unique_player_count(selections: list[dict[str, Any]]) -> int:
    return len({selection_player(s).lower() for s in selections if selection_player(s)})


def market_dict(match: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for market in get_markets(match):
        key = market_key(market)
        if key and key not in result:
            result[key] = market
    return result


def compare_markets(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, Any]:
    if not left or not right:
        return {
            "common": 0,
            "same_odds": 0,
            "exact_overlap": 0,
            "left_count": len(get_selections(left or {})),
            "right_count": len(get_selections(right or {})),
        }

    left_rows = get_selections(left)
    right_rows = get_selections(right)

    left_no_odds = {key_without_odds(s): selection_odds(s) for s in left_rows}
    right_no_odds = {key_without_odds(s): selection_odds(s) for s in right_rows}

    common_keys = set(left_no_odds) & set(right_no_odds)
    same_odds = sum(left_no_odds[key] == right_no_odds[key] for key in common_keys)

    left_exact = {exact_key(s) for s in left_rows}
    right_exact = {exact_key(s) for s in right_rows}

    return {
        "common": len(common_keys),
        "same_odds": same_odds,
        "exact_overlap": len(left_exact & right_exact),
        "left_count": len(left_rows),
        "right_count": len(right_rows),
    }


def market_issues(market: dict[str, Any]) -> list[str]:
    selections = get_selections(market)
    issues: list[str] = []

    dupes = duplicate_count(selections)
    if dupes:
        issues.append(f"{dupes} exact duplicate selection(s)")

    mapping_errors = [mapping_issue(s) for s in selections]
    mapping_errors = [x for x in mapping_errors if x]
    if mapping_errors:
        issues.append(f"{len(mapping_errors)} threshold/line mapping error(s)")

    bad_names = [suspicious_player_name(s) for s in selections]
    bad_names = [x for x in bad_names if x]
    if bad_names:
        issues.append(f"{len(bad_names)} suspicious/missing player name(s)")

    if market_key(market).startswith("player_") and not selections:
        issues.append("No selections")

    return issues


def build_match_issues(match: dict[str, Any]) -> list[str]:
    issues = [clean(x) for x in match.get("validation_warnings", []) if clean(x)]
    markets = market_dict(match)

    for key, label in REQUIRED_MARKETS:
        market = markets.get(key)
        if not market or not get_selections(market):
            issues.append(f"Missing required market: {label}")

    for market in get_markets(match):
        for issue in market_issues(market):
            issues.append(f"{clean(market.get('market'))}: {issue}")

    fouls = compare_markets(
        markets.get("player_fouls_committed"),
        markets.get("player_fouls_won"),
    )
    if fouls["common"] and fouls["same_odds"] == fouls["common"]:
        issues.append(
            "Fouls Committed and Fouls Won have identical odds for every common "
            "player/threshold key"
        )

    return list(dict.fromkeys(issues))


def status_class(ok: bool) -> str:
    return "ok" if ok else "bad"


def render_required_checklist(match: dict[str, Any]) -> str:
    markets = market_dict(match)
    cards: list[str] = []

    for key, label in REQUIRED_MARKETS:
        market = markets.get(key)
        count = len(get_selections(market or {}))
        players = unique_player_count(get_selections(market or {}))
        ok = count > 0
        cards.append(
            f"""
            <div class="check-card {status_class(ok)}">
              <div class="check-name">{esc(label)}</div>
              <div class="check-count">{count} selections</div>
              <div class="check-sub">{players} unique players</div>
            </div>
            """
        )

    return "\n".join(cards)


def render_fouls_comparison(match: dict[str, Any]) -> str:
    markets = market_dict(match)
    comp = compare_markets(
        markets.get("player_fouls_committed"),
        markets.get("player_fouls_won"),
    )

    if not comp["left_count"] and not comp["right_count"]:
        return ""

    common = comp["common"]
    same_odds = comp["same_odds"]
    percentage = (same_odds / common * 100.0) if common else 0.0
    overlap_class = "bad" if common and same_odds == common else "ok"

    return f"""
    <section class="comparison">
      <h3>Fouls market comparison</h3>
      <div class="metric-grid">
        <div class="metric"><b>{comp['left_count']}</b><span>Committed rows</span></div>
        <div class="metric"><b>{comp['right_count']}</b><span>Won rows</span></div>
        <div class="metric"><b>{common}</b><span>Common player/threshold keys</span></div>
        <div class="metric {overlap_class}">
          <b>{same_odds}</b>
          <span>Common keys with same odds ({percentage:.1f}%)</span>
        </div>
        <div class="metric"><b>{comp['exact_overlap']}</b><span>Exact rows shared</span></div>
      </div>
      <p class="hint">
        Different markets may share players and thresholds, but they should not
        carry identical prices across every common key.
      </p>
    </section>
    """


def render_scorer_comparison(match: dict[str, Any]) -> str:
    markets = market_dict(match)
    keys = [
        ("first_goalscorer", "First"),
        ("anytime_goalscorer", "Anytime"),
        ("scorer_2_plus", "2+"),
    ]
    cards: list[str] = []
    for key, label in keys:
        market = markets.get(key)
        rows = get_selections(market or {})
        cards.append(
            f"""
            <div class="metric">
              <b>{len(rows)}</b>
              <span>{esc(label)} selections</span>
              <small>{unique_player_count(rows)} unique players</small>
            </div>
            """
        )
    return f"""
    <section class="comparison">
      <h3>Scorer grid check</h3>
      <div class="metric-grid">{"".join(cards)}</div>
      <p class="hint">
        The three scorer columns should normally contain the same player list,
        with different odds and prop types.
      </p>
    </section>
    """


def render_selection_rows(market: dict[str, Any], fixture_index: int, market_index: int) -> str:
    rows: list[str] = []
    for row_index, selection in enumerate(get_selections(market), start=1):
        map_problem = mapping_issue(selection)
        name_problem = suspicious_player_name(selection)
        problems = [x for x in [map_problem, name_problem] if x]
        row_class = "problem-row" if problems else ""

        raw_source = (
            selection.get("source_selection")
            or selection.get("original_selection")
            or selection.get("selection")
            or ""
        )

        searchable = " ".join(
            clean(
                selection.get(field)
                if field in selection
                else ""
            )
            for field in [
                "player",
                "selection",
                "threshold",
                "line",
                "odds",
                "prop_type",
                "source_selection",
            ]
        ).lower()

        rows.append(
            f"""
            <tr class="{row_class}" data-search="{esc(searchable)}">
              <td>{row_index}</td>
              <td>{esc(selection_player(selection))}</td>
              <td>{esc(selection_threshold(selection))}</td>
              <td>{esc(selection_line(selection))}</td>
              <td class="odds">{esc(selection_odds(selection))}</td>
              <td>{esc(selection.get("prop_type"))}</td>
              <td>{esc(selection.get("selection"))}</td>
              <td>{esc(raw_source)}</td>
              <td class="problem">{esc("; ".join(problems))}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def render_market(
    market: dict[str, Any],
    fixture_index: int,
    market_index: int,
) -> str:
    selections = get_selections(market)
    issues = market_issues(market)
    unique_players = unique_player_count(selections)
    duplicates = duplicate_count(selections)
    issue_badge = (
        f'<span class="badge bad">{len(issues)} issue(s)</span>'
        if issues
        else '<span class="badge ok">No automatic issues</span>'
    )
    table_id = f"table-{fixture_index}-{market_index}"

    return f"""
    <details class="market-card" open>
      <summary>
        <span class="market-title">{esc(market.get("market"))}</span>
        <span class="badge">{len(selections)} selections</span>
        <span class="badge">{unique_players} players</span>
        <span class="badge">{duplicates} duplicates</span>
        {issue_badge}
      </summary>
      <div class="market-body">
        <div class="market-meta">
          normalized_market: <code>{esc(market_key(market))}</code>
        </div>
        <input
          class="market-search"
          type="search"
          placeholder="Filter this market by player, threshold, price..."
          oninput="filterTable('{table_id}', this.value)"
        >
        <div class="table-wrap">
          <table id="{table_id}">
            <thead>
              <tr>
                <th>#</th>
                <th>Player</th>
                <th>Threshold</th>
                <th>Line</th>
                <th>Odds</th>
                <th>Prop type</th>
                <th>Canonical selection</th>
                <th>Source selection</th>
                <th>Automatic warning</th>
              </tr>
            </thead>
            <tbody>
              {render_selection_rows(market, fixture_index, market_index)}
            </tbody>
          </table>
        </div>
      </div>
    </details>
    """


def render_match(match: dict[str, Any], fixture_index: int) -> str:
    match_name = clean(match.get("match")) or f"Fixture {fixture_index}"
    issues = build_match_issues(match)
    markets = get_markets(match)
    warning_html = (
        "<ul>" + "".join(f"<li>{esc(issue)}</li>" for issue in issues) + "</ul>"
        if issues
        else '<p class="all-good">No automatic fixture-level issues found.</p>'
    )

    market_html = "\n".join(
        render_market(market, fixture_index, idx)
        for idx, market in enumerate(markets, start=1)
    )

    return f"""
    <article class="fixture" id="fixture-{fixture_index}">
      <div class="fixture-header">
        <div>
          <h2>{esc(match_name)}</h2>
          <a class="source-link" href="{esc(match.get('url'))}" target="_blank" rel="noreferrer">
            Open William Hill event
          </a>
        </div>
        <div class="fixture-summary">
          <span class="badge">{len(markets)} markets</span>
          <span class="badge">{esc(match.get('player_selection_count'))} player selections</span>
          <span class="badge">{esc(match.get('elapsed_seconds'))}s</span>
          <span class="badge {'bad' if issues else 'ok'}">{len(issues)} review item(s)</span>
        </div>
      </div>

      <section>
        <h3>Required market checklist</h3>
        <div class="check-grid">
          {render_required_checklist(match)}
        </div>
      </section>

      <section class="issues {'has-issues' if issues else ''}">
        <h3>Automatic review notes</h3>
        {warning_html}
      </section>

      {render_fouls_comparison(match)}
      {render_scorer_comparison(match)}

      <section>
        <h3>All captured markets and selections</h3>
        <p class="hint">
          Expand a market and inspect the exact player, threshold, stored line,
          odds and source wording. Red rows have an automatic mapping/name warning.
        </p>
        {market_html}
      </section>
    </article>
    """


def build_html(data: dict[str, Any], input_path: Path) -> str:
    matches = as_rows(data)
    generated = datetime.now().astimezone().isoformat(timespec="seconds")

    nav = "".join(
        f'<a href="#fixture-{idx}">{esc(match.get("match") or f"Fixture {idx}")}</a>'
        for idx, match in enumerate(matches, start=1)
    )

    fixtures = "\n".join(
        render_match(match, idx)
        for idx, match in enumerate(matches, start=1)
    )

    total_issues = sum(len(build_match_issues(match)) for match in matches)

    embedded_summary = {
        "input": str(input_path),
        "source_generated_at": data.get("generated_at"),
        "match_count": len(matches),
        "total_review_items": total_issues,
    }

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>William Hill V12 TEST3 Review</title>
<style>
  :root {{
    --bg: #071126;
    --panel: #101d3c;
    --panel-2: #17274d;
    --text: #f5f7ff;
    --muted: #aeb9d5;
    --line: #33466f;
    --good: #39d98a;
    --bad: #ff6b6b;
    --warn: #ffd166;
    --link: #8ac5ff;
  }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: Arial, Helvetica, sans-serif;
    line-height: 1.45;
  }}
  a {{ color: var(--link); }}
  code {{
    background: #081329;
    border: 1px solid var(--line);
    border-radius: 5px;
    padding: 2px 5px;
  }}
  .top {{
    position: sticky;
    top: 0;
    z-index: 10;
    background: rgba(7, 17, 38, .96);
    border-bottom: 1px solid var(--line);
    padding: 14px 22px;
    backdrop-filter: blur(10px);
  }}
  .top h1 {{ margin: 0 0 5px; font-size: 22px; }}
  .top-meta {{ color: var(--muted); font-size: 13px; }}
  .nav {{
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 10px;
  }}
  .nav a {{
    text-decoration: none;
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-radius: 7px;
    padding: 6px 10px;
  }}
  main {{ max-width: 1700px; margin: 0 auto; padding: 22px; }}
  .overview {{
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 18px;
    margin-bottom: 22px;
  }}
  .fixture {{
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 20px;
    margin-bottom: 28px;
  }}
  .fixture-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 18px;
    border-bottom: 1px solid var(--line);
    padding-bottom: 14px;
    margin-bottom: 18px;
  }}
  h2 {{ margin: 0 0 6px; }}
  h3 {{ margin: 20px 0 10px; }}
  .source-link {{ font-size: 13px; }}
  .fixture-summary {{
    display: flex;
    gap: 7px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }}
  .badge {{
    display: inline-block;
    border: 1px solid var(--line);
    background: var(--panel-2);
    border-radius: 999px;
    padding: 4px 9px;
    font-size: 12px;
    white-space: nowrap;
  }}
  .badge.ok, .metric.ok {{ border-color: var(--good); color: var(--good); }}
  .badge.bad, .metric.bad {{ border-color: var(--bad); color: var(--bad); }}
  .check-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 10px;
  }}
  .check-card {{
    border: 1px solid var(--line);
    border-left-width: 5px;
    background: var(--panel-2);
    border-radius: 9px;
    padding: 11px;
  }}
  .check-card.ok {{ border-left-color: var(--good); }}
  .check-card.bad {{ border-left-color: var(--bad); }}
  .check-name {{ font-weight: bold; }}
  .check-count {{ font-size: 18px; margin-top: 4px; }}
  .check-sub {{ color: var(--muted); font-size: 12px; }}
  .issues {{
    border: 1px solid var(--line);
    border-radius: 9px;
    padding: 0 14px 10px;
    margin-top: 16px;
  }}
  .issues.has-issues {{ border-color: var(--warn); }}
  .issues li {{ margin: 5px 0; }}
  .all-good {{ color: var(--good); }}
  .comparison {{
    border: 1px solid var(--line);
    border-radius: 9px;
    padding: 0 14px 12px;
    margin-top: 16px;
  }}
  .metric-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 10px;
  }}
  .metric {{
    display: flex;
    flex-direction: column;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: var(--panel-2);
    padding: 11px;
  }}
  .metric b {{ font-size: 22px; }}
  .metric span, .metric small {{ color: var(--muted); }}
  .hint {{ color: var(--muted); font-size: 13px; }}
  .market-card {{
    border: 1px solid var(--line);
    border-radius: 10px;
    margin: 12px 0;
    overflow: hidden;
  }}
  .market-card summary {{
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    list-style: none;
    background: var(--panel-2);
    padding: 12px 14px;
  }}
  .market-card summary::-webkit-details-marker {{ display: none; }}
  .market-title {{
    font-size: 17px;
    font-weight: bold;
    margin-right: auto;
  }}
  .market-body {{ padding: 12px; }}
  .market-meta {{ color: var(--muted); font-size: 12px; margin-bottom: 9px; }}
  .market-search {{
    width: min(720px, 100%);
    background: #09152d;
    color: var(--text);
    border: 1px solid var(--line);
    border-radius: 7px;
    padding: 10px;
    margin-bottom: 10px;
  }}
  .table-wrap {{ overflow: auto; max-height: 700px; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  th {{
    position: sticky;
    top: 0;
    z-index: 2;
    background: #23365f;
    text-align: left;
    padding: 9px;
    border: 1px solid var(--line);
    white-space: nowrap;
  }}
  td {{
    padding: 8px;
    border: 1px solid var(--line);
    vertical-align: top;
  }}
  tr:nth-child(even) {{ background: rgba(255,255,255,.025); }}
  tr.problem-row {{ background: rgba(255, 107, 107, .14); }}
  td.odds {{ font-weight: bold; white-space: nowrap; }}
  td.problem {{ color: var(--bad); min-width: 220px; }}
  .footer {{
    color: var(--muted);
    text-align: center;
    padding: 20px;
    font-size: 12px;
  }}
  @media (max-width: 800px) {{
    .fixture-header {{ flex-direction: column; }}
    .fixture-summary {{ justify-content: flex-start; }}
  }}
</style>
<script>
function filterTable(tableId, value) {{
  const needle = (value || '').toLowerCase().trim();
  const table = document.getElementById(tableId);
  if (!table) return;
  for (const row of table.tBodies[0].rows) {{
    const haystack = row.dataset.search || row.innerText.toLowerCase();
    row.style.display = !needle || haystack.includes(needle) ? '' : 'none';
  }}
}}
</script>
</head>
<body>
<header class="top">
  <h1>William Hill V12 Impact Sub — TEST3 Review</h1>
  <div class="top-meta">
    Built {esc(generated)} · source JSON generated {esc(data.get("generated_at"))}
  </div>
  <nav class="nav">{nav}</nav>
</header>
<main>
  <section class="overview">
    <h2>Run overview</h2>
    <div class="metric-grid">
      <div class="metric"><b>{len(matches)}</b><span>Fixtures</span></div>
      <div class="metric"><b>{esc(data.get("matches_with_markets"))}</b><span>Fixtures with markets</span></div>
      <div class="metric"><b>{esc(data.get("total_player_markets"))}</b><span>Player markets</span></div>
      <div class="metric"><b>{esc(data.get("total_player_selections"))}</b><span>Player selections</span></div>
      <div class="metric"><b>{esc(data.get("elapsed_seconds"))}s</b><span>Scraper runtime</span></div>
      <div class="metric {'bad' if total_issues else 'ok'}"><b>{total_issues}</b><span>Total review items</span></div>
    </div>
    <p class="hint">
      Input: <code>{esc(input_path)}</code><br>
      Price mode: <code>{esc(data.get("player_price_mode"))}</code>
    </p>
  </section>
  {fixtures}
</main>
<footer class="footer">
  Generated locally. No production files were changed.
  <script type="application/json" id="review-summary">{html.escape(json.dumps(embedded_summary))}</script>
</footer>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a local HTML review site for William Hill V12 TEST3 data."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Input JSON (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()

    if not input_path.exists():
        print(f"ERROR: Input JSON not found:\n{input_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: Could not read JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print("ERROR: Expected a JSON object at the top level.", file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "index.html"
    output_path.write_text(build_html(data, input_path), encoding="utf-8")

    print("=" * 70)
    print("William Hill V12 local review site built")
    print("=" * 70)
    print(f"Input : {input_path}")
    print(f"Output: {output_path}")
    print()
    print("Open it directly, or run:")
    print(
        f'python -m http.server 8765 --directory "{output_dir}"'
    )
    print("Then visit: http://localhost:8765")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
