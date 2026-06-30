#!/usr/bin/env python3
"""
LiveScoreBet World Cup moneylines flexible-date PRODUCTION V2.

Writes a validated staging file, backs up the current canonical JSON,
and atomically promotes:
    football/data/livescorebet_worldcup_moneylines.json

The parser accepts:
- 2/7/2026 01:00
- Today 18:00 or Today, 18:00
- Tomorrow 02:00 or Tomorrow, 02:00
- Starting in 45 min
- Today / Tomorrow on one line followed by a time on the next line
- a date heading followed by time-only fixture rows
"""

import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

LIVE_OUT_PATH = (
    ROOT
    / "football"
    / "data"
    / "livescorebet_worldcup_moneylines.json"
)
STAGING_OUT_PATH = (
    ROOT
    / "football"
    / "data"
    / "livescorebet_worldcup_moneylines_PRODUCTION_V2_STAGING.json"
)
DEBUG_PATH = (
    ROOT
    / "football"
    / "debug"
    / "livescorebet_worldcup_text_debug_PRODUCTION_V2.txt"
)
AUDIT_PATH = (
    ROOT
    / "football"
    / "debug"
    / "livescorebet_worldcup_moneylines_PRODUCTION_V2_audit.json"
)
BACKUP_DIR = (
    ROOT
    / "football"
    / "data"
    / "backups"
)

MIN_MATCHES = 5

URL = "https://www.livescorebet.com/ie/coupon/21127/"

ODDS_RE = re.compile(
    r"^(?:\d+/\d+|EVS|EVENS|EVEN)$",
    re.IGNORECASE,
)
FULL_DATE_TIME_RE = re.compile(
    r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})$",
    re.IGNORECASE,
)
DATE_ONLY_RE = re.compile(
    r"^(\d{1,2})/(\d{1,2})/(\d{4})$",
    re.IGNORECASE,
)
TIME_RE = re.compile(
    r"^(\d{1,2}):(\d{2})$",
    re.IGNORECASE,
)
RELATIVE_RE = re.compile(
    r"^(Today|Tomorrow)\s*,?\s*(?:(\d{1,2}):(\d{2}))?$",
    re.IGNORECASE,
)
STARTING_IN_RE = re.compile(
    r"^Starting\s+in\s+"
    r"(?:(\d+)\s*(?:h|hr|hrs|hour|hours))?"
    r"(?:\s*(\d+)\s*(?:m|min|mins|minute|minutes))?$",
    re.IGNORECASE,
)

WORLD_CUP_TEAMS = {
    "Mexico", "South Africa", "South Korea", "Czech Republic", "Czechia",
    "Canada", "Bosnia & Herzegovina", "Bosnia and Herzegovina", "Bosnia",
    "USA", "Paraguay", "Qatar", "Switzerland", "Brazil", "Morocco",
    "Haiti", "Scotland", "Australia", "Turkey", "Turkiye", "Türkiye",
    "Germany", "Curacao", "Curaçao", "Netherlands", "Japan",
    "Ivory Coast", "Ecuador", "Sweden", "Tunisia", "Spain",
    "Cape Verde", "Cape Verde Islands", "Belgium", "Egypt",
    "Saudi Arabia", "Uruguay", "Iran", "New Zealand", "France",
    "Senegal", "Iraq", "Norway", "Argentina", "Algeria", "Austria",
    "Jordan", "Portugal", "DR Congo", "England", "Croatia", "Ghana",
    "Panama", "Colombia", "Uzbekistan",
}

TEAM_ALIASES = {
    "Czech Republic": "Czechia",
    "Bosnia & Herzegovina": "Bosnia",
    "Bosnia and Herzegovina": "Bosnia",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Curaçao": "Curacao",
    "Cape Verde Islands": "Cape Verde",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def canonical_team(value):
    value = clean(value)
    return TEAM_ALIASES.get(value, value)


def is_odds(value):
    return bool(ODDS_RE.fullmatch(clean(value)))


def is_team_line(value):
    return clean(value) in WORLD_CUP_TEAMS


def date_label(value):
    return f"{value.day}/{value.month}/{value.year}"


def local_now():
    return datetime.now().astimezone()


def parse_date_context(value, now):
    text = clean(value)

    full = FULL_DATE_TIME_RE.fullmatch(text)
    if full:
        dt = datetime(
            int(full.group(3)),
            int(full.group(2)),
            int(full.group(1)),
            int(full.group(4)),
            int(full.group(5)),
            tzinfo=now.tzinfo,
        )
        return dt.date(), f"{int(full.group(4)):02d}:{int(full.group(5)):02d}", "explicit"

    date_only = DATE_ONLY_RE.fullmatch(text)
    if date_only:
        dt = datetime(
            int(date_only.group(3)),
            int(date_only.group(2)),
            int(date_only.group(1)),
            tzinfo=now.tzinfo,
        )
        return dt.date(), "", "explicit_date_heading"

    relative = RELATIVE_RE.fullmatch(text)
    if relative:
        days = 1 if relative.group(1).casefold() == "tomorrow" else 0
        day = (now + timedelta(days=days)).date()
        clock = ""
        if relative.group(2) is not None:
            clock = f"{int(relative.group(2)):02d}:{int(relative.group(3)):02d}"
        return day, clock, relative.group(1).casefold()

    starting = STARTING_IN_RE.fullmatch(text)
    if starting:
        hours = int(starting.group(1) or 0)
        minutes = int(starting.group(2) or 0)

        if hours or minutes:
            target = now + timedelta(
                hours=hours,
                minutes=minutes,
            )

            # Countdown labels may be rounded by the site. Round the inferred
            # kickoff to the nearest five minutes for a stable fixture time.
            total_minutes = target.hour * 60 + target.minute
            rounded_minutes = int(round(total_minutes / 5.0) * 5)
            day_shift, minute_of_day = divmod(
                rounded_minutes,
                24 * 60,
            )
            target_date = (
                target.date()
                + timedelta(days=day_shift)
            )
            hour, minute = divmod(minute_of_day, 60)

            return (
                target_date,
                f"{hour:02d}:{minute:02d}",
                "starting_in",
            )

    return None, "", ""


def parse_schedule(lines, start_index, current_date, now):
    """
    Read the schedule immediately following one team/odds block.

    Returns:
        (date, HH:MM, raw_schedule, source, lines_consumed)
    """
    lookahead = lines[start_index:start_index + 4]

    for offset, line in enumerate(lookahead):
        parsed_date, parsed_time, source = parse_date_context(line, now)
        if parsed_date is not None and parsed_time:
            return (
                parsed_date,
                parsed_time,
                line,
                source,
                offset + 1,
            )

        if parsed_date is not None:
            if offset + 1 < len(lookahead):
                clock_match = TIME_RE.fullmatch(lookahead[offset + 1])
                if clock_match:
                    clock = (
                        f"{int(clock_match.group(1)):02d}:"
                        f"{int(clock_match.group(2)):02d}"
                    )
                    return (
                        parsed_date,
                        clock,
                        f"{line} {lookahead[offset + 1]}",
                        source,
                        offset + 2,
                    )

    # A time-only row can inherit the most recent date heading.
    for offset, line in enumerate(lookahead):
        clock_match = TIME_RE.fullmatch(line)
        if clock_match and current_date is not None:
            clock = (
                f"{int(clock_match.group(1)):02d}:"
                f"{int(clock_match.group(2)):02d}"
            )
            return (
                current_date,
                clock,
                line,
                "inherited_date_heading",
                offset + 1,
            )

    return None, "", " | ".join(lookahead), "unparsed", 0


def parse_livescorebet_text(text):
    lines = [
        clean(line)
        for line in text.splitlines()
        if clean(line)
    ]
    now = local_now()
    current_date = None
    matches = []
    rejected_blocks = []

    i = 0
    while i < len(lines):
        context_date, _, _ = parse_date_context(lines[i], now)
        if context_date is not None:
            current_date = context_date

        candidate = (
            i + 4 < len(lines)
            and is_team_line(lines[i])
            and is_team_line(lines[i + 1])
            and is_odds(lines[i + 2])
            and is_odds(lines[i + 3])
            and is_odds(lines[i + 4])
        )

        if not candidate:
            i += 1
            continue

        schedule_date, time_value, raw_schedule, schedule_source, consumed = (
            parse_schedule(
                lines,
                i + 5,
                current_date,
                now,
            )
        )

        home = canonical_team(lines[i])
        away = canonical_team(lines[i + 1])

        if schedule_date is None or not time_value:
            rejected_blocks.append({
                "line_index": i,
                "match": f"{home} v {away}",
                "odds": lines[i + 2:i + 5],
                "following_lines": lines[i + 5:i + 10],
                "reason": "schedule_not_parsed",
            })
            i += 5
            continue

        current_date = schedule_date

        matches.append({
            "competition": "FIFA World Cup",
            "bookmaker": "LiveScoreBet",
            "date_label": (
                f"{schedule_date.day}/"
                f"{schedule_date.month}/"
                f"{schedule_date.year}"
            ),
            "time": time_value,
            "match": f"{home} v {away}",
            "home_team": home,
            "away_team": away,
            "market": "Match Odds",
            "odds": {
                "home": lines[i + 2].upper(),
                "draw": lines[i + 3].upper(),
                "away": lines[i + 4].upper(),
            },
            "source_url": URL,
            "raw_schedule": raw_schedule,
            "schedule_source": schedule_source,
        })

        i += max(5 + consumed, 6)

    seen = set()
    unique = []

    for match in matches:
        key = (
            match["date_label"],
            match["time"],
            match["match"],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(match)

    return unique, rejected_blocks


def accept_cookies(page):
    for label in [
        "Accept All",
        "Accept all",
        "I Accept",
        "Accept",
        "Agree",
        "Allow all",
        "Got it",
    ]:
        try:
            button = page.get_by_role(
                "button",
                name=re.compile(label, re.IGNORECASE),
            )
            if button.count():
                button.first.click(timeout=3000)
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass



def validate_output(matches, rejected_blocks):
    errors = []
    warnings = []

    if len(matches) < MIN_MATCHES:
        errors.append(
            f"Only {len(matches)} matches parsed; "
            f"minimum safety threshold is {MIN_MATCHES}."
        )

    if rejected_blocks:
        errors.append(
            f"{len(rejected_blocks)} team/odds candidate block(s) "
            "could not be assigned a kickoff."
        )

    seen = set()
    for index, match in enumerate(matches, start=1):
        key = (
            clean(match.get("date_label")),
            clean(match.get("time")),
            clean(match.get("match")),
        )

        if key in seen:
            errors.append(
                f"Duplicate fixture at row {index}: {key}"
            )
        seen.add(key)

        odds = match.get("odds") or {}
        for side in ("home", "draw", "away"):
            if not is_odds(odds.get(side)):
                errors.append(
                    f"Row {index} {match.get('match')}: "
                    f"invalid {side} odds {odds.get(side)!r}"
                )

        if not clean(match.get("home_team")):
            errors.append(
                f"Row {index}: missing home team."
            )
        if not clean(match.get("away_team")):
            errors.append(
                f"Row {index}: missing away team."
            )
        if not clean(match.get("time")):
            errors.append(
                f"Row {index} {match.get('match')}: missing kickoff time."
            )

        if match.get("schedule_source") == "starting_in":
            warnings.append(
                f"{match.get('match')}: kickoff inferred from countdown "
                f"{match.get('raw_schedule')!r}."
            )

    return {
        "status": "PASS" if not errors else "FAIL",
        "match_count": len(matches),
        "rejected_candidate_count": len(rejected_blocks),
        "errors": errors,
        "warnings": warnings,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }


def atomic_promote():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    backup_path = None
    if LIVE_OUT_PATH.exists():
        backup_path = (
            BACKUP_DIR
            / f"livescorebet_worldcup_moneylines_before_prod_v2_{timestamp}.json"
        )
        shutil.copy2(LIVE_OUT_PATH, backup_path)

    temporary_live = LIVE_OUT_PATH.with_suffix(".json.tmp")
    shutil.copy2(STAGING_OUT_PATH, temporary_live)
    os.replace(temporary_live, LIVE_OUT_PATH)

    return backup_path


def main():
    STAGING_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page(
            viewport={"width": 1700, "height": 1000}
        )

        print(f"Opening {URL}")
        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )
        page.wait_for_timeout(9000)
        accept_cookies(page)

        try:
            page.get_by_text(
                "1 X 2",
                exact=True,
            ).first.click(timeout=3000)
            page.wait_for_timeout(1500)
        except Exception:
            pass

        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
        except Exception:
            pass

        for index in range(28):
            print(
                f"Loading page section {index + 1}/28..."
            )
            page.mouse.wheel(0, 750)
            page.wait_for_timeout(650)

        text = page.locator("body").inner_text(
            timeout=30000
        )
        DEBUG_PATH.write_text(
            text,
            encoding="utf-8",
        )

        matches, rejected_blocks = parse_livescorebet_text(
            text
        )

        output = {
            "sport": "football",
            "competition": "FIFA World Cup",
            "bookmaker": "LiveScoreBet",
            "market": "Match Odds",
            "scraper_version": "production_v2_flexible_dates",
            "source_url": URL,
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "match_count": len(matches),
            "rejected_candidate_count": len(rejected_blocks),
            "matches": matches,
        }

        validation = validate_output(
            matches,
            rejected_blocks,
        )

        STAGING_OUT_PATH.write_text(
            json.dumps(
                output,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        AUDIT_PATH.write_text(
            json.dumps(
                {
                    "validation": validation,
                    "rejected_candidates": rejected_blocks,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print("")
        print("=" * 72)
        print("LIVESCOREBET MONEYLINES PRODUCTION V2")
        print("=" * 72)
        print(
            f"Parsed {len(matches)} matches → "
            f"{STAGING_OUT_PATH}"
        )
        print(
            f"Rejected team/odds candidates: "
            f"{len(rejected_blocks)}"
        )
        print(f"Audit → {AUDIT_PATH}")

        for match in matches:
            print(
                f"- {match['date_label']} {match['time']} | "
                f"{match['match']} | "
                f"H {match['odds']['home']} "
                f"D {match['odds']['draw']} "
                f"A {match['odds']['away']} | "
                f"{match['schedule_source']}"
            )

        if validation["warnings"]:
            print("")
            print("Warnings:")
            for warning in validation["warnings"]:
                print(f"- {warning}")

        if validation["status"] != "PASS":
            print("")
            print("VALIDATION FAIL — production JSON was NOT changed.")
            for error in validation["errors"]:
                print(f"- {error}")

            if rejected_blocks:
                print("")
                print("Unparsed candidate blocks:")
                for item in rejected_blocks:
                    print(
                        f"- {item['match']}: "
                        f"{item['following_lines']}"
                    )

            browser.close()
            raise SystemExit(1)

        backup_path = atomic_promote()

        print("")
        print("VALIDATION PASS")
        if backup_path:
            print(f"Previous live backup → {backup_path}")
        else:
            print("No previous live JSON existed; no backup required.")
        print(f"Live JSON promoted → {LIVE_OUT_PATH}")

        browser.close()


if __name__ == "__main__":
    main()
