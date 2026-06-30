#!/usr/bin/env python3
"""
prepare_midnite_worldcup_props_fixtures.py

Creates one shared 15-fixture snapshot for both Midnite production scrapers.

Why this exists:
- moneylines are refreshed once;
- already-started/in-play fixtures are excluded;
- the same exact 15 fixtures are used by both the main/player-props scraper
  and the separate Match/Home/Away Shots and Shots-on-Target scraper.

Input:
    football/data/midnite_worldcup_moneylines.json

Output:
    football/data/midnite_worldcup_props_fixtures_prod15.json
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

INPUT_PATH = (
    ROOT
    / "football"
    / "data"
    / "midnite_worldcup_moneylines.json"
)

OUTPUT_PATH = (
    ROOT
    / "football"
    / "data"
    / "midnite_worldcup_props_fixtures_prod15.json"
)

MAX_MATCHES = 15
MIN_MATCHES = 1
MIN_LEAD_MINUTES = 15

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

WEEKDAYS = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}

LIVE_WORDS = (
    "live",
    "in-play",
    "in play",
    "started",
    "suspended",
    "finished",
    "full time",
)


def clean(value: Any) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def local_now() -> datetime:
    return datetime.now().astimezone()


def with_local_timezone(
    value: datetime,
    now: datetime,
) -> datetime:
    if value.tzinfo is None:
        return value.replace(
            tzinfo=now.tzinfo
        )

    return value.astimezone(
        now.tzinfo
    )


def parse_kickoff(
    raw_value: Any,
    now: datetime,
) -> tuple[
    datetime | None,
    str,
]:
    text = clean(raw_value)
    low = text.casefold()

    if not text:
        return None, "unknown"

    if any(
        word in low
        for word in LIVE_WORDS
    ):
        return None, "started"

    # ISO-like values.
    try:
        iso_value = datetime.fromisoformat(
            text.replace(
                "Z",
                "+00:00",
            )
        )
        return (
            with_local_timezone(
                iso_value,
                now,
            ),
            "parsed",
        )
    except ValueError:
        pass

    time_match = re.search(
        r"(\d{1,2}):(\d{2})",
        text,
    )

    if not time_match:
        return None, "unknown"

    hour = int(
        time_match.group(1)
    )
    minute = int(
        time_match.group(2)
    )

    # Today / Tomorrow.
    if re.search(
        r"\btoday\b",
        low,
    ):
        value = now.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        return value, "parsed"

    if re.search(
        r"\btomorrow\b",
        low,
    ):
        value = (
            now
            + timedelta(days=1)
        ).replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        return value, "parsed"

    # Explicit date, e.g. "Sun 28th Jun 20:00" or "28 June 2026 20:00".
    explicit = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"([A-Za-z]+)"
        r"(?:\s+(\d{4}))?\b",
        text,
        flags=re.IGNORECASE,
    )

    if explicit:
        day = int(
            explicit.group(1)
        )
        month_name = (
            explicit.group(2)
            .casefold()
        )
        month = MONTHS.get(
            month_name
        )
        year_text = explicit.group(3)

        if month:
            year = (
                int(year_text)
                if year_text
                else now.year
            )

            try:
                value = datetime(
                    year,
                    month,
                    day,
                    hour,
                    minute,
                    tzinfo=now.tzinfo,
                )

                # If the year was omitted and the parsed date is implausibly
                # far behind, treat it as the next calendar year.
                if (
                    not year_text
                    and value
                    < now - timedelta(days=180)
                ):
                    value = value.replace(
                        year=year + 1
                    )

                return value, "parsed"
            except ValueError:
                return None, "unknown"

    # Weekday-only value, e.g. "Sun 20:00".
    weekday_match = re.search(
        r"\b("
        + "|".join(
            re.escape(name)
            for name in WEEKDAYS
        )
        + r")\b",
        low,
        flags=re.IGNORECASE,
    )

    if weekday_match:
        target_weekday = WEEKDAYS[
            weekday_match
            .group(1)
            .casefold()
        ]
        days_ahead = (
            target_weekday
            - now.weekday()
        ) % 7

        value = (
            now
            + timedelta(
                days=days_ahead
            )
        ).replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )

        # Same-day times that have already passed are old/live fixtures,
        # not next week's fixture.
        return value, "parsed"

    return None, "unknown"


def load_moneylines() -> list[
    dict[str, Any]
]:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            "Midnite moneylines JSON is missing. "
            "Run fetch_midnite_worldcup_moneylines.py first."
        )

    payload = json.loads(
        INPUT_PATH.read_text(
            encoding="utf-8"
        )
    )
    matches = (
        payload.get("matches")
        or []
    )

    if not isinstance(
        matches,
        list,
    ):
        raise RuntimeError(
            "Midnite moneylines JSON has no valid matches list"
        )

    return matches


def main() -> None:
    print("=" * 72)
    print("PREPARE MIDNITE PROD15 FIXTURE SNAPSHOT")
    print("=" * 72)

    now = local_now()
    cutoff = (
        now
        + timedelta(
            minutes=MIN_LEAD_MINUTES
        )
    )

    source_matches = load_moneylines()
    candidates = []
    excluded_started = []
    unknown = []

    for original_index, match in enumerate(
        source_matches
    ):
        kickoff, status = parse_kickoff(
            match.get("kickoff"),
            now,
        )
        label = (
            f"{clean(match.get('home'))} v "
            f"{clean(match.get('away'))}"
        )

        if status == "started":
            excluded_started.append(
                {
                    "match": label,
                    "kickoff":
                        clean(
                            match.get(
                                "kickoff"
                            )
                        ),
                    "reason":
                        "live/started status text",
                }
            )
            continue

        if (
            kickoff is not None
            and kickoff <= cutoff
        ):
            excluded_started.append(
                {
                    "match": label,
                    "kickoff":
                        clean(
                            match.get(
                                "kickoff"
                            )
                        ),
                    "reason":
                        (
                            "kickoff passed or within "
                            f"{MIN_LEAD_MINUTES} minutes"
                        ),
                }
            )
            continue

        if kickoff is None:
            unknown.append(
                {
                    "original_index":
                        original_index,
                    "match":
                        match,
                }
            )
            continue

        candidates.append(
            {
                "original_index":
                    original_index,
                "kickoff":
                    kickoff,
                "match":
                    match,
            }
        )

    candidates.sort(
        key=lambda item: (
            item["kickoff"],
            item["original_index"],
        )
    )
    unknown.sort(
        key=lambda item:
            item["original_index"]
    )

    selected = [
        item["match"]
        for item in candidates
    ]

    # Unknown kickoff formats are retained only after all clearly parsed
    # upcoming fixtures, preserving original moneylines order.
    selected.extend(
        item["match"]
        for item in unknown
    )
    selected = selected[
        :MAX_MATCHES
    ]

    if len(selected) < MIN_MATCHES:
        print(
            f"ERROR: Found {len(selected)} eligible fixtures; "
            f"minimum required is {MIN_MATCHES}"
        )
        print(
            f"Source fixtures: {len(source_matches)}"
        )
        print(
            f"Excluded started/imminent: "
            f"{len(excluded_started)}"
        )
        raise SystemExit(1)

    if len(selected) < MAX_MATCHES:
        print(
            f"AVAILABILITY NOTE: only {len(selected)} eligible fixtures "
            f"currently have markets; continuing with all available "
            f"fixtures (maximum {MAX_MATCHES})."
        )

    event_ids = [
        clean(
            match.get("event_id")
        )
        for match in selected
    ]

    if len(event_ids) != len(
        set(event_ids)
    ):
        raise RuntimeError(
            "Duplicate event IDs detected in selected Midnite fixtures"
        )

    output = {
        "bookmaker": "Midnite",
        "competition":
            "FIFA World Cup 2026",
        "created_at":
            now.isoformat(),
        "max_matches":
            MAX_MATCHES,
        "requested_max_matches":
            MAX_MATCHES,
        "expected_match_count":
            len(selected),
        "minimum_lead_minutes":
            MIN_LEAD_MINUTES,
        "source_path":
            str(INPUT_PATH),
        "source_match_count":
            len(source_matches),
        "selected_match_count":
            len(selected),
        "excluded_started_or_imminent":
            excluded_started,
        "unknown_kickoff_count":
            len(unknown),
        "matches":
            selected,
    }

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    OUTPUT_PATH.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        f"Selected: {len(selected)}/{MAX_MATCHES}"
    )
    print(
        f"Excluded started/imminent: "
        f"{len(excluded_started)}"
    )
    print(
        f"Unknown kickoff format retained: "
        f"{len(unknown)}"
    )
    print("")

    for index, match in enumerate(
        selected,
        start=1,
    ):
        print(
            f"[{index:02d}] "
            f"{clean(match.get('home'))} v "
            f"{clean(match.get('away'))} | "
            f"{clean(match.get('kickoff'))}"
        )

    print("")
    print(
        f"Wrote shared fixture snapshot: "
        f"{OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
