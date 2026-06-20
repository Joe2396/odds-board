#!/usr/bin/env python3
"""
inspect_betvictor_cards_group.py

Read-only targeted inspector for BetVictor's Cards coupon group.

For Ecuador v Curacao it:
- loads the event in a real browser session;
- fetches the coupon-group list;
- finds the Cards group id (expected 19295);
- fetches that exact coupon endpoint directly;
- saves the full JSON;
- prints every card-related market object and likely selection/price row.

It does NOT modify production JSON.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PROPS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
OUT_PATH = ROOT / "football" / "data" / "betvictor_ecuador_cards_group.json"
DEBUG_PATH = (
    ROOT
    / "football"
    / "debug"
    / "betvictor_ecuador_cards_group_full.json"
)

MATCH_NAME = "Ecuador v Curacao"
HEADLESS = False

CARD_WORDS = (
    "card",
    "carded",
    "booked",
    "booking",
    "yellow",
    "red card",
    "caution",
)

NAME_KEYS = (
    "name",
    "title",
    "label",
    "selection_name",
    "participant_name",
    "runner_name",
    "outcome_name",
    "display_name",
    "market_name",
)

PRICE_KEYS = (
    "odds",
    "price",
    "fractional",
    "fractional_price",
    "decimal",
    "decimal_price",
    "display_price",
    "price_num",
    "price_den",
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def load_event_url() -> str:
    data = json.loads(PROPS_PATH.read_text(encoding="utf-8"))

    for match in data.get("matches", []):
        if clean(match.get("match")) != MATCH_NAME:
            continue

        url = clean(match.get("source_url") or match.get("url"))
        if "/events/" not in url:
            raise SystemExit(f"{MATCH_NAME} has no usable BetVictor event URL")
        return url.split("?", 1)[0]

    raise SystemExit(f"Could not find {MATCH_NAME} in {PROPS_PATH}")


def event_id_from_url(url: str) -> str:
    match = re.search(r"/events/(\d+)", url)
    if match:
        return match.group(1)

    match = re.search(r"event_id=(\d+)", url)
    if match:
        return match.group(1)

    raise SystemExit(f"Could not extract event id from {url}")


def accept_cookies(page) -> None:
    for label in (
        "Accept All",
        "Accept all",
        "I Accept",
        "Accept",
        "Agree",
        "Allow all",
        "OK",
    ):
        try:
            button = page.get_by_role(
                "button",
                name=re.compile(f"^{re.escape(label)}$", re.I),
            )
            if button.count():
                button.first.click(timeout=1500)
                page.wait_for_timeout(400)
                return
        except Exception:
            pass


def contains_card_word(value: Any) -> bool:
    text = clean(value).lower()
    return any(word in text for word in CARD_WORDS)


def scalar_snapshot(obj: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}

    for key, value in obj.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            snapshot[str(key)] = clean(value)[:500]

    return snapshot


def walk_objects(
    node: Any,
    path: str,
    card_objects: list[dict[str, Any]],
    likely_rows: list[dict[str, Any]],
) -> None:
    if isinstance(node, dict):
        scalar_text = " | ".join(
            clean(value)
            for value in node.values()
            if isinstance(value, (str, int, float, bool))
        )

        if contains_card_word(scalar_text):
            card_objects.append(
                {
                    "path": path,
                    "keys": list(node.keys()),
                    "scalars": scalar_snapshot(node),
                }
            )

        names = [
            clean(node.get(key))
            for key in NAME_KEYS
            if clean(node.get(key))
        ]
        prices = [
            f"{key}={clean(node.get(key))}"
            for key in PRICE_KEYS
            if clean(node.get(key))
        ]

        # Include rows with a name + price, and all card-named rows even if
        # the price is nested nearby.
        if names and (prices or any(contains_card_word(name) for name in names)):
            likely_rows.append(
                {
                    "path": path,
                    "names": names,
                    "prices": prices,
                    "scalars": scalar_snapshot(node),
                }
            )

        for key, value in node.items():
            walk_objects(
                value,
                f"{path}.{key}",
                card_objects,
                likely_rows,
            )

    elif isinstance(node, list):
        for index, value in enumerate(node):
            walk_objects(
                value,
                f"{path}[{index}]",
                card_objects,
                likely_rows,
            )


def fetch_json(page, url: str) -> dict[str, Any] | list[Any]:
    result = page.evaluate(
        r"""async (url) => {
            const response = await fetch(url, {
                credentials: 'include',
                headers: {
                    'accept': 'application/json, text/plain, */*'
                }
            });

            const text = await response.text();

            return {
                ok: response.ok,
                status: response.status,
                url: response.url,
                text
            };
        }""",
        url,
    )

    if not result.get("ok"):
        raise RuntimeError(
            f"Fetch failed: HTTP {result.get('status')} {result.get('url')}"
        )

    try:
        return json.loads(result["text"])
    except Exception as exc:
        sample = clean(result.get("text"))[:500]
        raise RuntimeError(
            f"Response was not JSON: {sample}"
        ) from exc


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)

    event_url = load_event_url()
    event_id = event_id_from_url(event_url)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            viewport={"width": 1700, "height": 1000},
        )
        page = context.new_page()

        page.goto(
            event_url,
            wait_until="domcontentloaded",
            timeout=70000,
        )
        page.wait_for_timeout(5000)
        accept_cookies(page)

        groups_url = (
            "https://www.betvictor.com/"
            f"bv_event_level/en-ie/1/coupon_groups/100?event_id={event_id}"
        )
        groups_payload = fetch_json(page, groups_url)

        if not isinstance(groups_payload, list):
            raise SystemExit(
                f"Unexpected coupon-groups payload type: "
                f"{type(groups_payload).__name__}"
            )

        card_groups = [
            item
            for item in groups_payload
            if isinstance(item, dict)
            and contains_card_word(item.get("name"))
        ]

        if not card_groups:
            raise SystemExit("No Cards coupon group was returned")

        card_group = card_groups[0]
        card_group_id = clean(card_group.get("id"))

        coupon_url = (
            "https://www.betvictor.com/"
            f"bv_event_level/en-ie/1/coupons/{event_id}/{card_group_id}"
            f"?t={int(time.time() * 1000)}&period_id=0"
        )
        cards_payload = fetch_json(page, coupon_url)

        browser.close()

    DEBUG_PATH.write_text(
        json.dumps(cards_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    card_objects: list[dict[str, Any]] = []
    likely_rows: list[dict[str, Any]] = []
    walk_objects(
        cards_payload,
        "$",
        card_objects,
        likely_rows,
    )

    output = {
        "bookmaker": "BetVictor",
        "match": MATCH_NAME,
        "event_id": event_id,
        "source_url": event_url,
        "card_group": card_group,
        "coupon_url": coupon_url,
        "card_objects": card_objects,
        "likely_selection_rows": likely_rows,
    }

    OUT_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("BETVICTOR CARDS-GROUP INSPECTION")
    print("=" * 78)
    print(f"Match: {MATCH_NAME}")
    print(f"Event id: {event_id}")
    print(
        f"Cards group: id={card_group_id} "
        f"name={clean(card_group.get('name'))!r} "
        f"coupon_count={clean(card_group.get('coupon_count'))}"
    )
    print(f"Coupon URL: {coupon_url}")

    print(f"\nCard-related market objects: {len(card_objects)}")
    for index, item in enumerate(card_objects[:80], 1):
        print(f"\n[CARD {index}] {item['path']}")
        for key, value in item["scalars"].items():
            print(f"  {key}: {value}")

    print(f"\nLikely selection/price rows: {len(likely_rows)}")
    for index, row in enumerate(likely_rows[:250], 1):
        print(f"\n[ROW {index}] {row['path']}")
        print(f"  names: {' | '.join(row['names'])}")
        if row["prices"]:
            print(f"  prices: {' | '.join(row['prices'])}")
        for key, value in row["scalars"].items():
            if key not in NAME_KEYS and key not in PRICE_KEYS:
                print(f"  {key}: {value}")

    print(f"\nSaved summary: {OUT_PATH}")
    print(f"Saved full Cards JSON: {DEBUG_PATH}")
    print("No production JSON was modified.")


if __name__ == "__main__":
    main()
