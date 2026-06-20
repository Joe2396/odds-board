#!/usr/bin/env python3
"""
inspect_betvictor_ecuador_card_api.py

Read-only inspector for BetVictor player-card data on Ecuador v Curacao.

It captures the event-level and Bet Builder API responses, recursively searches
their JSON for card/booked/yellow/caution wording, and prints the smallest
matching objects with their JSON paths.

It does NOT modify production JSON.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PROPS_PATH = ROOT / "football" / "data" / "betvictor_worldcup_props.json"
OUT_PATH = ROOT / "football" / "data" / "betvictor_ecuador_card_api_inspection.json"
DEBUG_DIR = ROOT / "football" / "debug" / "betvictor_ecuador_card_api"

MATCH_NAME = "Ecuador v Curacao"
HEADLESS = False

KEYWORDS = (
    "shown a card",
    "to be carded",
    "get a card",
    "receive a card",
    "booked",
    "booking",
    "yellow card",
    "red card",
    "carded",
    "cards",
    "card",
    "caution",
)

RELEVANT_URL_BITS = (
    "bv_event_level",
    "bet_builder",
    "coupon_groups",
    "progressive_prices",
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slug(value: str) -> str:
    value = clean(value).lower()
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


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
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def click_text_control(page, text: str) -> bool:
    try:
        locator = page.get_by_text(text, exact=True)

        for index in range(locator.count() - 1, -1, -1):
            item = locator.nth(index)
            try:
                if not item.is_visible():
                    continue
                item.scroll_into_view_if_needed(timeout=1800)
                item.click(timeout=2500)
                page.wait_for_timeout(1600)
                return True
            except Exception:
                pass
    except Exception:
        pass

    return False


def expand_and_scroll(page) -> None:
    patterns = (
        re.compile(r"^Show More$", re.I),
        re.compile(r"^View More$", re.I),
        re.compile(r"^Load More$", re.I),
        re.compile(r"^Show All$", re.I),
    )

    for _ in range(8):
        changed = False

        for pattern in patterns:
            try:
                buttons = page.get_by_role("button", name=pattern)

                for index in range(buttons.count()):
                    button = buttons.nth(index)
                    try:
                        if not button.is_visible():
                            continue
                        button.scroll_into_view_if_needed(timeout=1500)
                        button.click(timeout=1800)
                        page.wait_for_timeout(400)
                        changed = True
                    except Exception:
                        pass
            except Exception:
                pass

        if not changed:
            break

    for _ in range(30):
        page.mouse.wheel(0, 700)
        page.wait_for_timeout(150)

    page.evaluate(
        r"""() => {
            const candidates = [];

            for (const el of document.querySelectorAll('*')) {
                const style = getComputedStyle(el);
                const range = el.scrollHeight - el.clientHeight;
                const rect = el.getBoundingClientRect();

                if (range < 150 || rect.height < 140 || rect.width < 250) {
                    continue;
                }

                if (!['auto', 'scroll', 'overlay'].includes(style.overflowY)) {
                    continue;
                }

                candidates.push({el, range});
            }

            candidates
              .sort((a, b) => b.range - a.range)
              .slice(0, 12)
              .forEach(({el, range}) => {
                  const step = Math.max(200, Math.floor(el.clientHeight / 3));
                  for (let pos = 0; pos <= range; pos += step) {
                      el.scrollTop = pos;
                  }
                  el.scrollTop = range;
              });
        }"""
    )
    page.wait_for_timeout(1500)


def scalar_fields(obj: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}

    for key, value in obj.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            text = clean(value)
            result[str(key)] = text[:500]

    return result


def own_scalar_text(obj: dict[str, Any]) -> str:
    return " | ".join(
        clean(value)
        for value in obj.values()
        if isinstance(value, (str, int, float, bool))
    ).lower()


def has_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in KEYWORDS)


def walk_json(
    node: Any,
    path: str,
    object_hits: list[dict[str, Any]],
    string_hits: list[dict[str, Any]],
) -> None:
    if isinstance(node, dict):
        own_text = own_scalar_text(node)

        if own_text and has_keyword(own_text):
            object_hits.append(
                {
                    "path": path,
                    "keys": list(node.keys()),
                    "scalar_fields": scalar_fields(node),
                    "raw_object": node,
                }
            )

        for key, value in node.items():
            walk_json(
                value,
                f"{path}.{key}",
                object_hits,
                string_hits,
            )

    elif isinstance(node, list):
        for index, value in enumerate(node):
            walk_json(
                value,
                f"{path}[{index}]",
                object_hits,
                string_hits,
            )

    elif isinstance(node, str):
        if has_keyword(node):
            string_hits.append(
                {
                    "path": path,
                    "value": clean(node),
                }
            )


def main() -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    event_url = load_event_url()
    captured: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            viewport={"width": 1700, "height": 1000},
        )
        page = context.new_page()

        def on_response(response) -> None:
            try:
                url = response.url

                if not any(bit in url for bit in RELEVANT_URL_BITS):
                    return

                if url in seen_urls:
                    return

                seen_urls.add(url)
                text = response.text()

                try:
                    payload = json.loads(text)
                except Exception:
                    payload = None

                captured.append(
                    {
                        "url": url,
                        "status": response.status,
                        "content_type": clean(
                            response.headers.get("content-type", "")
                        ),
                        "payload": payload,
                        "raw_text": text if payload is None else None,
                    }
                )
            except Exception:
                pass

        page.on("response", on_response)

        page.goto(
            event_url,
            wait_until="domcontentloaded",
            timeout=70000,
        )
        page.wait_for_timeout(6000)
        accept_cookies(page)
        expand_and_scroll(page)

        for control in (
            "Bet Builder",
            "Cards",
            "Player",
            "Popular",
        ):
            if click_text_control(page, control):
                expand_and_scroll(page)

        page.wait_for_timeout(3000)
        browser.close()

    all_object_hits: list[dict[str, Any]] = []
    all_string_hits: list[dict[str, Any]] = []
    response_summaries: list[dict[str, Any]] = []

    for index, item in enumerate(captured, 1):
        filename = f"response_{index:02d}_{slug(item['url'])[-100:]}.json"
        path = DEBUG_DIR / filename

        if item["payload"] is not None:
            path.write_text(
                json.dumps(
                    item["payload"],
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            object_hits: list[dict[str, Any]] = []
            string_hits: list[dict[str, Any]] = []
            walk_json(
                item["payload"],
                "$",
                object_hits,
                string_hits,
            )

            for hit in object_hits:
                hit["response_url"] = item["url"]
                hit["debug_file"] = filename

            for hit in string_hits:
                hit["response_url"] = item["url"]
                hit["debug_file"] = filename

            all_object_hits.extend(object_hits)
            all_string_hits.extend(string_hits)

            response_summaries.append(
                {
                    "url": item["url"],
                    "status": item["status"],
                    "debug_file": filename,
                    "object_hits": len(object_hits),
                    "string_hits": len(string_hits),
                }
            )
        else:
            txt_name = filename.replace(".json", ".txt")
            (DEBUG_DIR / txt_name).write_text(
                item["raw_text"] or "",
                encoding="utf-8",
                errors="replace",
            )
            response_summaries.append(
                {
                    "url": item["url"],
                    "status": item["status"],
                    "debug_file": txt_name,
                    "object_hits": 0,
                    "string_hits": 0,
                }
            )

    output = {
        "bookmaker": "BetVictor",
        "match": MATCH_NAME,
        "source_url": event_url,
        "responses": response_summaries,
        "card_object_hits": all_object_hits,
        "card_string_hits": all_string_hits,
    }

    OUT_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("BETVICTOR ECUADOR PLAYER-CARD API INSPECTION")
    print("=" * 78)
    print(f"Captured relevant API responses: {len(response_summaries)}")

    for response in response_summaries:
        print(
            f"  {response['status']} "
            f"objects={response['object_hits']} "
            f"strings={response['string_hits']} "
            f"{response['url']}"
        )

    print(f"\nSmallest card-related objects: {len(all_object_hits)}")

    for index, hit in enumerate(all_object_hits[:80], 1):
        print(f"\n[{index}] {hit['path']}")
        for key, value in hit["scalar_fields"].items():
            print(f"  {key}: {value}")

    print(f"\nCard-related strings: {len(all_string_hits)}")
    for hit in all_string_hits[:100]:
        print(f"  {hit['path']}: {hit['value']}")

    print(f"\nSaved summary: {OUT_PATH}")
    print(f"Saved raw API JSON: {DEBUG_DIR}")
    print("No production JSON was modified.")


if __name__ == "__main__":
    main()
