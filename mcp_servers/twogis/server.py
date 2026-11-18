"""2GIS MCP server — Playwright scrapes 2gis.kz restaurant search."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from mcp.server import MCPServer
from playwright.sync_api import sync_playwright

mcp = MCPServer("2gis-almaty")

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".cache" / "twogis"
CACHE_TTL_SEC = 600
CITY_SLUG = {"алматы": "almaty", "almaty": "almaty", "астана": "astana", "astana": "astana"}


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() else "_" for c in key)[:80]
    return CACHE_DIR / f"{safe}.json"


def _read_cache(key: str, allow_stale: bool = False) -> list[dict[str, Any]] | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    if not allow_stale and time.time() - path.stat().st_mtime > CACHE_TTL_SEC:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(key: str, data: list[dict[str, Any]]) -> None:
    _cache_path(key).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_catalog_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("result", {}).get("items") or payload.get("items") or []
    restaurants: list[dict[str, Any]] = []
    for item in items[:12]:
        if not isinstance(item, dict):
            continue
        address_obj = item.get("address") or {}
        address = address_obj.get("name") or item.get("address_name") or ""
        reviews = item.get("reviews") or {}
        rating = reviews.get("rating") or item.get("rating") or 0
        schedule = item.get("schedule") or {}
        hours = schedule.get("comment") or schedule.get("description") or ""
        if not hours and isinstance(schedule.get("Mon"), dict):
            hours = json.dumps(schedule, ensure_ascii=False)[:120]
        contact = ""
        for contact_item in item.get("contact_groups") or []:
            for c in contact_item.get("contacts") or []:
                if c.get("type") in {"phone", "phone_internal"} or c.get("text"):
                    contact = c.get("text") or c.get("value") or contact
        rubrics = item.get("rubrics") or []
        cuisine = ", ".join(r.get("name", "") for r in rubrics if r.get("name"))[:80]
        restaurants.append(
            {
                "name": item.get("name") or "",
                "address": address,
                "rating": float(rating) if rating else 0.0,
                "price_range": str(item.get("ads", {}).get("article") or item.get("attribute_groups", "") or ""),
                "cuisine": cuisine or "ресторан",
                "working_hours": hours,
                "phone": contact,
            }
        )
    return restaurants


def _scrape_dom(page) -> list[dict[str, Any]]:
    cards = page.locator("a[href*='/firm/'], a[href*='/geo/']").all()[:20]
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for card in cards:
        try:
            text = card.inner_text(timeout=1000).strip()
        except Exception:
            continue
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            continue
        name = lines[0]
        if name in seen or len(name) < 2:
            continue
        seen.add(name)
        results.append(
            {
                "name": name,
                "address": next((ln for ln in lines[1:] if any(ch.isdigit() for ch in ln)), ""),
                "rating": 0.0,
                "price_range": "",
                "cuisine": "ресторан",
                "working_hours": "",
                "phone": "",
            }
        )
        if len(results) >= 10:
            break
    return results


@mcp.tool()
def search_restaurants(query: str, location: str = "Алматы") -> list[dict[str, Any]]:
    """Search restaurants, cafes and bars on 2GIS for a city (default Almaty)."""
    cache_key = f"{location}:{query}"
    cached = _read_cache(cache_key)
    if cached:
        return cached

    try:
        results = _scrape(query, location)
    except Exception as exc:
        stale = _read_cache(cache_key, allow_stale=True)
        if stale:
            return stale
        return [{"error": f"2GIS недоступен: {exc}. Попробуйте позже."}]

    if not results:
        stale = _read_cache(cache_key, allow_stale=True)
        if stale:
            return stale
    _write_cache(cache_key, results)
    return results


def _scrape(query: str, location: str) -> list[dict[str, Any]]:
    city = CITY_SLUG.get(location.strip().lower(), "almaty")
    url = f"https://2gis.kz/{city}/search/{quote(query)}"
    captured: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            locale="ru-RU",
            timezone_id="Asia/Almaty",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        time.sleep(0.8)

        def on_response(response):
            try:
                u = response.url
                if "catalog.api.2gis" in u and response.status == 200:
                    data = response.json()
                    parsed = _parse_catalog_items(data)
                    if parsed:
                        captured.extend(parsed)
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(5000)
        body = page.inner_text("body")[:400]
        if "Captcha" in page.title() or "подозрительную активность" in body:
            browser.close()
            # Raise so the caller can fall back to stale cache instead of
            # caching a useless captcha notice for 10 minutes.
            raise RuntimeError("2GIS показал captcha — откройте 2gis.kz в браузере на этом IP и повторите")
        if not captured:
            captured.extend(_scrape_dom(page))
        browser.close()

    # de-dupe by name
    uniq: dict[str, dict[str, Any]] = {}
    for row in captured:
        name = row.get("name") or ""
        if name and name not in uniq:
            uniq[name] = row
    return list(uniq.values())[:10]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
