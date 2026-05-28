"""Scrape de ficha individual (URL pegada) en Finca Raíz y Metrocuadrado."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from fincaraiz_daily_bot import (
    parse_area,
    parse_bathrooms,
    parse_bedrooms,
)
from scrapers.browser_utils import (
    ScrapeSession,
    brief_lazy_wait,
    goto_page,
    is_low_memory,
)
from scrapers.images import is_listing_image, normalize_image_url
from scrapers.admin_fee import parse_admin_fee, scrape_admin_fee_from_page
from propintel.transaction import detect_transaction_type
from scrapers.prices import extract_prices_from_text, pick_best_price

_JS_DETAIL_IMAGE = """
() => {
  const bad = (u) => !u || u.startsWith('data:') || /logo|icon|avatar|sprite|placeholder/i.test(u);
  const pick = (u) => (!bad(u) ? u : '');
  const og = document.querySelector('meta[property="og:image"]');
  if (og && og.content) return pick(og.content);
  const tw = document.querySelector('meta[name="twitter:image"]');
  if (tw && tw.content) return pick(tw.content);
  for (const img of document.querySelectorAll(
    '[class*="gallery"] img, [class*="Gallery"] img, [class*="carousel"] img, picture img, img'
  )) {
    for (const a of ['src', 'data-src', 'data-lazy-src', 'data-original']) {
      const v = img.getAttribute(a);
      if (pick(v)) return v;
    }
  }
  return '';
}
"""

SUPPORTED_PORTALS = ("fincaraiz", "metrocuadrado")


def normalize_listing_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if not raw.startswith("http"):
        raw = f"https://{raw}"
    return raw.split("?")[0].rstrip("/")


def detect_portal(url: str) -> Optional[str]:
    host = urlparse(normalize_listing_url(url)).netloc.lower()
    if "fincaraiz" in host:
        return "fincaraiz"
    if "metrocuadrado" in host:
        return "metrocuadrado"
    return None


def is_supported_url(url: str) -> bool:
    return detect_portal(url) is not None


def parse_urls_from_text(text: str) -> List[str]:
    found: List[str] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        for part in re.split(r"[\s,;]+", line.strip()):
            if not part or "http" not in part and "." not in part:
                continue
            url = normalize_listing_url(part)
            if not is_supported_url(url):
                continue
            key = url.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(url)
    return found


def _page_text(page) -> str:
    for sel in ("main", "[role='main']", "article", "#content"):
        loc = page.locator(sel).first
        if loc.count():
            try:
                text = loc.inner_text(timeout=3000)
                if text and len(text) > 120:
                    return text
            except Exception:
                pass
    return page.inner_text("body")


def _scrape_on_page(page, url: str) -> Dict[str, Any]:
    portal = detect_portal(url)
    goto_page(page, url)
    brief_lazy_wait(page)
    if not is_low_memory():
        page.wait_for_timeout(600)

    text = _page_text(page)
    title = ""
    for sel in ("h1", "[data-testid='title']", ".title"):
        loc = page.locator(sel).first
        if loc.count():
            try:
                title = (loc.inner_text(timeout=2000) or "").strip()[:200]
                if title:
                    break
            except Exception:
                pass
    if not title:
        match = re.search(
            r"(Apartamento|Casa)(?:\s+en\s+(?:venta|arriendo|alquiler))?[^.\n]{5,80}",
            text,
            re.IGNORECASE,
        )
        title = match.group(0).strip()[:200] if match else "Inmueble"

    image_url = ""
    if not is_low_memory():
        try:
            raw_img = page.evaluate(_JS_DETAIL_IMAGE)
            if raw_img and is_listing_image(str(raw_img)):
                image_url = normalize_image_url(str(raw_img))
        except Exception:
            pass
    if not image_url:
        try:
            og = page.locator("meta[property='og:image']").first
            if og.count():
                candidate = og.get_attribute("content") or ""
                if candidate and is_listing_image(candidate):
                    image_url = normalize_image_url(candidate)
        except Exception:
            pass

    txn = detect_transaction_type(url, title, text)
    candidates = [
        (r, v, c, False) for r, v, c in extract_prices_from_text(text, transaction_type=txn)
    ]
    price_raw, price = (
        pick_best_price(candidates, transaction_type=txn) if candidates else ("", None)
    )
    admin_fee = scrape_admin_fee_from_page(page) or parse_admin_fee(text)

    return {
        "portal": portal,
        "original_url": normalize_listing_url(url),
        "title": title,
        "price": price,
        "price_raw": price_raw,
        "admin_fee": admin_fee,
        "bedrooms": parse_bedrooms(text),
        "bathrooms": parse_bathrooms(text),
        "area_m2": parse_area(text),
        "image_url": image_url or None,
        "source_text": text[:2500],
        "transaction_type": txn,
    }


def scrape_listing_detail(url: str, *, session=None) -> Dict[str, Any]:
    url = normalize_listing_url(url)
    if not is_supported_url(url):
        raise ValueError("Solo enlaces de fincaraiz.com.co o metrocuadrado.com")

    if session is not None:
        return session.run_page(_scrape_on_page, url)

    with ScrapeSession() as sess:
        return sess.run_page(_scrape_on_page, url)


def scrape_listing_details(urls: List[str]) -> List[Tuple[str, Optional[Dict[str, Any]], Optional[str]]]:
    """Devuelve [(url, data, error), ...]."""
    results: List[Tuple[str, Optional[Dict[str, Any]], Optional[str]]] = []
    with ScrapeSession() as session:
        for url in urls:
            try:
                data = scrape_listing_detail(url, session=session)
                results.append((url, data, None))
            except Exception as exc:
                results.append((url, None, str(exc)))
    return results
