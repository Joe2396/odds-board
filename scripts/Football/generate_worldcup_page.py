#!/usr/bin/env python3
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PADDY_PATH = ROOT / "football" / "data" / "paddypower_worldcup_moneylines.json"
BOYLE_PATH = ROOT / "football" / "data" / "boylesports_worldcup_moneylines.json"
BETVICTOR_PATH = ROOT / "football" / "data" / "betvictor_worldcup_moneylines.json"
UNIBET_PATH = ROOT / "football" / "data" / "unibet_worldcup_moneylines.json"
LIVESCOREBET_PATH = ROOT / "football" / "data" / "livescorebet_worldcup_moneylines.json"
WILLIAMHILL_PATH = ROOT / "football" / "data" / "williamhill_worldcup_moneylines.json"
EIGHTEIGHTEIGHT_PATH = ROOT / "football" / "data" / "888sport_worldcup_moneylines.json"

PADDY_PROPS_PATH = ROOT / "football" / "data" / "paddypower_worldcup_props.json"
BOYLE_PROPS_PATH = ROOT / "football" / "data" / "boylesports_worldcup_props.json"
UNIBET_PROPS_PATH = ROOT / "football" / "data" / "unibet_worldcup_props.json"

OUT_DIR = ROOT / "football" / "world-cup"
OUT_PATH = OUT_DIR / "index.html"
HUB_PATH = ROOT / "football" / "index.html"

BASE = "/odds-board"

def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def esc(s):
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def slugify(s):
    s = str(s or "").lower()
    s = s.replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def fractional_to_decimal(value):
    value = str(value or "").strip().upper()
    if value in {"EVS", "EVENS", "EVEN"}:
        return 2.0
    if "/" in value:
        try:
            a, b = value.split("/", 1)
            return (float(a) / float(b)) + 1
        except Exception:
            return 0
    try:
        val = float(value)
        if val > 1:
            return val
    except Exception:
        pass
    return 0


def display_team(s):
    s = str(s or "").strip()
    aliases = {
        "Bosnia & Herzegovina": "Bosnia & Herzegovina",
        "Bosnia and Herzegovina": "Bosnia & Herzegovina",
        "Czech Republic": "Czechia",
        "Turkey": "Türkiye",
        "Turkiye": "Türkiye",
        "Curaçao": "Curacao",
    }
    return aliases.get(s, s)


def key_team(s):
    s = display_team(s).lower()
    s = s.replace("&", "and")
    s = s.replace("herzegovina", "")
    s = s.replace("türkiye", "turkiye")
    s = s.replace("turkey", "turkiye")
    s = s.replace("curaçao", "curacao")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    aliases = {
        "bosnia and": "bosnia",
        "bosnia": "bosnia",
        "czech republic": "czechia",
        "czechia": "czechia",
        "ivory coast": "ivory coast",
        "curacao": "curacao",
        "turkiye": "turkiye",
        "dr congo": "dr congo",
        "usa": "usa",
    }
    return aliases.get(s, s)


def fixture_key(home, away):
    return f"{key_team(home)}__{key_team(away)}"


def loose_fixture_key(home, away):
    parts = sorted([key_team(home), key_team(away)])
    return "__".join(parts)


def load_book(bookmaker, path):
    data = load_json(path)
    rows = []
    for m in data.get("matches") or []:
        home = display_team(m.get("home_team"))
        away = display_team(m.get("away_team"))
        if not home or not away:
            continue
        rows.append({
            "bookmaker": bookmaker,
            "date_label": m.get("date_label") or "",
            "time": m.get("time") or "",
            "match": f"{home} v {away}",
            "home_team": home,
            "away_team": away,
            "odds": m.get("odds") or {},
            "source_url": m.get("source_url") or "",
            "strict_key": fixture_key(home, away),
            "loose_key": loose_fixture_key(home, away),
            "generated_at": data.get("generated_at") or "",
        })
    return rows, data.get("generated_at") or ""


def split_match_name(match_name):
    match_name = clean(match_name)
    if re.search(r"\s+v\s+", match_name, re.I):
        home, away = re.split(r"\s+v\s+", match_name, maxsplit=1, flags=re.I)
        return display_team(home), display_team(away)
    return "", ""


def pretty_market_name(name):
    raw = clean(name)
    key = normalize_text_key(raw)
    aliases = {
        "match_betting": "Match Betting",
        "match_odds": "Match Betting",
        "correct_score": "Correct Score",
        "total_goals": "Total Goals Over/Under",
        "over_under_goals": "Total Goals Over/Under",
        "over_under_goals_markets": "Total Goals Over/Under",
        "first_half_goals": "1st Half Goals",
        "1st_half_over_under_goals": "1st Half Goals",
        "btts": "Both Teams To Score",
        "both_teams_to_score": "Both Teams To Score",
        "both_teams_to_score_markets": "Both Teams To Score",
        "double_chance": "Double Chance",
        "handicap": "Handicap",
        "handicaps": "Handicap",
        "half_time_result": "Half Time Result",
        "half_time_full_time": "Half Time / Full Time",
        "ht_ft": "Half Time / Full Time",
        "result_both_to_score": "Result & Both Teams To Score",
        "result_btts": "Result & Both Teams To Score",
        "btts_result": "Result & Both Teams To Score",
        "both_teams_to_score_and_match_result": "Result & Both Teams To Score",
        "result_total_goals": "Result & Total Goals",
        "match_result_and_total_goals": "Result & Total Goals",
        "player_to_score": "Player To Score",
        "anytime_scorer": "Player To Score",
        "anytime_goalscorer": "Player To Score",
        "main_goalscorer_markets": "Player To Score",
        "first_scorer": "First Goalscorer",
        "first_goalscorer": "First Goalscorer",
        "scorer_2_plus": "To Score 2 Or More",
        "one_goal_ahead": "1 Goal Ahead",
    }
    return aliases.get(key, raw.replace("_", " ").title())


def normalize_text_key(value):
    value = clean(value).lower()
    value = value.replace("&", "and")
    value = value.replace("/", " ")
    value = value.replace("?", "")
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def normalize_prop_market_key(market_name):
    key = normalize_text_key(market_name)

    if key.startswith("total_goals_by_"):
        return key
    if key.startswith("team_total_goals"):
        return key

    aliases = {
        "match_odds": "match_betting",
        "match_betting": "match_betting",
        "over_under_goals_markets": "total_goals",
        "over_under_goals": "total_goals",
        "total_goals_over_under": "total_goals",
        "total_goals_over_under_markets": "total_goals",
        "total_goals": "total_goals",
        "1st_half_over_under_goals": "first_half_goals",
        "1st_half_goals_over_under": "first_half_goals",
        "first_half_goals": "first_half_goals",
        "both_teams_to_score_markets": "btts",
        "both_teams_to_score": "btts",
        "btts": "btts",
        "result_both_to_score": "btts_result",
        "result_btts": "btts_result",
        "both_teams_to_score_and_match_result": "btts_result",
        "result_and_both_teams_to_score": "btts_result",
        "correct_score": "correct_score",
        "double_chance": "double_chance",
        "half_time_result": "half_time_result",
        "half_time_full_time": "ht_ft",
        "ht_ft": "ht_ft",
        # BoyleSports-specific keys
        "handicaps": "handicap",
        "handicap": "handicap",
        "match_result_and_total_goals": "result_total_goals",
        "result_total_goals": "result_total_goals",
        "1_goal_ahead": "one_goal_ahead",
        "one_goal_ahead": "one_goal_ahead",
        "main_goalscorer_markets": "anytime_scorer",
        "player_to_score": "anytime_scorer",
        "anytime_goalscorer": "anytime_scorer",
        "anytime_scorer": "anytime_scorer",
        "first_goalscorer": "first_goalscorer",
        "first_scorer": "first_goalscorer",
        "scorer_2_plus": "scorer_2_plus",
    }

    return aliases.get(key, key)


def normalize_prop_selection_key(market_name, selection_name):
    market_key = normalize_prop_market_key(market_name)
    selection = clean(selection_name)
    selection_lower = selection.lower().replace("&", "and")
    selection_lower = re.sub(r"\s+", " ", selection_lower).strip()

    score_match = re.search(r"(\d+)\s*-\s*(\d+)", selection_lower)
    if score_match and market_key == "correct_score":
        return f"score_{score_match.group(1)}_{score_match.group(2)}"

    ou_match = re.search(r"\b(over|under)\b\s*(\d+(?:\.\d+)?)", selection_lower)
    if ou_match:
        return f"{ou_match.group(1)}_{ou_match.group(2)}"

    # Goalscorer: "Raul Jimenez Anytime Goalscorer" → "anytime__raul_jimenez"
    # "Raul Jimenez First Goalscorer" → "first__raul_jimenez"
    # This lets PaddyPower and Unibet compare even when stored under different market keys
    if market_key in {"anytime_scorer", "first_goalscorer", "scorer_2_plus", "player_to_score"}:
        if re.search(r"\banytime\b", selection_lower):
            player = re.sub(r"\banytime\s*goalscorer\b", "", selection_lower).strip()
            return "anytime__" + re.sub(r"[^a-z0-9]+", "_", player).strip("_")
        if re.search(r"\bfirst\s+goalscorer\b", selection_lower):
            player = re.sub(r"\bfirst\s+goalscorer\b", "", selection_lower).strip()
            return "first__" + re.sub(r"[^a-z0-9]+", "_", player).strip("_")
        if re.search(r"\bto score 2\b|\b2 or more\b", selection_lower):
            player = re.sub(r"\bto score 2.*$|\b2 or more.*$", "", selection_lower).strip()
            return "score2__" + re.sub(r"[^a-z0-9]+", "_", player).strip("_")
        return normalize_text_key(selection_lower)

    if market_key == "btts":
        side = None
        if re.search(r"(?:^|\b|[- ])yes(?:$|\b)", selection_lower):
            side = "yes"
        elif re.search(r"(?:^|\b|[- ])no(?:$|\b)", selection_lower):
            side = "no"
        if side:
            if "first half" in selection_lower:
                return f"both_teams_to_score_first_half_{side}"
            if "both halves" in selection_lower:
                return f"both_teams_to_score_both_halves_{side}"
            if "no draw" in selection_lower:
                return f"both_teams_score_no_draw_{side}"
            if "two or more" in selection_lower:
                return f"both_teams_to_score_two_or_more_goals_{side}"
            if selection_lower in {"yes", "no"} or "both teams to score" in selection_lower or "btts" in selection_lower:
                return f"both_teams_to_score_{side}"
        return normalize_text_key(selection_lower)

    if market_key == "half_time_result":
        if "draw" in selection_lower:
            return "draw"
        return normalize_text_key(selection_lower.replace("half time result", ""))

    return normalize_text_key(selection_lower)


def pretty_prop_selection_label(market_name, selection_name):
    market_key = normalize_prop_market_key(market_name)
    selection = clean(selection_name)
    lower = selection.lower().replace("&", "and")

    if market_key == "btts":
        if re.search(r"(?:^|\b|[- ])yes(?:$|\b)", lower):
            if "first half" in lower:
                return "Yes - 1st Half"
            if "both halves" in lower:
                return "Yes - Both Halves"
            if "no draw" in lower:
                return "Yes - No Draw"
            if "two or more" in lower:
                return "Yes - 2+ Goals"
            return "Yes"
        if re.search(r"(?:^|\b|[- ])no(?:$|\b)", lower):
            if "first half" in lower:
                return "No - 1st Half"
            if "both halves" in lower:
                return "No - Both Halves"
            if "no draw" in lower:
                return "No - No Draw"
            if "two or more" in lower:
                return "No - 2+ Goals"
            return "No"

    return selection


def convert_market(raw_market):
    if not isinstance(raw_market, dict):
        return None

    market_name = (
        raw_market.get("market")
        or raw_market.get("label")
        or raw_market.get("name")
        or raw_market.get("market_name")
        or ""
    )
    market_name = pretty_market_name(market_name)

    selections = []
    for raw_selection in raw_market.get("selections") or []:
        if not isinstance(raw_selection, dict):
            continue
        selection = (
            raw_selection.get("selection")
            or raw_selection.get("name")
            or raw_selection.get("label")
            or raw_selection.get("selection_name")
            or ""
        )
        odds = (
            raw_selection.get("odds")
            or raw_selection.get("price")
            or raw_selection.get("fractional")
            or ""
        )
        selection = clean(selection)
        odds = clean(odds).upper()
        if not selection or not odds:
            continue
        selections.append({
            "selection": selection,
            "normalized_selection": normalize_text_key(selection),
            "odds": odds,
        })

    if not market_name or not selections:
        return None

    return {
        "market": market_name,
        "normalized_market": normalize_prop_market_key(market_name),
        "selection_count": len(selections),
        "selections": selections,
    }


def convert_markets(raw_markets):
    markets = []

    if isinstance(raw_markets, list):
        for raw_market in raw_markets:
            market = convert_market(raw_market)
            if market:
                markets.append(market)

    elif isinstance(raw_markets, dict):
        for internal_name, raw_market in raw_markets.items():
            if not isinstance(raw_market, dict):
                continue
            raw_market = dict(raw_market)
            raw_market.setdefault("market", raw_market.get("label") or pretty_market_name(internal_name))
            market = convert_market(raw_market)
            if market:
                markets.append(market)

    seen = set()
    unique = []
    for market in markets:
        key = market.get("normalized_market")
        if key in seen:
            continue
        seen.add(key)
        unique.append(market)

    return unique


def make_market(name, selections):
    return {
        "market": name,
        "normalized_market": normalize_prop_market_key(name),
        "selection_count": len(selections),
        "selections": selections,
    }


def selection_line_key(selection_name):
    selection = clean(selection_name).lower()
    match = re.search(r"\b(over|under)\b\s*(\d+(?:\.\d+)?)", selection)
    if not match:
        return None
    return f"{match.group(1)}_{match.group(2)}"


def split_unibet_team_total_markets(bookmaker, markets, home, away):
    if bookmaker != "Unibet":
        return markets

    fixed = []
    for market in markets:
        market_key = market.get("normalized_market") or normalize_prop_market_key(market.get("market"))
        selections = market.get("selections") or []

        if market_key != "total_goals" or len(selections) <= 6:
            fixed.append(market)
            continue

        seen_lines = set()
        has_duplicate_lines = False
        for sel in selections:
            key = selection_line_key(sel.get("selection"))
            if not key:
                continue
            if key in seen_lines:
                has_duplicate_lines = True
                break
            seen_lines.add(key)

        if not has_duplicate_lines:
            fixed.append(market)
            continue

        match_selections = selections[:6]
        remaining = selections[6:]

        if match_selections:
            fixed.append(make_market("Total Goals", match_selections))

        team_names = [home, away]
        chunk_size = 6

        for idx, team in enumerate(team_names):
            start = idx * chunk_size
            chunk = remaining[start:start + chunk_size]
            if not chunk:
                continue
            fixed.append(make_market(f"Total Goals by {team}", chunk))

        extra = remaining[len(team_names) * chunk_size:]
        if extra:
            fixed.append(make_market("Other Team Goals", extra))

    return fixed


def postprocess_props_markets(bookmaker, markets, home, away):
    markets = split_unibet_team_total_markets(bookmaker, markets, home, away)
    markets = repair_prop_markets(bookmaker, markets)
    return markets


def repair_prop_markets(bookmaker, markets):
    fixed = []
    for market in markets or []:
        if not isinstance(market, dict):
            continue

        market_key = normalize_prop_market_key(market.get("market") or market.get("normalized_market") or "")
        selections = market.get("selections") or []

        if market_key == "btts" and len(selections) == 2:
            labels = [clean(s.get("selection") or "").lower() for s in selections]
            has_yes_no = any(
                re.search(r"(?:^|\b|[- ])yes(?:$|\b)", x) or
                re.search(r"(?:^|\b|[- ])no(?:$|\b)", x)
                for x in labels
            )

            if not has_yes_no:
                repaired = []
                for idx, sel in enumerate(selections):
                    side = "Yes" if idx == 0 else "No"
                    repaired.append({
                        **sel,
                        "selection": f"Both Teams To Score - {side}",
                        "normalized_selection": normalize_text_key(f"Both Teams To Score - {side}"),
                    })
                market = {
                    **market,
                    "market": "Both Teams To Score",
                    "normalized_market": "btts",
                    "selection_count": len(repaired),
                    "selections": repaired,
                }

        fixed.append(market)

    return fixed


def load_props_file(bookmaker, path):
    data = load_json(path)

    if isinstance(data, list):
        raw_matches = data
        generated_at = ""
        source_url = ""
    else:
        raw_matches = data.get("matches") or data.get("results") or []
        generated_at = data.get("generated_at") or ""
        source_url = data.get("source_url") or ""

    props_by_key = {}

    for m in raw_matches:
        if not isinstance(m, dict):
            continue

        home = display_team(m.get("home_team"))
        away = display_team(m.get("away_team"))

        if not home or not away:
            home, away = split_match_name(m.get("match") or m.get("name") or "")

        if not home or not away:
            continue

        markets = convert_markets(m.get("markets") or {})
        markets = postprocess_props_markets(bookmaker, markets, home, away)

        if not markets:
            continue

        props_by_key[fixture_key(home, away)] = {
            "bookmaker": bookmaker,
            "match": m.get("match") or m.get("name") or f"{home} v {away}",
            "home_team": home,
            "away_team": away,
            "source_url": m.get("source_url") or m.get("url") or source_url,
            "market_count": len(markets),
            "markets": markets,
        }

    return props_by_key, generated_at


def load_paddypower_props():
    return load_props_file("PaddyPower", PADDY_PROPS_PATH)


def load_boylesports_props():
    return load_props_file("BoyleSports", BOYLE_PROPS_PATH)


def load_unibet_props():
    return load_props_file("Unibet", UNIBET_PROPS_PATH)


def add_book_rows(fixtures, strict_index, loose_index, rows, bookmaker):
    for row in rows:
        target_key = None

        if row["strict_key"] in strict_index:
            target_key = strict_index[row["strict_key"]]
        elif row["loose_key"] in loose_index:
            target_key = loose_index[row["loose_key"]]

        if target_key:
            fixtures[target_key]["bookmakers"][bookmaker] = {
                "bookmaker": bookmaker,
                "odds": row["odds"],
                "source_url": row["source_url"],
            }
        else:
            key = row["strict_key"]
            fixtures[key] = {
                "key": key,
                "loose_key": row["loose_key"],
                "slug": slugify(f"{row['home_team']}-v-{row['away_team']}"),
                "date_label": row["date_label"],
                "time": row["time"],
                "match": row["match"],
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "bookmakers": {
                    bookmaker: {
                        "bookmaker": bookmaker,
                        "odds": row["odds"],
                        "source_url": row["source_url"],
                    }
                },
                "props": {},
            }
            strict_index[key] = key
            loose_index[row["loose_key"]] = key


def load_all_matches():
    paddy_rows, paddy_generated = load_book("PaddyPower", PADDY_PATH)
    boyle_rows, boyle_generated = load_book("BoyleSports", BOYLE_PATH)
    betvictor_rows, betvictor_generated = load_book("BetVictor", BETVICTOR_PATH)
    unibet_rows, unibet_generated = load_book("Unibet", UNIBET_PATH)
    livescore_rows, livescore_generated = load_book("LiveScoreBet", LIVESCOREBET_PATH)
    williamhill_rows, williamhill_generated = load_book("WilliamHill", WILLIAMHILL_PATH)
    eighteight_rows, eighteight_generated = load_book("888Sport", EIGHTEIGHTEIGHT_PATH)

    paddy_props, paddy_props_generated = load_paddypower_props()
    boyle_props, boyle_props_generated = load_boylesports_props()
    unibet_props, unibet_props_generated = load_unibet_props()

    fixtures = {}

    for row in paddy_rows:
        key = row["strict_key"]
        fixtures[key] = {
            "key": key,
            "loose_key": row["loose_key"],
            "slug": slugify(f"{row['home_team']}-v-{row['away_team']}"),
            "date_label": row["date_label"],
            "time": row["time"],
            "match": row["match"],
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "bookmakers": {
                "PaddyPower": {
                    "bookmaker": "PaddyPower",
                    "odds": row["odds"],
                    "source_url": row["source_url"],
                }
            },
            "props": {},
        }

    strict_index = {f["key"]: key for key, f in fixtures.items()}
    loose_index = {f["loose_key"]: key for key, f in fixtures.items()}

    add_book_rows(fixtures, strict_index, loose_index, boyle_rows, "BoyleSports")
    add_book_rows(fixtures, strict_index, loose_index, betvictor_rows, "BetVictor")
    add_book_rows(fixtures, strict_index, loose_index, unibet_rows, "Unibet")
    add_book_rows(fixtures, strict_index, loose_index, livescore_rows, "LiveScoreBet")
    add_book_rows(fixtures, strict_index, loose_index, williamhill_rows, "WilliamHill")
    add_book_rows(fixtures, strict_index, loose_index, eighteight_rows, "888Sport")

    for bookmaker, book_props in [
        ("PaddyPower", paddy_props),
        ("BoyleSports", boyle_props),
        ("Unibet", unibet_props),
    ]:
        for props_key, props_data in book_props.items():
            target_key = None
            loose_key = loose_fixture_key(props_data.get("home_team"), props_data.get("away_team"))

            if props_key in strict_index:
                target_key = strict_index[props_key]
            elif loose_key in loose_index:
                target_key = loose_index[loose_key]

            if target_key and target_key in fixtures:
                fixtures[target_key].setdefault("props", {})
                fixtures[target_key]["props"][bookmaker] = props_data

    fixtures_list = list(fixtures.values())
    fixtures_list.sort(
        key=lambda x: (
            date_sort_key(x.get("date_label")),
            x.get("time", ""),
            x.get("match", ""),
        )
    )

    generated = (
        unibet_props_generated
        or boyle_props_generated
        or paddy_props_generated
        or eighteight_generated
        or williamhill_generated
        or livescore_generated
        or unibet_generated
        or betvictor_generated
        or boyle_generated
        or paddy_generated
    )

    bookmaker_names = set()
    for f in fixtures_list:
        for b in f.get("bookmakers", {}):
            bookmaker_names.add(b)

    return fixtures_list, len(bookmaker_names), generated


def date_sort_key(date_label):
    label = str(date_label or "")
    day_order = {
        "Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4,
        "Friday": 5, "Saturday": 6, "Sunday": 7,
        "Mon": 1, "Tue": 2, "Wed": 3, "Thu": 4, "Fri": 5, "Sat": 6, "Sun": 7,
    }
    parts = label.split()
    number = 999
    day = 999
    if parts:
        day = day_order.get(parts[0], 999)
    for p in parts:
        if p.isdigit():
            number = int(p)
            break
    return (number, day, label)


def best_price(fixture, side):
    offers = []
    for bookmaker, info in fixture.get("bookmakers", {}).items():
        raw = (info.get("odds") or {}).get(side)
        dec = fractional_to_decimal(raw)
        if raw and dec > 1:
            offers.append({"bookmaker": bookmaker, "odds": raw, "decimal": dec})
    if not offers:
        return None
    return sorted(offers, key=lambda x: x["decimal"], reverse=True)[0]


def all_prices_for_side(fixture, side):
    rows = []
    for bookmaker, info in sorted(fixture.get("bookmakers", {}).items()):
        raw = (info.get("odds") or {}).get(side)
        dec = fractional_to_decimal(raw)
        if raw and dec > 1:
            rows.append({"bookmaker": bookmaker, "odds": raw, "decimal": dec})
    best = best_price(fixture, side)
    best_key = (best["bookmaker"], best["odds"]) if best else None
    for row in rows:
        row["is_best"] = best_key == (row["bookmaker"], row["odds"])
    return rows


def render_best_box(label, best):
    if not best:
        return f"""
        <div class="odd-box">
          <span>{esc(label)}</span>
          <strong>—</strong>
          <em>No price</em>
        </div>
        """
    return f"""
    <div class="odd-box">
      <span>{esc(label)}</span>
      <strong>{esc(best["odds"])}</strong>
      <em>{esc(best["bookmaker"])}</em>
    </div>
    """


def render_worldcup_page(fixtures, bookmaker_count, generated_at):
    grouped = {}
    for fixture in fixtures:
        grouped.setdefault(fixture.get("date_label") or "Upcoming", []).append(fixture)

    groups_html = ""
    for date_label, items in grouped.items():
        cards = ""
        for fixture in items:
            home = fixture["home_team"]
            away = fixture["away_team"]
            slug = fixture["slug"]

            best_home = best_price(fixture, "home")
            best_draw = best_price(fixture, "draw")
            best_away = best_price(fixture, "away")

            books_count = len(fixture.get("bookmakers", {}))
            props_count = sum(len((p.get("markets") or [])) for p in (fixture.get("props") or {}).values())

            props_badge = ""
            if props_count:
                props_badge = f'<span class="props-pill">{props_count} prop markets</span>'

            cards += f"""
            <article class="match-card">
              <div class="match-top">
                <div>
                  <h3>{esc(home)} <span>v</span> {esc(away)}</h3>
                  <p>{esc(fixture.get("time"))} · {books_count} bookmaker{"s" if books_count != 1 else ""} {props_badge}</p>
                </div>
                <a class="market-badge" href="{BASE}/football/world-cup/{slug}/">View books →</a>
              </div>
              <div class="odds-grid">
                {render_best_box(home, best_home)}
                {render_best_box("Draw", best_draw)}
                {render_best_box(away, best_away)}
              </div>
            </article>
            """

        groups_html += f"""
        <section class="date-section">
          <div class="date-header">
            <h2>{esc(date_label)}</h2>
            <span>{len(items)} match{"es" if len(items) != 1 else ""}</span>
          </div>
          <div class="matches-grid">
            {cards}
          </div>
        </section>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>FIFA World Cup Odds — BeatTheBooks</title>
  <style>
    :root {{
      --bg: #0f1621; --panel: #111827; --border: #223047;
      --text: #ffffff; --muted: #91a0b5; --green: #22c55e;
      --blue: #60a5fa; --gold: #facc15;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background:
        radial-gradient(circle at top left, rgba(34,197,94,0.16), transparent 32%),
        radial-gradient(circle at top right, rgba(96,165,250,0.13), transparent 30%),
        var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      min-height: 100vh;
    }}
    a {{ color: inherit; text-decoration: none; }}
    .page {{ max-width: 1500px; margin: 0 auto; padding: 34px 28px 70px; }}
    .top-nav {{ display: flex; gap: 12px; color: var(--muted); font-size: 14px; margin-bottom: 28px; flex-wrap: wrap; }}
    .top-nav a {{ color: var(--blue); }}
    .hero {{ border: 1px solid var(--border); border-radius: 28px; padding: 34px; background: rgba(17,24,39,0.82); box-shadow: 0 20px 80px rgba(0,0,0,0.28); margin-bottom: 28px; }}
    .eyebrow {{ display: inline-flex; border: 1px solid rgba(34,197,94,0.45); background: rgba(34,197,94,0.1); color: #86efac; border-radius: 999px; padding: 7px 12px; font-size: 12px; font-weight: 900; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 16px; }}
    h1 {{ font-size: clamp(42px, 6vw, 82px); line-height: 0.95; letter-spacing: -0.055em; margin-bottom: 14px; }}
    .subtitle {{ color: var(--muted); font-size: 17px; max-width: 760px; line-height: 1.6; margin-bottom: 18px; }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-top: 22px; }}
    .stat {{ border: 1px solid var(--border); border-radius: 16px; padding: 16px; background: rgba(255,255,255,0.03); }}
    .stat strong {{ display: block; font-size: 30px; color: var(--green); margin-bottom: 4px; }}
    .stat span {{ color: var(--muted); font-size: 13px; }}
    .date-section {{ margin-top: 34px; }}
    .date-header {{ display: flex; justify-content: space-between; align-items: center; gap: 16px; border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 14px; }}
    .date-header h2 {{ font-size: 24px; letter-spacing: -0.02em; }}
    .date-header span {{ border: 1px solid rgba(96,165,250,0.35); color: #bfdbfe; background: rgba(96,165,250,0.08); border-radius: 999px; padding: 5px 10px; font-size: 12px; font-weight: 800; }}
    .matches-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 14px; }}
    .match-card {{ border: 1px solid var(--border); border-radius: 20px; padding: 18px; background: rgba(17,24,39,0.72); }}
    .match-top {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 16px; }}
    .match-top h3 {{ font-size: 18px; letter-spacing: -0.02em; margin-bottom: 5px; }}
    .match-top h3 span {{ color: var(--muted); font-weight: 500; }}
    .match-top p {{ color: var(--muted); font-size: 13px; }}
    .props-pill {{ display: inline-flex; margin-left: 8px; color: #86efac; font-weight: 900; }}
    .market-badge {{ white-space: nowrap; border: 1px solid rgba(250,204,21,0.4); color: #fde68a; background: rgba(250,204,21,0.08); border-radius: 999px; padding: 6px 10px; font-size: 11px; font-weight: 900; text-transform: uppercase; }}
    .odds-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }}
    .odd-box {{ border: 1px solid var(--border); border-radius: 14px; padding: 12px 10px; background: rgba(15,22,33,0.82); text-align: center; }}
    .odd-box span {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 8px; min-height: 30px; }}
    .odd-box strong {{ display: block; color: var(--green); font-size: 22px; font-weight: 950; }}
    .odd-box em {{ display: block; color: var(--muted); font-size: 11px; font-style: normal; margin-top: 5px; }}
    .footer-note {{ margin-top: 34px; color: var(--muted); font-size: 13px; line-height: 1.6; }}
    @media (max-width: 700px) {{
      .page {{ padding: 20px 14px 50px; }}
      .hero {{ padding: 24px; border-radius: 22px; }}
      .matches-grid {{ grid-template-columns: 1fr; }}
      .odds-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <nav class="top-nav">
      <a href="{BASE}/football/">Football</a>
      <span>›</span>
      <span>FIFA World Cup</span>
    </nav>
    <section class="hero">
      <div class="eyebrow">⚽ Football Odds</div>
      <h1>FIFA World Cup Odds</h1>
      <p class="subtitle">Best available match odds across tracked bookmakers. Click any fixture to compare prices and view props.</p>
      <div class="stats">
        <div class="stat"><strong>{len(fixtures)}</strong><span>Fixtures tracked</span></div>
        <div class="stat"><strong>{bookmaker_count}</strong><span>Bookmakers</span></div>
        <div class="stat"><strong>Props</strong><span>Props from tracked bookmakers</span></div>
      </div>
      <p class="footer-note">Updated: {esc(generated_at)}</p>
    </section>
    {groups_html}
    <p class="footer-note">Odds are scraped from tracked bookmakers and may change. Always check the bookmaker before placing any bet.</p>
  </main>
</body>
</html>
"""


def render_props_section(fixture):
    props = fixture.get("props") or {}
    home = fixture.get("home_team") or ""
    away = fixture.get("away_team") or ""

    if not props:
        return """
        <section class="props-wrap" id="props">
          <div class="section-title"><h2>Props</h2><p>No props available for this match yet.</p></div>
        </section>
        """

    PLAYER_MARKET_KEYS = {"anytime_scorer", "first_goalscorer", "scorer_2_plus"}
    GROUPED_OVER_UNDER_KEYS = {"total_goals", "first_half_goals"}

    def is_player_market(market_name):
        market_key = normalize_prop_market_key(market_name)
        name = str(market_name or "").lower()
        if market_key in PLAYER_MARKET_KEYS:
            return True
        player_keywords = ["player to score", "goalscorer", "goal scorer", "first scorer", "anytime scorer", "to score 2 or more"]
        return any(word in name for word in player_keywords)

    def is_team_market(market_name):
        market_key = normalize_prop_market_key(market_name)
        name = str(market_name or "").lower()
        home_l = str(home or "").lower()
        away_l = str(away or "").lower()
        if market_key.startswith("total_goals_by_"):
            return True
        if market_key.startswith("team_total_goals"):
            return True
        if "team total" in name or "total goals by" in name:
            return True
        if home_l and f"by {home_l}" in name:
            return True
        if away_l and f"by {away_l}" in name:
            return True
        return False

    def best_offer(offers):
        offers = [o for o in offers if o.get("decimal", 0) > 1]
        if not offers:
            return None
        return sorted(offers, key=lambda x: x["decimal"], reverse=True)[0]

    def offer_label(offer):
        if not offer:
            return "—"
        return f"{esc(offer['bookmaker'])} <strong>{esc(offer['odds'])}</strong>"

    def render_market_card(market):
        selections = market.get("selections") or []
        rows = ""
        for sel in selections:
            rows += f"""
            <tr>
              <td>{esc(sel.get("selection"))}</td>
              <td><strong>{esc(sel.get("odds"))}</strong></td>
            </tr>
            """
        if not rows:
            rows = '<tr><td colspan="2">No selections available</td></tr>'
        return f"""
        <section class="prop-market">
          <h3>{esc(market.get("market"))}</h3>
          <table>
            <thead><tr><th>Selection</th><th>Odds</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </section>
        """

    def build_comparison_data():
        comparison = {}
        for bookmaker, prop_data in sorted(props.items()):
            for market in prop_data.get("markets") or []:
                market_name = market.get("market") or ""
                if is_team_market(market_name):
                    continue
                market_key = normalize_prop_market_key(market_name)
                for sel in market.get("selections") or []:
                    selection_name = sel.get("selection") or ""
                    odds = sel.get("odds") or ""
                    decimal = fractional_to_decimal(odds)
                    if not selection_name or not odds or decimal <= 1:
                        continue
                    selection_key = normalize_prop_selection_key(market_name, selection_name)
                    key = (market_key, selection_key)
                    if key not in comparison:
                        comparison[key] = {
                            "market": pretty_market_name(market_name),
                            "market_key": market_key,
                            "selection": pretty_prop_selection_label(market_name, selection_name),
                            "selection_key": selection_key,
                            "offers": [],
                        }
                    comparison[key]["offers"].append({"bookmaker": bookmaker, "odds": odds, "decimal": decimal})
        return comparison

    def build_over_under_cards(comparison):
        grouped = {}
        for item in comparison.values():
            market_key = item.get("market_key")
            selection_key = item.get("selection_key") or ""
            if market_key not in GROUPED_OVER_UNDER_KEYS:
                continue
            match = re.match(r"^(over|under)_(\d+(?:\.\d+)?)$", selection_key)
            if not match:
                continue
            side = match.group(1)
            line = match.group(2)
            grouped.setdefault(market_key, {"market": item.get("market") or pretty_market_name(market_key), "lines": {}})
            grouped[market_key]["lines"].setdefault(line, {})[side] = item

        cards = ""
        for market_key in ["total_goals", "first_half_goals"]:
            group = grouped.get(market_key)
            if not group:
                continue
            rows = ""
            for line in sorted(group["lines"].keys(), key=lambda x: float(x)):
                sides = group["lines"].get(line) or {}
                over_item = sides.get("over")
                under_item = sides.get("under")
                over_offers = over_item.get("offers") if over_item else []
                under_offers = under_item.get("offers") if under_item else []
                if len({o["bookmaker"] for o in over_offers}) < 2 and len({o["bookmaker"] for o in under_offers}) < 2:
                    continue
                over_best = best_offer(over_offers)
                under_best = best_offer(under_offers)
                rows += f"""
                <tr>
                  <td><strong>{esc(line)}</strong></td>
                  <td>{offer_label(over_best)}</td>
                  <td>{offer_label(under_best)}</td>
                </tr>
                """
            if not rows:
                continue
            cards += f"""
            <section class="prop-market prop-market-wide">
              <h3>{esc(group["market"])} — Over / Under</h3>
              <table>
                <thead><tr><th>Line</th><th>Best Over</th><th>Best Under</th></tr></thead>
                <tbody>{rows}</tbody>
              </table>
            </section>
            """
        return cards

    def build_goalscorer_comparison_cards(comparison):
        """Build per-player comparison tables for Anytime and First Goalscorer."""
        # Group by scorer type (anytime / first / score2) then by player
        grouped = {}  # {scorer_type: {player_key: {market_label, player_name, offers}}}

        SCORER_MARKET_KEYS = {"anytime_scorer", "first_goalscorer", "scorer_2_plus", "player_to_score"}

        for item in comparison.values():
            market_key = item.get("market_key")
            if market_key not in SCORER_MARKET_KEYS:
                continue

            selection_key = item.get("selection_key") or ""
            offers = item.get("offers") or []

            # Only show where 2+ bookmakers have a price
            bookmakers_seen = {o["bookmaker"] for o in offers}
            if len(bookmakers_seen) < 2:
                continue

            # Parse the normalised key: "anytime__raul_jimenez" → type=anytime, player=raul_jimenez
            match = re.match(r"^(anytime|first|score2)__(.+)$", selection_key)
            if not match:
                continue

            scorer_type = match.group(1)
            player_key = match.group(2)
            player_name = player_key.replace("_", " ").title()

            type_label = {
                "anytime": "Anytime Goalscorer",
                "first":   "First Goalscorer",
                "score2":  "To Score 2+",
            }.get(scorer_type, scorer_type.title())

            grouped.setdefault(scorer_type, {"label": type_label, "players": {}})
            grouped[scorer_type]["players"].setdefault(player_key, {
                "player_name": player_name,
                "offers": [],
            })
            # Merge offers (dedupe by bookmaker keeping best decimal)
            existing = {o["bookmaker"]: o for o in grouped[scorer_type]["players"][player_key]["offers"]}
            for offer in offers:
                bk = offer["bookmaker"]
                if bk not in existing or offer["decimal"] > existing[bk]["decimal"]:
                    existing[bk] = offer
            grouped[scorer_type]["players"][player_key]["offers"] = list(existing.values())

        cards = ""
        for scorer_type in ["anytime", "first", "score2"]:
            group = grouped.get(scorer_type)
            if not group:
                continue

            # Sort players by best available decimal desc
            players = sorted(
                group["players"].values(),
                key=lambda p: max((o["decimal"] for o in p["offers"]), default=0),
                reverse=True,
            )

            # Get all bookmakers that appear
            all_books = sorted({o["bookmaker"] for p in players for o in p["offers"]})
            if len(all_books) < 2:
                continue

            header_cells = "".join(f"<th>{esc(b)}</th>" for b in all_books)
            rows = ""
            for player in players:
                by_book = {o["bookmaker"]: o for o in player["offers"]}
                best_dec = max((o["decimal"] for o in player["offers"]), default=0)
                cells = ""
                for bk in all_books:
                    offer = by_book.get(bk)
                    if offer:
                        is_best = offer["decimal"] == best_dec
                        cls = ' class="best-cell"' if is_best else ""
                        cells += f'<td{cls}><strong>{esc(offer["odds"])}</strong></td>'
                    else:
                        cells += "<td>—</td>"
                rows += f"<tr><td>{esc(player['player_name'])}</td>{cells}</tr>"

            cards += f"""
            <section class="prop-market prop-market-wide goalscorer-comparison">
              <h3>{esc(group["label"])}</h3>
              <table>
                <thead><tr><th>Player</th>{header_cells}</tr></thead>
                <tbody>{rows}</tbody>
              </table>
            </section>
            """

        return cards

    def build_standard_comparison_cards(comparison):
        cards = ""
        SAFE_STANDARD_MARKETS = {"btts", "double_chance"}
        for item in sorted(comparison.values(), key=lambda x: (x["market"], x["selection"])):
            market_key = item.get("market_key")
            if market_key in GROUPED_OVER_UNDER_KEYS:
                continue
            if market_key not in SAFE_STANDARD_MARKETS:
                continue
            offers = item.get("offers") or []
            best_by_bookmaker = {}
            for offer in offers:
                bookmaker = offer.get("bookmaker")
                if not bookmaker:
                    continue
                current = best_by_bookmaker.get(bookmaker)
                if current is None or offer.get("decimal", 0) > current.get("decimal", 0):
                    best_by_bookmaker[bookmaker] = offer
            offers = list(best_by_bookmaker.values())
            bookmakers_seen = {offer["bookmaker"] for offer in offers}
            if len(bookmakers_seen) < 2:
                continue
            offers = sorted(offers, key=lambda x: x["decimal"], reverse=True)
            best_decimal = offers[0]["decimal"] if offers else 0
            rows = ""
            for offer in offers:
                is_best = offer["decimal"] == best_decimal
                cls = "best-row" if is_best else ""
                tag = "BEST" if is_best else ""
                rows += f"""
                <tr class="{cls}">
                  <td>{esc(offer["bookmaker"])}</td>
                  <td><strong>{esc(offer["odds"])}</strong></td>
                  <td>{tag}</td>
                </tr>
                """
            cards += f"""
            <section class="prop-market">
              <h3>{esc(item["market"])} — {esc(item["selection"])}</h3>
              <table>
                <thead><tr><th>Bookmaker</th><th>Odds</th><th></th></tr></thead>
                <tbody>{rows}</tbody>
              </table>
            </section>
            """
        return cards

    def build_best_prop_comparisons():
        comparison = build_comparison_data()
        grouped_ou_cards = build_over_under_cards(comparison)
        standard_cards = build_standard_comparison_cards(comparison)
        goalscorer_cards = build_goalscorer_comparison_cards(comparison)
        if not grouped_ou_cards and not standard_cards and not goalscorer_cards:
            return ""
        return f"""
        <section class="book-props" id="best-prop-prices">
          <div class="book-props-head">
            <h2>Best Prop Prices</h2>
            <span class="compare-note">Compared across tracked bookmakers</span>
          </div>
          <div class="props-grid props-grid-wide">{grouped_ou_cards}</div>
          <div class="props-grid">{standard_cards}</div>
          <div class="props-grid props-grid-wide">{goalscorer_cards}</div>
        </section>
        """

    best_comparison_html = build_best_prop_comparisons()
    match_book_html = ""
    team_book_html = ""
    player_book_html = ""

    for bookmaker, prop_data in sorted(props.items()):
        markets = prop_data.get("markets") or []
        if not markets:
            continue
        match_market_cards = ""
        team_market_cards = ""
        player_market_cards = ""
        for market in markets:
            market_name = market.get("market")
            if is_player_market(market_name):
                player_market_cards += render_market_card(market)
            elif is_team_market(market_name):
                team_market_cards += render_market_card(market)
            else:
                match_market_cards += render_market_card(market)

        bookmaker_link = f'<a href="{esc(prop_data.get("source_url"))}" target="_blank" rel="noopener">Open bookmaker →</a>'

        if match_market_cards:
            match_book_html += f"""
            <section class="book-props">
              <div class="book-props-head"><h2>{esc(bookmaker)} Match Props</h2>{bookmaker_link}</div>
              <div class="props-grid">{match_market_cards}</div>
            </section>
            """
        if team_market_cards:
            team_book_html += f"""
            <section class="book-props">
              <div class="book-props-head"><h2>{esc(bookmaker)} Team Props</h2>{bookmaker_link}</div>
              <div class="props-grid">{team_market_cards}</div>
            </section>
            """
        if player_market_cards:
            player_book_html += f"""
            <section class="book-props">
              <div class="book-props-head"><h2>{esc(bookmaker)} Player Props</h2>{bookmaker_link}</div>
              <div class="props-grid">{player_market_cards}</div>
            </section>
            """

    if not best_comparison_html and not match_book_html and not team_book_html and not player_book_html:
        return """
        <section class="props-wrap" id="props">
          <div class="section-title"><h2>Props</h2><p>No props available for this match yet.</p></div>
        </section>
        """

    match_section = ""
    if match_book_html:
        match_section = f"""
        <section id="match-props">
          <div class="section-title sub-section-title">
            <h2>Match Props</h2>
            <p>Match result, total goals, BTTS, score, handicap and double chance markets.</p>
          </div>
          {match_book_html}
        </section>
        """

    team_section = ""
    if team_book_html:
        team_section = f"""
        <section id="team-props">
          <div class="section-title sub-section-title">
            <h2>Team Props</h2>
            <p>Team-specific goal markets.</p>
          </div>
          {team_book_html}
        </section>
        """

    player_section = ""
    if player_book_html:
        player_section = f"""
        <section id="player-props">
          <div class="section-title sub-section-title">
            <h2>Player Props</h2>
            <p>Goalscorer markets.</p>
          </div>
          {player_book_html}
        </section>
        """

    team_link = '<a href="#team-props">Team Props</a>' if team_book_html else ""

    return f"""
    <section class="props-wrap" id="props">
      <div class="section-title"><h2>Props</h2><p>Best prices and prop markets from tracked bookmakers.</p></div>
      <nav class="props-jump-nav">
        <a href="#best-prop-prices">Best Prop Prices</a>
        <a href="#match-props">Match Props</a>
        {team_link}
        <a href="#player-props">Player Props</a>
      </nav>
      {best_comparison_html}
      {match_section}
      {team_section}
      {player_section}
    </section>
    """


def render_match_page(fixture):
    home = fixture["home_team"]
    away = fixture["away_team"]

    home_rows = all_prices_for_side(fixture, "home")
    draw_rows = all_prices_for_side(fixture, "draw")
    away_rows = all_prices_for_side(fixture, "away")

    def render_table(side_label, rows):
        body = ""
        for r in rows:
            cls = "best-row" if r["is_best"] else ""
            tag = "BEST" if r["is_best"] else ""
            body += f"""
            <tr class="{cls}">
              <td>{esc(r["bookmaker"])}</td>
              <td><strong>{esc(r["odds"])}</strong></td>
              <td>{tag}</td>
            </tr>
            """
        if not body:
            body = '<tr><td colspan="3">No prices available</td></tr>'
        return f"""
        <section class="price-panel">
          <h2>{esc(side_label)}</h2>
          <table>
            <thead><tr><th>Bookmaker</th><th>Odds</th><th></th></tr></thead>
            <tbody>{body}</tbody>
          </table>
        </section>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(home)} v {esc(away)} Odds — BeatTheBooks</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #0f1621; color: white; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; min-height: 100vh; }}
    a {{ color: #60a5fa; text-decoration: none; }}
    .page {{ max-width: 1300px; margin: 0 auto; padding: 34px 24px 70px; }}
    .nav {{ color: #91a0b5; margin-bottom: 28px; display: flex; gap: 12px; flex-wrap: wrap; }}
    .hero {{ border: 1px solid #223047; border-radius: 28px; padding: 32px; background: rgba(17,24,39,0.86); margin-bottom: 28px; }}
    .eyebrow {{ display: inline-flex; border: 1px solid rgba(34,197,94,0.45); background: rgba(34,197,94,0.1); color: #86efac; border-radius: 999px; padding: 7px 12px; font-size: 12px; font-weight: 900; text-transform: uppercase; margin-bottom: 14px; }}
    h1 {{ font-size: clamp(38px, 6vw, 72px); letter-spacing: -0.055em; line-height: .95; margin-bottom: 12px; }}
    .meta {{ color: #91a0b5; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 32px; }}
    .price-panel, .prop-market, .book-props {{ border: 1px solid #223047; border-radius: 20px; padding: 18px; background: rgba(17,24,39,0.72); }}
    .price-panel h2 {{ margin-bottom: 14px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 10px 8px; border-bottom: 1px solid #223047; color: #c7d2fe; font-size: 14px; vertical-align: top; }}
    th {{ color: #91a0b5; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
    td strong {{ color: #22c55e; font-size: 20px; }}
    .best-row {{ background: rgba(34,197,94,0.08); }}
    .best-row td:last-child {{ color: #86efac; font-weight: 900; font-size: 12px; }}
    .best-cell strong {{ color: #22c55e !important; }}
    .goalscorer-comparison td:first-child {{ font-weight: 600; color: #e2e8f0; min-width: 160px; }}
    .props-wrap {{ margin-top: 36px; }}
    .section-title {{ margin-bottom: 16px; }}
    .section-title h2 {{ font-size: 34px; letter-spacing: -0.035em; margin-bottom: 6px; }}
    .section-title p {{ color: #91a0b5; }}
    .book-props {{ margin-bottom: 18px; }}
    .book-props-head {{ display: flex; justify-content: space-between; align-items: center; gap: 14px; margin-bottom: 16px; flex-wrap: wrap; }}
    .book-props-head h2 {{ font-size: 24px; }}
    .book-props-head a {{ border: 1px solid rgba(96,165,250,0.45); background: rgba(96,165,250,0.08); color: #bfdbfe; border-radius: 999px; padding: 7px 11px; font-size: 12px; font-weight: 900; text-transform: uppercase; }}
    .props-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 14px; }}
    .prop-market h3 {{ font-size: 18px; margin-bottom: 12px; color: #facc15; }}
    .prop-market td strong {{ color: #86efac; font-size: 18px; }}
    .compare-note {{ color: #c7d2fe; font-size: 13px; font-weight: 800; }}
    .props-jump-nav {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 18px; }}
    .props-jump-nav a {{ border: 1px solid rgba(96,165,250,0.45); background: rgba(96,165,250,0.08); color: #bfdbfe; border-radius: 999px; padding: 8px 12px; font-size: 12px; font-weight: 900; text-transform: uppercase; }}
    .sub-section-title {{ margin-top: 34px; }}
    .props-grid-wide {{ grid-template-columns: repeat(auto-fit, minmax(520px, 1fr)); margin-bottom: 14px; }}
    .prop-market-wide td strong {{ font-size: 16px; }}
    @media (max-width: 700px) {{
      .page {{ padding: 22px 14px 50px; }}
      .hero {{ padding: 22px; border-radius: 22px; }}
      .props-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <nav class="nav">
      <a href="{BASE}/football/">Football</a>
      <span>›</span>
      <a href="{BASE}/football/world-cup/">FIFA World Cup</a>
      <span>›</span>
      <span>{esc(home)} v {esc(away)}</span>
    </nav>
    <section class="hero">
      <div class="eyebrow">⚽ Match Odds</div>
      <h1>{esc(home)} v {esc(away)}</h1>
      <p class="meta">{esc(fixture.get("date_label"))} · {esc(fixture.get("time"))} · {len(fixture.get("bookmakers", {}))} bookmaker{"s" if len(fixture.get("bookmakers", {})) != 1 else ""}</p>
    </section>
    <div class="grid">
      {render_table(home, home_rows)}
      {render_table("Draw", draw_rows)}
      {render_table(away, away_rows)}
    </div>
    {render_props_section(fixture)}
  </main>
</body>
</html>
"""


def render_football_hub(fixtures, bookmaker_count, generated_at):
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Football — BeatTheBooks</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #0f1621; color: white; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; min-height: 100vh; }}
    a {{ color: inherit; text-decoration: none; }}
    .page {{ max-width: 1200px; margin: 0 auto; padding: 42px 24px; }}
    .hero {{ border: 1px solid #223047; border-radius: 28px; padding: 34px; background: rgba(17,24,39,0.85); margin-bottom: 24px; }}
    .eyebrow {{ display: inline-block; color: #86efac; border: 1px solid rgba(34,197,94,0.45); background: rgba(34,197,94,0.1); padding: 7px 12px; border-radius: 999px; font-size: 12px; font-weight: 900; text-transform: uppercase; margin-bottom: 16px; }}
    h1 {{ font-size: clamp(42px, 6vw, 78px); letter-spacing: -0.055em; margin-bottom: 12px; }}
    p {{ color: #91a0b5; line-height: 1.6; }}
    .card {{ display: block; border: 1px solid #223047; border-radius: 22px; padding: 24px; background: rgba(255,255,255,0.035); transition: transform .15s ease, border-color .15s ease; }}
    .card:hover {{ transform: translateY(-2px); border-color: rgba(96,165,250,0.55); }}
    .card h2 {{ font-size: 28px; margin-bottom: 8px; }}
    .meta {{ margin-top: 18px; display: flex; gap: 10px; flex-wrap: wrap; }}
    .pill {{ border: 1px solid #223047; border-radius: 999px; padding: 7px 10px; color: #bfdbfe; font-size: 13px; font-weight: 800; }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div class="eyebrow">⚽ Football</div>
      <h1>Football Hub</h1>
      <p>Football odds, fixtures and betting tools. Starting with FIFA World Cup moneylines and selected props.</p>
    </section>
    <a class="card" href="{BASE}/football/world-cup/">
      <h2>FIFA World Cup</h2>
      <p>Best available match odds across tracked bookmakers, with props on selected matches.</p>
      <div class="meta">
        <span class="pill">{len(fixtures)} fixtures</span>
        <span class="pill">{bookmaker_count} bookmakers</span>
        <span class="pill">Best H/D/A odds</span>
        <span class="pill">Props</span>
        <span class="pill">Updated {esc(generated_at)}</span>
      </div>
    </a>
  </main>
</body>
</html>
"""


def main():
    fixtures, bookmaker_count, generated_at = load_all_matches()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    HUB_PATH.parent.mkdir(parents=True, exist_ok=True)

    OUT_PATH.write_text(render_worldcup_page(fixtures, bookmaker_count, generated_at), encoding="utf-8")
    HUB_PATH.write_text(render_football_hub(fixtures, bookmaker_count, generated_at), encoding="utf-8")

    for fixture in fixtures:
        match_dir = OUT_DIR / fixture["slug"]
        match_dir.mkdir(parents=True, exist_ok=True)
        (match_dir / "index.html").write_text(render_match_page(fixture), encoding="utf-8")

    props_matches = sum(1 for f in fixtures if f.get("props"))

    print(f"Wrote World Cup page: {OUT_PATH}")
    print(f"Wrote Football hub:   {HUB_PATH}")
    print(f"Wrote match pages:    {len(fixtures)}")
    print(f"Fixtures:             {len(fixtures)}")
    print(f"Bookmakers:           {bookmaker_count}")
    print(f"Matches with props:   {props_matches}")


if __name__ == "__main__":
    main()