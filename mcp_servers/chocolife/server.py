"""Chocolife MCP server — Playwright scrapes restaurant deals."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from mcp.server import MCPServer
from playwright.sync_api import sync_playwright

mcp = MCPServer("chocolife-deals")

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".cache" / "chocolife"
CACHE_TTL_SEC = 600
BASE = "https://chocolife.me"
CATALOG = f"{BASE}/restorany-kafe-i-bary/"


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


def _parse_prices(text: str) -> tuple[int, int, int]:
    nums = [int(x.replace(" ", "")) for x in re.findall(r"(\d[\d\s]{1,8})\s*₸", text)]
    pct = re.search(r"(\d{1,2})\s*%", text)
    discount_percent = int(pct.group(1)) if pct else 0
    original, discount = 0, 0
    if len(nums) >= 2:
        original, discount = max(nums[:2]), min(nums[:2])
    elif len(nums) == 1:
        discount = nums[0]
        if discount_percent:
            original = int(discount / max(1 - discount_percent / 100, 0.01))
    return original, discount, discount_percent


@mcp.tool()
def search_deals(category: str = "рестораны", city: str = "Алматы") -> list[dict[str, Any]]:
    """Search Chocolife restaurant/cafe/bar deals and coupons (Almaty catalog)."""
    cache_key = f"{city}:{category}"
    cached = _read_cache(cache_key)
    if cached:
        return cached

    try:
        deals = _scrape()
    except Exception as exc:
        # Site slow/unreachable: stale data beats no data.
        stale = _read_cache(cache_key, allow_stale=True)
        if stale:
            return stale
        return [{"error": f"Chocolife недоступен: {exc}. Попробуйте позже."}]

    if not deals:
        stale = _read_cache(cache_key, allow_stale=True)
        if stale:
            return stale
    _write_cache(cache_key, deals)
    return deals


def _scrape() -> list[dict[str, Any]]:
    deals: list[dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        time.sleep(0.8)
        page.goto(CATALOG, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)

        links = page.locator("a[href*='/deal/'], a[href*='/offers/'], a[href*='/aktsii/']")
        hrefs: list[str] = []
        for i in range(min(links.count(), 24)):
            href = links.nth(i).get_attribute("href") or ""
            if href:
                hrefs.append(urljoin(BASE, href))

        # Fallback: any offer-like cards
        if not hrefs:
            cards = page.locator("article, .deal, .offer, [class*='Deal'], [class*='offer']")
            for i in range(min(cards.count(), 12)):
                el = cards.nth(i)
                text = el.inner_text()
                orig, disc, pct = _parse_prices(text)
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                rest = next((ln for ln in lines if "·" in ln or any(k in ln.lower() for k in ("кафе", "бар", "ресторан", "house", "мята"))), "")
                rest = rest.split("·")[0].strip() if rest else (lines[2] if len(lines) > 2 else (lines[0] if lines else "Заведение"))
                title = next((ln for ln in lines if "скидк" in ln.lower() or "меню" in ln.lower() or "завтрак" in ln.lower()), lines[0] if lines else "Акция")
                deals.append(
                    {
                        "title": title[:160],
                        "restaurant_name": rest[:80],
                        "original_price": orig,
                        "discount_price": disc,
                        "discount_percent": pct,
                        "description": text[:400],
                        "url": CATALOG,
                    }
                )
        else:
            seen: set[str] = set()
            for href in hrefs:
                if href in seen:
                    continue
                seen.add(href)
                try:
                    card = page.locator(f"a[href='{href.replace(BASE, '')}'], a[href='{href}']").first
                    text = card.inner_text(timeout=1500)
                except Exception:
                    text = href
                orig, disc, pct = _parse_prices(text)
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                rest = next((ln.split("·")[0].strip() for ln in lines if "·" in ln), "")
                title = next((ln for ln in lines if "скидк" in ln.lower() or "меню" in ln.lower()), lines[0] if lines else "Акция Chocolife")
                if not rest:
                    rest = lines[-2] if len(lines) > 2 else title
                deals.append(
                    {
                        "title": title[:160],
                        "restaurant_name": rest[:80],
                        "original_price": orig,
                        "discount_price": disc,
                        "discount_percent": pct,
                        "description": text[:400],
                        "url": href,
                    }
                )
                if len(deals) >= 10:
                    break
        browser.close()
    return deals


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
