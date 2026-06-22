#!/usr/bin/env python3
import json
import os
import re
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

BOOK_FILES = {
    "PaddyPower": os.path.join(ROOT, "football", "data", "paddypower_worldcup_moneylines.json"),
    "BoyleSports": os.path.join(ROOT, "football", "data", "boylesports_worldcup_moneylines.json"),
    "BetVictor": os.path.join(ROOT, "football", "data", "betvictor_worldcup_moneylines.json"),
    "Unibet": os.path.join(ROOT, "football", "data", "unibet_worldcup_moneylines.json"),
    "LiveScoreBet": os.path.join(ROOT, "football", "data", "livescorebet_worldcup_moneylines.json"),
    "WilliamHill": os.path.join(ROOT, "football", "data", "williamhill_worldcup_moneylines.json"),
    "888Sport": os.path.join(ROOT, "football", "data", "888sport_worldcup_moneylines.json"),
}

OUT_PATH = os.path.join(ROOT, "football", "data", "arbitrage.json")


def fractional_to_decimal(value):
    value = str(value or "").strip().upper()

    if value in {"EVS", "EVENS", "EVEN"}:
        return 2.0

    if "/" in value:
        try:
            num, den = value.split("/", 1)
            return round((float(num) / float(den)) + 1, 6)
        except Exception:
            return None

    try:
        decimal = float(value)
        if decimal > 1:
            return decimal
    except Exception:
        pass

    return None


def implied_probability(decimal_odds):
    if not decimal_odds or decimal_odds <= 1:
        return None
    return 1 / decimal_odds


def normalize_team(name):
    name = str(name or "").lower().strip()

    replacements = {
        "türkiye": "turkiye",
        "turkey": "turkiye",
        "czech republic": "czechia",
        "bosnia & herzegovina": "bosnia",
        "bosnia and herzegovina": "bosnia",
        "cape verde islands": "cape verde",
        "congo dr": "dr congo",
        "curaçao": "curacao",
    }

    for old, new in replacements.items():
        name = name.replace(old, new)

    name = re.sub(r"[^a-z0-9]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()

    return name


def fixture_key(home, away):
    return f"{normalize_team(home)}__{normalize_team(away)}"


def loose_fixture_key(home, away):
    teams = sorted([normalize_team(home), normalize_team(away)])
    return "__".join(teams)


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def add_offer(fixtures, key, side, bookmaker, raw_odds, row):
    decimal = fractional_to_decimal(raw_odds)

    if not decimal or decimal <= 1:
        return

    fixtures[key]["selections"][side].append({
        "bookmaker": bookmaker,
        "odds": raw_odds,
        "decimal_odds": decimal,
        "implied_probability": round(implied_probability(decimal), 6),
        "source_url": row.get("source_url") or "",
    })



# ── Props arbitrage ────────────────────────────────────────────────────────────

PROPS_FILES = {
    "PaddyPower":   ("paddypower_worldcup_props.json",   "fractional"),
    "BoyleSports":  ("boylesports_worldcup_props_complete.json", "fractional"),
    "LiveScoreBet": ("livescorebet_worldcup_props.json", "fractional"),
    "Ladbrokes":    ("ladbrokes_worldcup_props.json",    "fractional"),
    "WilliamHill":  ("williamhill_worldcup_props.json",  "fractional"),
    "BetVictor":    ("betvictor_worldcup_props.json",    "fractional"),
    # "Midnite":    ("midnite_worldcup_props.json",      "fractional"),  # dict format, not list
    # "Unibet":     ("unibet_worldcup_props.json",       "fractional"),  # not ready
}

OU_MARKET_KEYS = {
    "total_goals_over_under", "total_goals_over", "total_goals",
    "first_half_goals_over_under", "first_half_goals",
    "total_corners_over_under", "total_corners",
    "total_cards_over_under", "total_match_cards",
    "total_shots_on_target_over_under", "total_shots_over_under",
}


def normalize_key(s):
    s = str(s or "").lower().replace("&", "and").replace("?", "")
    import re as _re
    return _re.sub(r"[^a-z0-9]+", "_", s).strip("_")


PLAYER_MARKET_WORDS = {
    "player", "goalscorer", "to_score", "to_assist", "tackles",
    "fouls", "carded", "to_get_a_card",
}


def classify_prop_metric(market_name):
    mk = normalize_key(market_name)

    if any(word in mk for word in PLAYER_MARKET_WORDS):
        return None

    if "shots_on_target" in mk:
        return "shots_on_target", "Shots On Target"
    if "shots" in mk:
        return "shots", "Shots"
    if "corners" in mk:
        return "corners", "Corners"
    if "cards" in mk or "booking_points" in mk:
        return "cards", "Cards"
    if "first_half" in mk and "goals" in mk:
        return "first_half_goals", "First Half Goals"
    if "goals" in mk:
        return "goals", "Goals"

    return None


def _canonical_fixture_team(value, home, away):
    value = normalize_team(value)
    home_c = normalize_team(home)
    away_c = normalize_team(away)

    if value == home_c:
        return home_c
    if value == away_c:
        return away_c
    return ""


def resolve_prop_identity(market_name, selection, selection_name, home, away):
    """
    Resolve a strict market identity using all available evidence.

    This understands:
      - actual team names in the market title
      - Home / Away market titles
      - selection["team"] metadata
      - actual team names in the selection label

    Returns:
      (canonical_key, display_name, scope, scope_team, metric)
    or:
      (None, reason)
    """
    metric_info = classify_prop_metric(market_name)
    if not metric_info:
        return None, "unsupported/player market"

    metric, label = metric_info
    mk = normalize_key(market_name)
    sn = normalize_key(selection_name)

    home_c = normalize_team(home)
    away_c = normalize_team(away)
    home_k = normalize_key(home_c)
    away_k = normalize_key(away_c)

    candidates = []

    # Actual team names in the market title.
    if home_k and home_k in mk:
        candidates.append(home_c)
    if away_k and away_k in mk:
        candidates.append(away_c)

    # Generic Home / Away market titles.
    title_tokens = set(mk.split("_"))
    if "home" in title_tokens:
        candidates.append(home_c)
    if "away" in title_tokens:
        candidates.append(away_c)

    # Explicit team metadata from the scraper.
    explicit_team = _canonical_fixture_team(
        selection.get("team") or "",
        home,
        away,
    )
    if explicit_team:
        candidates.append(explicit_team)

    # Actual team names in the selection text.
    if home_k and home_k in sn:
        candidates.append(home_c)
    if away_k and away_k in sn:
        candidates.append(away_c)

    unique_candidates = {x for x in candidates if x}

    if len(unique_candidates) > 1:
        return None, "conflicting team scope"

    if len(unique_candidates) == 1:
        scope_team = next(iter(unique_candidates))
        canonical = f"team_{metric}::{scope_team}"
        display = f"{scope_team.title()} Total {label} Over Under"
        return canonical, display, "team", scope_team, metric

    # A title that explicitly says home/away/team but could not be resolved
    # must not silently become a match total.
    team_markers = {
        "home", "away", "team", "team_total", "home_team", "away_team",
    }
    if any(marker in mk for marker in team_markers):
        return None, "ambiguous team scope"

    canonical = f"match_{metric}"
    display = f"Total {label} Over Under"
    return canonical, display, "match", "", metric


def should_quarantine_offer(bookmaker, canonical_market, line):
    """
    Keep confirmed bad source rows off the live board until their source parser
    has been repaired and verified.
    """
    line = str(line or "").strip()

    if (
        bookmaker == "BetVictor"
        and canonical_market == "match_goals"
        and line == "0.5"
    ):
        return "BetVictor unverified Total Goals 0.5"

    return ""


def remove_duplicate_match_team_ladders(data, rejected):
    """
    If one bookmaker produces an identical full ladder for a match total and a
    team total, the team scope is almost certainly a parser copy/misclick.

    The comparison requires at least four identical selections, so one
    coincidental matching price is not enough to trigger it.
    """
    for fixture_markets in data.values():
        by_metric = {}

        for canonical_mk, lines in fixture_markets.items():
            if canonical_mk.startswith("match_"):
                metric = canonical_mk[len("match_"):]
                scope = "match"
            elif canonical_mk.startswith("team_"):
                metric = canonical_mk[len("team_"):].split("::", 1)[0]
                scope = "team"
            else:
                continue

            by_metric.setdefault(metric, []).append(
                (canonical_mk, scope, lines)
            )

        for metric, entries in by_metric.items():
            match_entries = [e for e in entries if e[1] == "match"]
            team_entries = [e for e in entries if e[1] == "team"]

            if not match_entries or not team_entries:
                continue

            match_key, _, match_lines = match_entries[0]

            bookmakers = set()
            for sides in match_lines.values():
                for offers in sides.values():
                    bookmakers.update(o["bookmaker"] for o in offers)

            for bookmaker in bookmakers:
                match_fp = set()
                for line, sides in match_lines.items():
                    for side, offers in sides.items():
                        for offer in offers:
                            if offer["bookmaker"] == bookmaker:
                                match_fp.add((line, side, offer["odds"]))

                if len(match_fp) < 4:
                    continue

                for team_key, _, team_lines in team_entries:
                    team_fp = set()
                    for line, sides in team_lines.items():
                        for side, offers in sides.items():
                            for offer in offers:
                                if offer["bookmaker"] == bookmaker:
                                    team_fp.add((line, side, offer["odds"]))

                    if team_fp != match_fp:
                        continue

                    removed = 0
                    for line, sides in team_lines.items():
                        for side in list(sides):
                            before = len(sides[side])
                            sides[side] = [
                                o for o in sides[side]
                                if o["bookmaker"] != bookmaker
                            ]
                            removed += before - len(sides[side])

                    if removed:
                        reason = (
                            f"{bookmaker} duplicate match/team {metric} ladder"
                        )
                        rejected[reason] = rejected.get(reason, 0) + removed



def scan_props_arbitrage(root):
    """Scan strictly matched O/U prop markets across bookmakers."""
    data = {}
    rejected = {}

    def reject(reason):
        rejected[reason] = rejected.get(reason, 0) + 1

    for bk, (fname, fmt) in PROPS_FILES.items():
        path = os.path.join(root, "football", "data", fname)
        raw = load_json(path)
        if not raw:
            continue

        matches = raw.get("matches") or []
        if isinstance(raw, list):
            matches = raw

        for m in matches:
            home = m.get("home_team", "")
            away = m.get("away_team", "")
            if not home or not away:
                continue

            fk = fixture_key(home, away)
            markets = m.get("markets") or {}

            if isinstance(markets, list):
                markets = {
                    mk.get("market", ""): mk
                    for mk in markets
                    if isinstance(mk, dict)
                }

            for mkt_name, mkt_data in markets.items():
                if not isinstance(mkt_data, dict):
                    continue

                sels = mkt_data.get("selections") or []

                for sel in sels:
                    if not isinstance(sel, dict):
                        continue

                    sn = sel.get("selection", "")
                    odds_raw = sel.get("odds") or sel.get("price", "")
                    side = str(sel.get("side") or "").lower().strip()
                    line = str(sel.get("line") or "").strip()

                    if not side or not line:
                        m2 = re.search(
                            r"\b(over|under)\s+([\d.]+)\b",
                            str(sn),
                            re.I,
                        )
                        if m2:
                            side = m2.group(1).lower()
                            line = m2.group(2)

                    if side not in {"over", "under"} or not line or not odds_raw:
                        continue

                    identity = resolve_prop_identity(
                        mkt_name,
                        sel,
                        sn,
                        home,
                        away,
                    )

                    if not identity or identity[0] is None:
                        reason = (
                            identity[1]
                            if identity and len(identity) > 1
                            else "unresolved market identity"
                        )
                        reject(reason)
                        continue

                    (
                        canonical_mk,
                        display_name,
                        scope,
                        scope_team,
                        metric,
                    ) = identity

                    quarantine_reason = should_quarantine_offer(
                        bk,
                        canonical_mk,
                        line,
                    )
                    if quarantine_reason:
                        reject(quarantine_reason)
                        continue

                    dec = fractional_to_decimal(odds_raw)
                    if not dec or dec <= 1:
                        continue

                    offer = {
                        "bookmaker": bk,
                        "odds": odds_raw,
                        "decimal": dec,
                        "match": f"{home} v {away}",
                        "market": display_name,
                        "source_market": mkt_name,
                        "scope": scope,
                        "scope_team": scope_team,
                        "metric": metric,
                    }

                    data.setdefault(fk, {}).setdefault(
                        canonical_mk, {}
                    ).setdefault(line, {}).setdefault(side, []).append(offer)

    remove_duplicate_match_team_ladders(data, rejected)

    arbs = []
    near_misses = []

    for fk, markets in data.items():
        for canonical_mk, lines in markets.items():
            for line, sides in lines.items():
                overs = sides.get("over") or []
                unders = sides.get("under") or []
                if not overs or not unders:
                    continue

                pairs = [
                    (over, under)
                    for over in overs
                    for under in unders
                    if over["bookmaker"] != under["bookmaker"]
                ]
                if not pairs:
                    continue

                best_over, best_under = min(
                    pairs,
                    key=lambda pair: (
                        (1 / pair[0]["decimal"])
                        + (1 / pair[1]["decimal"])
                    ),
                )

                arb_sum = (
                    (1 / best_over["decimal"])
                    + (1 / best_under["decimal"])
                )

                row = {
                    "sport": "Football",
                    "competition": "FIFA World Cup",
                    "type": "props_ou",
                    "match": best_over["match"],
                    "market": best_over["market"],
                    "canonical_market": canonical_mk,
                    "scope": best_over["scope"],
                    "scope_team": best_over["scope_team"],
                    "line": line,
                    "arb_sum": round(arb_sum, 6),
                    "arb_percent": round(arb_sum * 100, 3),
                    "profit_margin_percent": round(
                        ((1 / arb_sum) - 1) * 100,
                        3,
                    ),
                    "bookmaker_count": 2,
                    "selections": {
                        "over": {
                            "bookmaker": best_over["bookmaker"],
                            "odds": best_over["odds"],
                            "decimal_odds": best_over["decimal"],
                            "source_market": best_over["source_market"],
                        },
                        "under": {
                            "bookmaker": best_under["bookmaker"],
                            "odds": best_under["odds"],
                            "decimal_odds": best_under["decimal"],
                            "source_market": best_under["source_market"],
                        },
                    },
                    "all_prices": {
                        "over": sorted(
                            overs,
                            key=lambda x: x["decimal"],
                            reverse=True,
                        ),
                        "under": sorted(
                            unders,
                            key=lambda x: x["decimal"],
                            reverse=True,
                        ),
                    },
                }

                if arb_sum < 1:
                    arbs.append(row)
                elif arb_sum < 1.04:
                    near_misses.append(row)

    arbs.sort(
        key=lambda x: x["profit_margin_percent"],
        reverse=True,
    )
    near_misses.sort(key=lambda x: x["arb_sum"])

    if rejected:
        print("Props safety filters:")
        for reason, count in sorted(rejected.items()):
            print(f"  - {reason}: {count} offer(s) skipped")

    return arbs, near_misses

def main():
    fixtures = {}
    strict_index = {}
    loose_index = {}

    bookmaker_summary = {}

    for bookmaker, path in BOOK_FILES.items():
        data = load_json(path)

        if not data:
            bookmaker_summary[bookmaker] = {
                "file_found": False,
                "matches_loaded": 0,
                "path": path,
            }
            print(f"{bookmaker}: file missing or unreadable")
            continue

        rows = data.get("matches") or []
        loaded = 0

        for row in rows:
            home = row.get("home_team") or ""
            away = row.get("away_team") or ""
            odds = row.get("odds") or {}

            if not home or not away or not odds:
                continue

            strict_key = fixture_key(home, away)
            loose_key = loose_fixture_key(home, away)

            target_key = None

            if strict_key in strict_index:
                target_key = strict_index[strict_key]
            elif loose_key in loose_index:
                target_key = loose_index[loose_key]

            if not target_key:
                target_key = strict_key

                fixtures[target_key] = {
                    "sport": "Football",
                    "competition": row.get("competition") or "FIFA World Cup",
                    "match": row.get("match") or f"{home} v {away}",
                    "home_team": home,
                    "away_team": away,
                    "date_label": row.get("date_label") or "",
                    "time": row.get("time") or "",
                    "strict_key": strict_key,
                    "loose_key": loose_key,
                    "selections": {
                        "home": [],
                        "draw": [],
                        "away": [],
                    },
                    "bookmakers_seen": set(),
                }

                strict_index[strict_key] = target_key
                loose_index[loose_key] = target_key

            fixtures[target_key]["bookmakers_seen"].add(bookmaker)

            add_offer(fixtures, target_key, "home", bookmaker, odds.get("home"), row)
            add_offer(fixtures, target_key, "draw", bookmaker, odds.get("draw"), row)
            add_offer(fixtures, target_key, "away", bookmaker, odds.get("away"), row)

            loaded += 1

        bookmaker_summary[bookmaker] = {
            "file_found": True,
            "matches_loaded": loaded,
            "path": path,
        }

        print(f"{bookmaker}: loaded {loaded} matches")

    arbitrage = []
    near_misses = []

    compared_fixtures = 0
    skipped_fixtures = 0

    for key, fixture in fixtures.items():
        selections = fixture["selections"]

        if not selections["home"] or not selections["draw"] or not selections["away"]:
            skipped_fixtures += 1
            continue

        compared_fixtures += 1

        best_home = max(selections["home"], key=lambda x: x["decimal_odds"])
        best_draw = max(selections["draw"], key=lambda x: x["decimal_odds"])
        best_away = max(selections["away"], key=lambda x: x["decimal_odds"])

        arb_sum = (
            (1 / best_home["decimal_odds"])
            + (1 / best_draw["decimal_odds"])
            + (1 / best_away["decimal_odds"])
        )

        arb_percent = arb_sum * 100
        profit_margin_percent = ((1 / arb_sum) - 1) * 100

        row = {
            "sport": "Football",
            "competition": fixture["competition"],
            "type": "moneyline_1x2",
            "match": fixture["match"],
            "home_team": fixture["home_team"],
            "away_team": fixture["away_team"],
            "date_label": fixture["date_label"],
            "time": fixture["time"],
            "market": "Match Odds",
            "bookmaker_count": len(fixture["bookmakers_seen"]),
            "arb_sum": round(arb_sum, 6),
            "arb_percent": round(arb_percent, 3),
            "profit_margin_percent": round(profit_margin_percent, 3),
            "selections": {
                "home": best_home,
                "draw": best_draw,
                "away": best_away,
            },
            "all_prices": {
                "home": sorted(selections["home"], key=lambda x: x["decimal_odds"], reverse=True),
                "draw": sorted(selections["draw"], key=lambda x: x["decimal_odds"], reverse=True),
                "away": sorted(selections["away"], key=lambda x: x["decimal_odds"], reverse=True),
            },
        }

        if arb_sum < 1:
            arbitrage.append(row)
        else:
            near_misses.append(row)

    arbitrage.sort(key=lambda x: x["profit_margin_percent"], reverse=True)
    near_misses.sort(key=lambda x: x["arb_sum"])

    # Convert set() before writing JSON.
    for fixture in fixtures.values():
        fixture["bookmakers_seen"] = sorted(list(fixture["bookmakers_seen"]))

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sport": "Football",
        "competition": "FIFA World Cup",
        "bookmaker_summary": bookmaker_summary,
        "fixture_count": len(fixtures),
        "compared_fixtures": compared_fixtures,
        "skipped_fixtures": skipped_fixtures,
        "arbitrage_count": len(arbitrage),
        "near_miss_count": len(near_misses),
        "arbitrage": arbitrage,
        "near_misses": near_misses[:25],
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

    # Props arbitrage
    props_arbs, props_near_misses = scan_props_arbitrage(ROOT)
    print(f"Props arb opportunities: {len(props_arbs)}")
    print(f"Props near misses: {len(props_near_misses)}")

    all_arbs = arbitrage + props_arbs
    all_near_misses = (near_misses + props_near_misses)
    all_near_misses.sort(key=lambda x: x["arb_sum"])

    output["arbitrage"] = all_arbs
    output["near_misses"] = all_near_misses[:25]
    output["arbitrage_count"] = len(all_arbs)
    output["near_miss_count"] = len(all_near_misses)
    output["props_arb_count"] = len(props_arbs)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("")
    print("Football arbitrage scan complete")
    print(f"Fixtures found: {len(fixtures)}")
    print(f"Fixtures compared: {compared_fixtures}")
    print(f"Fixtures skipped: {skipped_fixtures}")
    print(f"Arbitrage opportunities: {len(arbitrage)}")
    print(f"Near misses saved: {min(len(near_misses), 25)}")
    print(f"Saved to: {OUT_PATH}")

    if arbitrage:
        print("")
        print("Top arbitrage opportunities:")
        for arb in arbitrage[:10]:
            print(
                f"- {arb['match']} | "
                f"profit {arb['profit_margin_percent']}% | "
                f"home {arb['selections']['home']['odds']} {arb['selections']['home']['bookmaker']} | "
                f"draw {arb['selections']['draw']['odds']} {arb['selections']['draw']['bookmaker']} | "
                f"away {arb['selections']['away']['odds']} {arb['selections']['away']['bookmaker']}"
            )
    else:
        print("")
        print("No live football arbs found right now.")
        print("Closest near misses:")
        for miss in near_misses[:10]:
            print(
                f"- {miss['match']} | "
                f"arb {miss['arb_percent']}% | "
                f"home {miss['selections']['home']['odds']} {miss['selections']['home']['bookmaker']} | "
                f"draw {miss['selections']['draw']['odds']} {miss['selections']['draw']['bookmaker']} | "
                f"away {miss['selections']['away']['odds']} {miss['selections']['away']['bookmaker']}"
            )


if __name__ == "__main__":
    main()