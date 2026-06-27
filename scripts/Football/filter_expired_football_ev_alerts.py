#!/usr/bin/env python3
"""
filter_expired_football_ev_alerts.py

Removes only clearly expired fixtures from:
    football/data/ev_alerts.json

Rules:
- past dated fixtures are removed;
- today's fixtures are removed only after their listed kickoff time;
- unknown/unparseable dates are retained;
- bookmaker odds and EV calculations are never changed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EV_PATH = ROOT / "football" / "data" / "ev_alerts.json"

DATE_FORMATS = (
    "%a %d %b %Y",
    "%A %d %b %Y",
    "%d %b %Y",
    "%d %B %Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_kickoff(
    date_label: Any,
    time_value: Any,
    now: datetime,
) -> datetime | None:
    date_text = clean(date_label)
    time_text = clean(time_value)

    # Some rows store a complete ISO kickoff in either field.
    for candidate in (date_text, time_text):
        if not candidate:
            continue
        try:
            parsed = datetime.fromisoformat(
                candidate.replace("Z", "+00:00")
            )
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=now.tzinfo)
            return parsed.astimezone(now.tzinfo)
        except ValueError:
            pass

    time_match = re.search(
        r"\b(\d{1,2}):(\d{2})\b",
        time_text or date_text,
    )
    hour = int(time_match.group(1)) if time_match else 23
    minute = int(time_match.group(2)) if time_match else 59

    lowered = date_text.casefold()

    if "today" in lowered:
        return now.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )

    if "tomorrow" in lowered:
        from datetime import timedelta

        return (now + timedelta(days=1)).replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )

    # Remove a duplicated time if it appears in date_label.
    date_only = re.sub(
        r"\b\d{1,2}:\d{2}\b",
        "",
        date_text,
    ).strip()

    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(
                date_only,
                fmt,
            )
            return parsed.replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
                tzinfo=now.tzinfo,
            )
        except ValueError:
            continue

    return None


def main() -> None:
    if not EV_PATH.exists():
        raise FileNotFoundError(
            f"Football EV file not found: {EV_PATH}"
        )

    payload = json.loads(
        EV_PATH.read_text(
            encoding="utf-8"
        )
    )
    alerts = payload.get("alerts") or []

    if not isinstance(alerts, list):
        raise RuntimeError(
            "football/data/ev_alerts.json has no valid alerts list"
        )

    now = datetime.now().astimezone()
    kept = []
    removed = []
    unknown = []

    for alert in alerts:
        kickoff = parse_kickoff(
            alert.get("date_label"),
            alert.get("time"),
            now,
        )

        if kickoff is None:
            kept.append(alert)
            unknown.append(alert)
            continue

        if kickoff <= now:
            removed.append(alert)
        else:
            kept.append(alert)

    payload["alerts"] = kept
    payload["alert_count"] = len(kept)
    payload["moneyline_alert_count"] = sum(
        1
        for alert in kept
        if alert.get("type") == "moneyline_1x2"
    )
    payload["props_alert_count"] = sum(
        1
        for alert in kept
        if alert.get("type") == "props_player"
    )
    payload["expiry_filter"] = {
        "filtered_at": now.isoformat(),
        "removed_expired_alerts": len(removed),
        "retained_alerts": len(kept),
        "unknown_date_alerts_retained": len(unknown),
    }

    temp_path = EV_PATH.with_suffix(
        ".json.tmp"
    )
    temp_path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    json.loads(
        temp_path.read_text(
            encoding="utf-8"
        )
    )
    temp_path.replace(EV_PATH)

    print("=" * 68)
    print("FOOTBALL EV EXPIRY FILTER")
    print("=" * 68)
    print(f"Before: {len(alerts)}")
    print(f"Removed expired: {len(removed)}")
    print(f"Retained: {len(kept)}")
    print(
        "Unknown date formats retained: "
        f"{len(unknown)}"
    )

    if removed:
        print("")
        print("Removed fixtures:")
        seen = set()
        for alert in removed:
            label = (
                clean(alert.get("match")),
                clean(alert.get("date_label")),
                clean(alert.get("time")),
            )
            if label in seen:
                continue
            seen.add(label)
            print(
                f"  - {label[0]} | "
                f"{label[1]} {label[2]}"
            )

    print("")
    print(f"Updated: {EV_PATH}")


if __name__ == "__main__":
    main()
