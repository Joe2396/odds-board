#!/usr/bin/env python3
"""
audit_williamhill_odds_READ_ONLY.py

Read-only William Hill production odds audit.

Checks:
- fractional odds validity;
- duplicate/conflicting selections;
- threshold-to-line mapping, e.g. 4+ -> 3.5;
- monotonic player threshold prices;
- monotonic Over/Under ladders;
- complete Over/Under pairs;
- scorer-market price relationships;
- overlap between match-stats and cards/corners outputs;
- moneyline price validity.

Outputs:
  football/debug/williamhill_odds_audit/audit_report.json
  football/debug/williamhill_odds_audit/index.html

This script never writes to production JSON.
"""

from __future__ import annotations

import html
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = ROOT / "football" / "data"
OUT_DIR = ROOT / "football" / "debug" / "williamhill_odds_audit"
REPORT_PATH = OUT_DIR / "audit_report.json"
HTML_PATH = OUT_DIR / "index.html"

FILES = {
    "moneylines": DATA_DIR / "williamhill_worldcup_moneylines.json",
    "props": DATA_DIR / "williamhill_worldcup_props.json",
    "match_stats": DATA_DIR / "williamhill_worldcup_match_stats.json",
    "cards_corners": DATA_DIR / "williamhill_worldcup_cards_corners.json",
}

ODDS_RE = re.compile(r"^(?:\d+/\d+|EVS|EVENS|EVEN)$", re.I)
THRESHOLD_RE = re.compile(r"^(\d+)\+$")
OU_RE = re.compile(r"^(over|under)\s+(\d+(?:\.\d+)?)$", re.I)

TEAM_ALIASES = {
    "bosnia": "bosnia_and_herzegovina",
    "bosnia_herzegovina": "bosnia_and_herzegovina",
    "bosnia_and_herzegovina": "bosnia_and_herzegovina",
    "congo_dr": "dr_congo",
    "dr_congo": "dr_congo",
    "ivory_coast": "cote_divoire",
    "cote_divoire": "cote_divoire",
    "south_korea": "korea_republic",
    "korea_republic": "korea_republic",
    "united_states": "usa",
    "usa": "usa",
    "turkey": "turkiye",
    "turkiye": "turkiye",
}


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value: Any) -> str:
    text = clean(value).lower().replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    aliases = {
        "anytime_scorer": "anytime_goalscorer",
        "to_score_2": "scorer_2_plus",
        "to_score_2_plus": "scorer_2_plus",
        "player_card": "player_cards",
        "player_shown_a_card": "player_cards",
        "match_total_corners": "total_corners",
        "match_total_cards": "total_cards",
    }
    return aliases.get(text, text)


def norm_team(value: Any) -> str:
    key = normalize(value)
    return TEAM_ALIASES.get(key, key)


def fixture_key(row: dict[str, Any]) -> str:
    home = clean(
        row.get("home_team")
        or row.get("home")
        or row.get("home_name")
    )
    away = clean(
        row.get("away_team")
        or row.get("away")
        or row.get("away_name")
    )
    name = clean(row.get("match") or row.get("name"))

    if (not home or not away) and " v " in name:
        home, away = [clean(x) for x in name.split(" v ", 1)]
    elif (not home or not away) and " vs " in name:
        home, away = [clean(x) for x in name.split(" vs ", 1)]

    return f"{norm_team(home)}_v_{norm_team(away)}"


def fixture_name(row: dict[str, Any]) -> str:
    value = clean(row.get("match") or row.get("name"))
    if value:
        return value

    home = clean(row.get("home_team") or row.get("home"))
    away = clean(row.get("away_team") or row.get("away"))
    return f"{home} v {away}".strip()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rows_from(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        rows = data.get("matches", [])
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def markets_from(row: dict[str, Any]) -> list[dict[str, Any]]:
    markets = row.get("markets", [])
    if not isinstance(markets, list):
        return []
    return [m for m in markets if isinstance(m, dict)]


def selections_from(market: dict[str, Any]) -> list[dict[str, Any]]:
    selections = market.get("selections", [])
    if not isinstance(selections, list):
        return []
    return [s for s in selections if isinstance(s, dict)]


def market_key(market: dict[str, Any]) -> str:
    return normalize(
        market.get("normalized_market") or market.get("market")
    )


def odds_decimal(value: Any) -> float | None:
    text = clean(value).upper()
    if text in {"EVS", "EVENS", "EVEN"}:
        return 2.0
    if not ODDS_RE.fullmatch(text):
        return None

    try:
        frac = Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None

    return 1.0 + float(frac)


def odds_valid(value: Any) -> bool:
    return odds_decimal(value) is not None


def selection_label(selection: dict[str, Any]) -> str:
    return clean(
        selection.get("selection")
        or selection.get("name")
        or selection.get("label")
    )


def selection_player(selection: dict[str, Any]) -> str:
    return clean(selection.get("player"))


def selection_threshold(selection: dict[str, Any]) -> str:
    return clean(selection.get("threshold"))


def selection_line(selection: dict[str, Any]) -> str:
    value = selection.get("line")
    return clean(value)


def selection_side(selection: dict[str, Any]) -> str:
    side = clean(selection.get("side")).lower()
    if side in {"over", "under"}:
        return side

    match = OU_RE.fullmatch(selection_label(selection))
    return match.group(1).lower() if match else ""


def numeric_line(selection: dict[str, Any]) -> float | None:
    line = selection_line(selection)
    if line:
        try:
            return float(line)
        except ValueError:
            pass

    match = OU_RE.fullmatch(selection_label(selection))
    if match:
        return float(match.group(2))
    return None


def semantic_selection_key(
    market: dict[str, Any],
    selection: dict[str, Any],
) -> tuple[str, ...]:
    return (
        market_key(market),
        normalize(selection_player(selection)),
        normalize(selection_label(selection)),
        selection_threshold(selection).lower(),
        selection_line(selection).lower(),
        selection_side(selection),
        normalize(selection.get("prop_type")),
        normalize(selection.get("team")),
    )


def exact_selection_key(
    market: dict[str, Any],
    selection: dict[str, Any],
) -> tuple[str, ...]:
    return semantic_selection_key(market, selection) + (
        clean(selection.get("odds")).upper(),
    )


def issue(
    severity: str,
    source: str,
    match: str,
    market: str,
    message: str,
    selection: str = "",
) -> dict[str, str]:
    return {
        "severity": severity,
        "source": source,
        "match": match,
        "market": market,
        "selection": selection,
        "message": message,
    }


def audit_market(
    source: str,
    match_name: str,
    market: dict[str, Any],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    name = clean(market.get("market"))
    selections = selections_from(market)

    declared = market.get("selection_count")
    if isinstance(declared, int) and declared != len(selections):
        issues.append(
            issue(
                "ERROR",
                source,
                match_name,
                name,
                f"selection_count says {declared}, but there are "
                f"{len(selections)} selection rows.",
            )
        )

    exact_seen: set[tuple[str, ...]] = set()
    semantic_odds: dict[tuple[str, ...], set[str]] = defaultdict(set)

    for selection in selections:
        label = selection_label(selection)
        price = clean(selection.get("odds")).upper()

        if not odds_valid(price):
            issues.append(
                issue(
                    "ERROR",
                    source,
                    match_name,
                    name,
                    f"Invalid fractional odds: {price or '[blank]'}.",
                    label,
                )
            )

        exact_key = exact_selection_key(market, selection)
        semantic_key = semantic_selection_key(market, selection)

        if exact_key in exact_seen:
            issues.append(
                issue(
                    "WARNING",
                    source,
                    match_name,
                    name,
                    "Exact duplicate selection row.",
                    label,
                )
            )
        exact_seen.add(exact_key)
        semantic_odds[semantic_key].add(price)

        threshold = selection_threshold(selection)
        threshold_match = THRESHOLD_RE.fullmatch(threshold)
        line = numeric_line(selection)

        if threshold_match and line is not None:
            expected = int(threshold_match.group(1)) - 0.5
            if not math.isclose(line, expected, abs_tol=1e-9):
                issues.append(
                    issue(
                        "ERROR",
                        source,
                        match_name,
                        name,
                        f"Threshold {threshold} should map to line "
                        f"{expected:g}, but got {line:g}.",
                        label,
                    )
                )

    for key, prices in semantic_odds.items():
        nonblank = {p for p in prices if p}
        if len(nonblank) > 1:
            issues.append(
                issue(
                    "ERROR",
                    source,
                    match_name,
                    name,
                    "The same semantic selection has conflicting odds: "
                    + ", ".join(sorted(nonblank)),
                    key[2],
                )
            )

    # Player threshold monotonicity:
    # 1+ must not be longer than 2+, 2+ must not be longer than 3+, etc.
    threshold_groups: dict[
        tuple[str, str],
        list[tuple[int, float, str, str]],
    ] = defaultdict(list)

    for selection in selections:
        threshold_match = THRESHOLD_RE.fullmatch(
            selection_threshold(selection)
        )
        player = selection_player(selection)
        decimal = odds_decimal(selection.get("odds"))
        if not threshold_match or not player or decimal is None:
            continue

        group_key = (
            normalize(player),
            normalize(selection.get("prop_type") or name),
        )
        threshold_groups[group_key].append(
            (
                int(threshold_match.group(1)),
                decimal,
                clean(selection.get("odds")),
                selection_label(selection),
            )
        )

    for (player_key, _), values in threshold_groups.items():
        by_threshold: dict[int, tuple[float, str, str]] = {}
        for threshold, decimal, fractional, label in values:
            current = by_threshold.get(threshold)
            if current is None:
                by_threshold[threshold] = (
                    decimal,
                    fractional,
                    label,
                )

        ordered = sorted(by_threshold.items())
        for (left_n, left), (right_n, right) in zip(
            ordered,
            ordered[1:],
        ):
            if right[0] + 1e-9 < left[0]:
                issues.append(
                    issue(
                        "ERROR",
                        source,
                        match_name,
                        name,
                        f"Threshold odds reverse for {player_key}: "
                        f"{left_n}+ is {left[1]}, but {right_n}+ is "
                        f"shorter at {right[1]}.",
                        right[2],
                    )
                )

    # O/U ladder checks.
    ou_rows: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
    line_sides: dict[float, set[str]] = defaultdict(set)

    for selection in selections:
        side = selection_side(selection)
        line = numeric_line(selection)
        decimal = odds_decimal(selection.get("odds"))
        if side not in {"over", "under"} or line is None or decimal is None:
            continue
        ou_rows[side].append(
            (line, decimal, clean(selection.get("odds")))
        )
        line_sides[line].add(side)

    if ou_rows:
        for line, sides in sorted(line_sides.items()):
            if sides != {"over", "under"}:
                issues.append(
                    issue(
                        "WARNING",
                        source,
                        match_name,
                        name,
                        f"Line {line:g} does not have both Over and Under.",
                    )
                )

        for side, values in ou_rows.items():
            dedup: dict[float, tuple[float, str]] = {}
            for line, decimal, fractional in values:
                dedup[line] = (decimal, fractional)

            ordered = sorted(dedup.items())
            for (left_line, left), (right_line, right) in zip(
                ordered,
                ordered[1:],
            ):
                wrong = (
                    side == "over"
                    and right[0] + 1e-9 < left[0]
                ) or (
                    side == "under"
                    and right[0] > left[0] + 1e-9
                )
                if wrong:
                    direction = (
                        "increase"
                        if side == "over"
                        else "decrease"
                    )
                    issues.append(
                        issue(
                            "ERROR",
                            source,
                            match_name,
                            name,
                            f"{side.title()} odds should generally "
                            f"{direction} as the line rises, but "
                            f"{left_line:g}={left[1]} and "
                            f"{right_line:g}={right[1]}.",
                        )
                    )

    return issues


def audit_scorer_relationships(
    source: str,
    row: dict[str, Any],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    name = fixture_name(row)

    market_lookup = {
        market_key(m): m for m in markets_from(row)
    }

    aliases = {
        "first": [
            "first_goalscorer",
            "first_goal_scorer",
        ],
        "anytime": [
            "anytime_goalscorer",
            "anytime_scorer",
        ],
        "two_plus": [
            "scorer_2_plus",
            "to_score_2_plus",
            "to_score_2",
        ],
    }

    picked: dict[str, dict[str, Any]] = {}
    for label, keys in aliases.items():
        for key in keys:
            normalized = normalize(key)
            if normalized in market_lookup:
                picked[label] = market_lookup[normalized]
                break

    def player_prices(market: dict[str, Any]) -> dict[str, tuple[float, str]]:
        result: dict[str, tuple[float, str]] = {}
        for selection in selections_from(market):
            player = normalize(selection_player(selection))
            decimal = odds_decimal(selection.get("odds"))
            fractional = clean(selection.get("odds"))
            if player and decimal is not None:
                result[player] = (decimal, fractional)
        return result

    anytime = player_prices(picked.get("anytime", {}))
    first = player_prices(picked.get("first", {}))
    two_plus = player_prices(picked.get("two_plus", {}))

    for player in sorted(set(anytime) & set(first)):
        if first[player][0] + 1e-9 < anytime[player][0]:
            issues.append(
                issue(
                    "ERROR",
                    source,
                    name,
                    "Scorer relationship",
                    f"First Goalscorer ({first[player][1]}) is shorter "
                    f"than Anytime ({anytime[player][1]}) for {player}.",
                    player,
                )
            )

    for player in sorted(set(anytime) & set(two_plus)):
        if two_plus[player][0] + 1e-9 < anytime[player][0]:
            issues.append(
                issue(
                    "ERROR",
                    source,
                    name,
                    "Scorer relationship",
                    f"To Score 2+ ({two_plus[player][1]}) is shorter "
                    f"than Anytime ({anytime[player][1]}) for {player}.",
                    player,
                )
            )

    return issues


def audit_source(
    source: str,
    data: Any,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    for row in rows_from(data):
        name = fixture_name(row)
        url = clean(row.get("url"))
        if not url:
            issues.append(
                issue(
                    "WARNING",
                    source,
                    name,
                    "",
                    "Missing event URL.",
                )
            )

        for market in markets_from(row):
            issues.extend(audit_market(source, name, market))

        if source == "props":
            issues.extend(audit_scorer_relationships(source, row))

    return issues


def audit_moneylines(data: Any) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    rows = rows_from(data)

    price_keys = [
        ("home", ["home_odds", "home_price"]),
        ("draw", ["draw_odds", "draw_price"]),
        ("away", ["away_odds", "away_price"]),
    ]

    for row in rows:
        name = fixture_name(row)
        for label, keys in price_keys:
            value = ""
            for key in keys:
                if row.get(key) not in {None, ""}:
                    value = clean(row.get(key))
                    break

            if not odds_valid(value):
                issues.append(
                    issue(
                        "ERROR",
                        "moneylines",
                        name,
                        "Match Betting",
                        f"Invalid {label} odds: {value or '[blank]'}.",
                        label,
                    )
                )

    return issues


def selection_map(market: dict[str, Any]) -> dict[tuple[str, float], str]:
    result: dict[tuple[str, float], str] = {}
    for selection in selections_from(market):
        side = selection_side(selection)
        line = numeric_line(selection)
        odds = clean(selection.get("odds")).upper()
        if side in {"over", "under"} and line is not None and odds:
            result[(side, line)] = odds
    return result


def compare_cards_corners(
    match_stats: Any,
    cards_corners: Any,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    left_rows = {
        fixture_key(row): row for row in rows_from(match_stats)
    }
    right_rows = {
        fixture_key(row): row for row in rows_from(cards_corners)
    }

    for key in sorted(set(left_rows) & set(right_rows)):
        left = left_rows[key]
        right = right_rows[key]
        name = fixture_name(left)

        left_markets = {
            market_key(m): m for m in markets_from(left)
        }
        right_markets = {
            market_key(m): m for m in markets_from(right)
        }

        for market_name in ["total_corners", "total_cards"]:
            left_market = left_markets.get(market_name)
            right_market = right_markets.get(market_name)
            if not left_market or not right_market:
                continue

            left_map = selection_map(left_market)
            right_map = selection_map(right_market)

            for selection_key in sorted(
                set(left_map) & set(right_map)
            ):
                if left_map[selection_key] != right_map[selection_key]:
                    side, line = selection_key
                    issues.append(
                        issue(
                            "WARNING",
                            "cross_file",
                            name,
                            market_name,
                            f"{side.title()} {line:g} differs between "
                            f"match_stats ({left_map[selection_key]}) and "
                            f"cards_corners ({right_map[selection_key]}). "
                            "This can be market movement or stale output.",
                            f"{side.title()} {line:g}",
                        )
                    )

    return issues


def source_metadata(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    return {
        "generated_at": data.get("generated_at"),
        "match_count": data.get("match_count"),
        "bookmaker": data.get("bookmaker"),
        "scraper_version": data.get("scraper_version"),
    }


def richest_fixture_keys(
    props: Any,
    match_stats: Any,
    limit: int = 3,
) -> list[str]:
    scores: dict[str, int] = defaultdict(int)

    for row in rows_from(props):
        scores[fixture_key(row)] += sum(
            len(selections_from(m))
            for m in markets_from(row)
        )

    for row in rows_from(match_stats):
        scores[fixture_key(row)] += 1000 * len(markets_from(row))

    return [
        key
        for key, _ in sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:limit]
    ]


def row_by_key(data: Any) -> dict[str, dict[str, Any]]:
    return {
        fixture_key(row): row
        for row in rows_from(data)
        if fixture_key(row) != "_v_"
    }


def esc(value: Any) -> str:
    return html.escape(clean(value), quote=True)


def render_market(market: dict[str, Any]) -> str:
    rows = []
    for selection in selections_from(market):
        rows.append(
            "<tr>"
            f"<td>{esc(selection_label(selection))}</td>"
            f"<td>{esc(selection_player(selection))}</td>"
            f"<td>{esc(selection_threshold(selection))}</td>"
            f"<td>{esc(selection_line(selection))}</td>"
            f"<td>{esc(selection_side(selection))}</td>"
            f"<td><strong>{esc(selection.get('odds'))}</strong></td>"
            "</tr>"
        )

    return (
        "<details>"
        f"<summary>{esc(market.get('market'))} "
        f"({len(rows)} selections)</summary>"
        "<table>"
        "<thead><tr><th>Selection</th><th>Player</th>"
        "<th>Threshold</th><th>Line</th><th>Side</th>"
        "<th>Odds</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></details>"
    )


def build_html(
    datasets: dict[str, Any],
    report: dict[str, Any],
) -> str:
    props_by_key = row_by_key(datasets.get("props"))
    stats_by_key = row_by_key(datasets.get("match_stats"))
    money_by_key = row_by_key(datasets.get("moneylines"))
    cc_by_key = row_by_key(datasets.get("cards_corners"))

    sample_keys = richest_fixture_keys(
        datasets.get("props"),
        datasets.get("match_stats"),
        limit=3,
    )

    issue_rows = []
    for item in report["issues"]:
        issue_rows.append(
            "<tr>"
            f"<td class='{item['severity'].lower()}'>"
            f"{esc(item['severity'])}</td>"
            f"<td>{esc(item['source'])}</td>"
            f"<td>{esc(item['match'])}</td>"
            f"<td>{esc(item['market'])}</td>"
            f"<td>{esc(item['selection'])}</td>"
            f"<td>{esc(item['message'])}</td>"
            "</tr>"
        )

    samples = []
    for key in sample_keys:
        candidates = [
            props_by_key.get(key),
            stats_by_key.get(key),
            money_by_key.get(key),
            cc_by_key.get(key),
        ]
        base = next((row for row in candidates if row), {})
        name = fixture_name(base)
        url = clean(
            (props_by_key.get(key) or {}).get("url")
            or (stats_by_key.get(key) or {}).get("url")
            or (money_by_key.get(key) or {}).get("url")
        )

        sections = []
        for source, lookup in [
            ("Moneylines", money_by_key),
            ("Main props", props_by_key),
            ("Match stats", stats_by_key),
            ("Cards/corners", cc_by_key),
        ]:
            row = lookup.get(key)
            if not row:
                continue

            if source == "Moneylines":
                sections.append(
                    "<details open><summary>Moneylines</summary>"
                    "<table><thead><tr><th>Home</th><th>Draw</th>"
                    "<th>Away</th></tr></thead><tbody><tr>"
                    f"<td>{esc(row.get('home_odds'))}</td>"
                    f"<td>{esc(row.get('draw_odds'))}</td>"
                    f"<td>{esc(row.get('away_odds'))}</td>"
                    "</tr></tbody></table></details>"
                )
            else:
                market_html = "".join(
                    render_market(m)
                    for m in markets_from(row)
                )
                sections.append(
                    f"<h3>{esc(source)}</h3>{market_html}"
                )

        link = (
            f'<a href="{esc(url)}" target="_blank" '
            'rel="noopener">Open live William Hill event</a>'
            if url
            else "<span>No event URL</span>"
        )

        samples.append(
            "<section class='fixture'>"
            f"<h2>{esc(name)}</h2>"
            f"<p>{link}</p>"
            "<p class='hint'>Compare the exact player, threshold/line and "
            "fractional price. Do not compare only the market total.</p>"
            f"{''.join(sections)}"
            "</section>"
        )

    status = report["status"]
    status_class = "pass" if status == "PASS" else "fail"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>William Hill Odds Audit</title>
<style>
body {{
  font-family: Arial, sans-serif;
  margin: 0;
  background: #f3f5f7;
  color: #17212b;
}}
header {{
  background: #111827;
  color: white;
  padding: 24px;
}}
main {{
  max-width: 1500px;
  margin: 0 auto;
  padding: 20px;
}}
.card, .fixture {{
  background: white;
  border-radius: 10px;
  padding: 18px;
  margin: 0 0 18px;
  box-shadow: 0 2px 8px rgba(0,0,0,.08);
}}
.status {{
  display: inline-block;
  padding: 7px 12px;
  border-radius: 999px;
  font-weight: bold;
}}
.status.pass {{ background: #dcfce7; color: #166534; }}
.status.fail {{ background: #fee2e2; color: #991b1b; }}
table {{
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0 18px;
  font-size: 14px;
}}
th, td {{
  border: 1px solid #d9dee5;
  padding: 7px;
  text-align: left;
  vertical-align: top;
}}
th {{ background: #eef2f7; }}
.error {{ color: #b91c1c; font-weight: bold; }}
.warning {{ color: #a16207; font-weight: bold; }}
details {{
  margin: 9px 0;
  border: 1px solid #d9dee5;
  border-radius: 7px;
  padding: 8px;
}}
summary {{
  cursor: pointer;
  font-weight: bold;
}}
.hint {{ color: #52606d; }}
a {{ color: #075db7; font-weight: bold; }}
</style>
</head>
<body>
<header>
  <h1>William Hill Production Odds Audit</h1>
  <p>Generated {esc(report['generated_at'])}</p>
</header>
<main>
<section class="card">
  <span class="status {status_class}">{esc(status)}</span>
  <p>
    Errors: <strong>{report['error_count']}</strong> |
    Warnings: <strong>{report['warning_count']}</strong> |
    Files checked: <strong>{report['files_checked']}</strong>
  </p>
  <p>This page is read-only. The live links are for manual spot-checking.</p>
</section>

<section class="card">
  <h2>Automatic audit findings</h2>
  <table>
    <thead><tr>
      <th>Severity</th><th>Source</th><th>Match</th>
      <th>Market</th><th>Selection</th><th>Finding</th>
    </tr></thead>
    <tbody>
      {''.join(issue_rows) if issue_rows else '<tr><td colspan="6">No automatic issues found.</td></tr>'}
    </tbody>
  </table>
</section>

<section class="card">
  <h2>Live spot-check method</h2>
  <ol>
    <li>Open the William Hill event link.</li>
    <li>Choose the exact market shown below.</li>
    <li>Compare player/selection, threshold or line, and fractional odds.</li>
    <li>Check at least one low, middle and high threshold per player market.</li>
    <li>For Corners/Cards, compare every displayed Over/Under line.</li>
  </ol>
</section>

{''.join(samples)}
</main>
</body>
</html>
"""


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    datasets: dict[str, Any] = {}
    missing: list[str] = []

    for name, path in FILES.items():
        if not path.exists():
            missing.append(str(path))
            continue
        try:
            datasets[name] = read_json(path)
        except Exception as exc:
            print(f"ERROR reading {path}: {exc}")
            return 1

    if "moneylines" not in datasets:
        print("Missing canonical William Hill moneylines JSON.")
        return 1
    if "props" not in datasets:
        print("Missing canonical William Hill props JSON.")
        return 1
    if "match_stats" not in datasets:
        print("Missing canonical William Hill match-stats JSON.")
        return 1

    issues: list[dict[str, str]] = []
    issues.extend(audit_moneylines(datasets["moneylines"]))

    for source in ["props", "match_stats", "cards_corners"]:
        if source in datasets:
            issues.extend(audit_source(source, datasets[source]))

    if "cards_corners" in datasets:
        issues.extend(
            compare_cards_corners(
                datasets["match_stats"],
                datasets["cards_corners"],
            )
        )

    severity_rank = {"ERROR": 0, "WARNING": 1}
    issues.sort(
        key=lambda item: (
            severity_rank.get(item["severity"], 9),
            item["match"],
            item["source"],
            item["market"],
            item["selection"],
        )
    )

    errors = [i for i in issues if i["severity"] == "ERROR"]
    warnings = [i for i in issues if i["severity"] == "WARNING"]

    report = {
        "status": "PASS" if not errors else "FAIL",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files_checked": len(datasets),
        "missing_optional_files": missing,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "metadata": {
            name: source_metadata(data)
            for name, data in datasets.items()
        },
        "issues": issues,
    }

    REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    HTML_PATH.write_text(
        build_html(datasets, report),
        encoding="utf-8",
    )

    print("=" * 68)
    print("William Hill odds audit — READ ONLY")
    print("=" * 68)
    print(f"Status:   {report['status']}")
    print(f"Errors:   {report['error_count']}")
    print(f"Warnings: {report['warning_count']}")
    print(f"Report:   {REPORT_PATH}")
    print(f"Review:   {HTML_PATH}")

    if missing:
        print("\nOptional/missing files:")
        for path in missing:
            print(f"  - {path}")

    if issues:
        print("\nFirst 25 findings:")
        for item in issues[:25]:
            selection = (
                f" | {item['selection']}"
                if item["selection"]
                else ""
            )
            print(
                f"  [{item['severity']}] {item['match']} | "
                f"{item['source']} | {item['market']}"
                f"{selection} — {item['message']}"
            )

    print("\nOpen the review page with:")
    print(
        r'start "" "football\debug\williamhill_odds_audit\index.html"'
    )

    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
