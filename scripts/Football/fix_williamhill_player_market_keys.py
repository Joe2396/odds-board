#!/usr/bin/env python3
"""
fix_williamhill_player_market_keys.py

Post-process patch for William Hill player markets that were scraped into JSON
but not displayed on player pages because the market key / player field is off.

Fixes:
  - Player Cards        -> Player To Get A Card
  - Player Assists      -> Player To Assist
  - Player Fouls Won    -> clean player names + correct Over N => N+1 threshold
  - Player Fouls Committed -> clean player names + correct Over N => N+1 threshold

Also filters obvious William Hill sent-off odds leaking into Player Cards,
for example duplicate "To Be Carded" rows at 100/1+.

Run AFTER:
  python scripts/Football/fetch_williamhill_worldcup_props.py
  python scripts/Football/fix_williamhill_player_shot_lines.py
  python scripts/Football/fix_williamhill_embedded_player_shots.py

Run BEFORE:
  python scripts/Football/generate_worldcup_page.py
"""

import json
import re
import shutil
from pathlib import Path
from datetime import datetime, timezone
from fractions import Fraction

ROOT = Path(__file__).resolve().parents[2]
PROPS_PATH = ROOT / "football" / "data" / "williamhill_worldcup_props.json"
BACKUP_PATH = ROOT / "football" / "data" / "williamhill_worldcup_props.before_wh_player_market_keys_fix.json"


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def normalize(s):
    s = clean(s).lower().replace("&", "and").replace("?", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def dec_odds(frac):
    x = clean(frac).upper()
    if x in {"EVS", "EVENS", "EVEN"}:
        return 2.0
    try:
        return float(Fraction(x)) + 1.0
    except Exception:
        return 0.0


def threshold_from_over_number(n):
    n = int(float(n))
    # WH integer count row: Over 1 = 2+, Over 2 = 3+
    threshold_n = n + 1
    line = f"{threshold_n - 0.5:g}"
    return f"{threshold_n}+", line


def threshold_from_atleast_number(n):
    n = int(float(n))
    line = f"{n - 0.5:g}"
    return f"{n}+", line


def parse_player_and_foul_threshold(selection, current_player, kind):
    """
    kind: 'Foul Won' or 'Foul Committed'
    """
    raw = clean(selection)
    player_blob = clean(current_player) or raw

    patterns = [
        rf"^(?P<player>.+?)\s+Over\s+(?P<n>\d+(?:\.\d+)?)\s+Fouls?\s+{kind.split()[-1]}(?:\s+\d\+)?$",
        rf"^(?P<player>.+?)\s+Over\s+(?P<n>\d+(?:\.\d+)?)\s+Foul\s+{kind.split()[-1]}(?:\s+\d\+)?$",
        rf"^(?P<player>.+?)\s+At\s+Least\s+(?P<a>\d+)\s+Fouls?\s+{kind.split()[-1]}$",
        rf"^(?P<player>.+?)\s+(?P<th>\d\+)\s+Fouls?\s+{kind.split()[-1]}$",
    ]

    combined = raw
    if current_player and raw not in current_player:
        combined = f"{current_player} {raw}"

    for source in [combined, raw, player_blob]:
        source = clean(source)
        for pat in patterns:
            m = re.match(pat, source, flags=re.I)
            if not m:
                continue

            player = clean(m.group("player"))
            player = re.sub(r"\s+Over\s+\d+(?:\.\d+)?\s+Fouls?.*$", "", player, flags=re.I).strip()
            player = re.sub(r"\s+\d\+\s+Fouls?.*$", "", player, flags=re.I).strip()

            if m.groupdict().get("n"):
                threshold, line = threshold_from_over_number(m.group("n"))
            elif m.groupdict().get("a"):
                threshold, line = threshold_from_atleast_number(m.group("a"))
            elif m.groupdict().get("th"):
                th = m.group("th")
                threshold = th
                try:
                    line = f"{int(th[:-1]) - 0.5:g}"
                except Exception:
                    line = ""
            else:
                threshold, line = "", ""

            return player, threshold, line

    # Fallback: clean common bad player field like "Jonathan David Over 1 Foul Won"
    player = re.sub(r"\s+Over\s+\d+(?:\.\d+)?\s+Fouls?\s+(?:Won|Committed).*$", "", player_blob, flags=re.I).strip()
    threshold = clean(re.search(r"(\d\+)", raw).group(1)) if re.search(r"(\d\+)", raw) else clean(current_player and "")
    line = ""
    if threshold.endswith("+"):
        try:
            line = f"{int(threshold[:-1]) - 0.5:g}"
        except Exception:
            pass
    return player, threshold, line


def parse_player_card(selection, current_player):
    raw = clean(selection)
    player = clean(current_player)

    if not player:
        player = re.sub(
            r"\s+(?:To\s+Be\s+Carded|To\s+Get\s+A\s+Card|Shown\s+A\s+Card|Player\s+Shown\s+A\s+Card).*$",
            "",
            raw,
            flags=re.I,
        ).strip()

    player = re.sub(
        r"\s+(?:To\s+Be\s+Carded|To\s+Get\s+A\s+Card|Shown\s+A\s+Card).*$",
        "",
        player,
        flags=re.I,
    ).strip()

    return player


def parse_player_assist(selection, current_player):
    raw = clean(selection)
    player = clean(current_player)

    if not player:
        player = re.sub(r"\s+(?:1\+|To\s+Assist|Player\s+To\s+Assist).*$", "", raw, flags=re.I).strip()

    player = re.sub(r"\s+(?:1\+|To\s+Assist|Player\s+To\s+Assist).*$", "", player, flags=re.I).strip()
    return player


def valid_player(player):
    if not player or len(player) < 3:
        return False
    low = player.lower()
    bad = ["show more", "odds format", "help", "media", "bet builder", "player shown", "match over", "team"]
    if any(b in low for b in bad):
        return False
    if re.match(r"^(over|under|yes|no|draw|home|away)\b", low):
        return False
    return True


def fix_card_market(market):
    fixed = []
    by_player = {}

    for s in market.get("selections", []):
        odds = clean(s.get("odds", ""))
        if not odds:
            continue

        # Drop obvious sent-off leakage. Carded odds at 100/1+ are not this market.
        if dec_odds(odds) > 51:
            continue

        player = parse_player_card(s.get("selection", ""), s.get("player", ""))
        if not valid_player(player):
            continue

        row = dict(s)
        row.update({
            "selection": f"{player} To Get A Card",
            "normalized_selection": normalize(f"{player} To Get A Card"),
            "player": player,
            "prop_type": "player_to_get_a_card",
            "threshold": "To Get A Card",
            "line": "0.5",
            "williamhill_player_market_key_fix": True,
        })

        # Keep best price for same player after filtering sent-off leak.
        k = normalize(player)
        if k not in by_player or dec_odds(row["odds"]) > dec_odds(by_player[k]["odds"]):
            by_player[k] = row

    fixed = list(by_player.values())
    market["market"] = "Player To Get A Card"
    market["normalized_market"] = "player_to_get_a_card"
    market["selections"] = fixed
    market["selection_count"] = len(fixed)
    market["williamhill_player_market_key_fix"] = True


def fix_assist_market(market):
    fixed = []
    by_player = {}

    for s in market.get("selections", []):
        odds = clean(s.get("odds", ""))
        if not odds:
            continue

        player = parse_player_assist(s.get("selection", ""), s.get("player", ""))
        if not valid_player(player):
            continue

        row = dict(s)
        row.update({
            "selection": f"{player} To Assist",
            "normalized_selection": normalize(f"{player} To Assist"),
            "player": player,
            "prop_type": "player_to_assist",
            "threshold": "1+",
            "line": "0.5",
            "williamhill_player_market_key_fix": True,
        })

        k = normalize(player)
        if k not in by_player or dec_odds(row["odds"]) > dec_odds(by_player[k]["odds"]):
            by_player[k] = row

    fixed = list(by_player.values())
    market["market"] = "Player To Assist"
    market["normalized_market"] = "player_to_assist"
    market["selections"] = fixed
    market["selection_count"] = len(fixed)
    market["williamhill_player_market_key_fix"] = True


def fix_foul_market(market, normalized_market, kind, prop_type):
    fixed = []
    seen = set()

    for s in market.get("selections", []):
        odds = clean(s.get("odds", ""))
        if not odds:
            continue

        player, threshold, line = parse_player_and_foul_threshold(
            s.get("selection", ""),
            s.get("player", ""),
            kind,
        )

        if not valid_player(player) or not threshold or not line:
            continue

        row = dict(s)
        row.update({
            "selection": f"{player} {threshold} {kind}s" if not kind.endswith("s") else f"{player} {threshold} {kind}",
            "normalized_selection": normalize(f"{player} {threshold} {kind}"),
            "player": player,
            "prop_type": prop_type,
            "threshold": threshold,
            "line": line,
            "williamhill_player_market_key_fix": True,
        })

        k = (normalize(player), threshold, odds)
        if k in seen:
            continue
        seen.add(k)
        fixed.append(row)

    market["market"] = f"Player {kind}s" if not kind.endswith("s") else f"Player {kind}"
    market["normalized_market"] = normalized_market
    market["selections"] = fixed
    market["selection_count"] = len(fixed)
    market["williamhill_player_market_key_fix"] = True


def main():
    if not PROPS_PATH.exists():
        raise SystemExit(f"Missing file: {PROPS_PATH}")

    data = json.loads(PROPS_PATH.read_text(encoding="utf-8"))
    shutil.copy2(PROPS_PATH, BACKUP_PATH)

    touched = 0
    stats = {
        "player_to_get_a_card": 0,
        "player_to_assist": 0,
        "player_fouls_won": 0,
        "player_fouls_committed": 0,
    }

    for match in data.get("matches", []):
        match_touched = False

        for market in match.get("markets", []):
            mk_raw = market.get("normalized_market") or normalize(market.get("market", ""))

            if mk_raw in {"player_cards", "player_card", "player_shown_a_card", "player_to_get_a_card"} or normalize(market.get("market", "")) in {"player_cards", "player_card"}:
                fix_card_market(market)
                stats["player_to_get_a_card"] += market.get("selection_count", 0)
                match_touched = True

            elif mk_raw in {"player_assists", "player_assist", "player_to_assist"} or normalize(market.get("market", "")) in {"player_assists", "player_assist"}:
                fix_assist_market(market)
                stats["player_to_assist"] += market.get("selection_count", 0)
                match_touched = True

            elif mk_raw in {"player_fouls_won", "fouls_won"}:
                fix_foul_market(market, "player_fouls_won", "Fouls Won", "player_fouls_won")
                stats["player_fouls_won"] += market.get("selection_count", 0)
                match_touched = True

            elif mk_raw in {"player_fouls_committed", "fouls_committed"}:
                fix_foul_market(market, "player_fouls_committed", "Fouls Committed", "player_fouls_committed")
                stats["player_fouls_committed"] += market.get("selection_count", 0)
                match_touched = True

        if match_touched:
            match["market_count"] = len(match.get("markets", []))
            touched += 1

    data["williamhill_player_market_keys_fixed_at"] = datetime.now(timezone.utc).isoformat()
    data["generated_at"] = datetime.now(timezone.utc).isoformat()

    PROPS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print("William Hill player market key/name fix complete")
    print(f"Backup: {BACKUP_PATH}")
    print(f"Matches touched: {touched}")
    for k, v in stats.items():
        print(f"{k}: {v} selections")
    print(f"Output: {PROPS_PATH}")


if __name__ == "__main__":
    main()
