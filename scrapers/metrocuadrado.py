"""Scraper de listados públicos en Metrocuadrado (Bogotá)."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from fincaraiz_daily_bot import (
    Listing,
    extract_card_text,
    extract_price_text,
    normalize_text,
    parse_area,
    parse_bathrooms,
    parse_bedrooms,
    parse_price_value,
)
from scrapers.browser_utils import (
    chromium_launch_kwargs,
    ensure_listing_cards,
    goto_page,
    is_low_memory,
    new_browser_context,
    page_default_timeout,
    scroll_pause_ms,
    scroll_rounds_default,
)
from scrapers.images import collect_listing_images, extract_card_image, lookup_image
from scrapers.prices import collect_listing_prices, lookup_price
from search_query import KNOWN_ZONES, SearchCriteria

BASE_URL = "https://www.metrocuadrado.com"
DEFAULT_URL = f"{BASE_URL}/apartamentos/venta/bogota/"

LISTING_LINK_SELECTOR = "a[href*='/inmueble/']"

# Zonas con URL directa en Metrocuadrado
ZONE_SCRAPE_URLS: dict[str, str] = {
    "chapinero": f"{BASE_URL}/apartamentos/venta/bogota/chapinero/",
    "teusaquillo": f"{BASE_URL}/apartamentos/venta/bogota/teusaquillo/",
    "usaquen": f"{BASE_URL}/apartamentos/venta/bogota/usaquen/",
    "cedritos": f"{BASE_URL}/apartamentos/venta/bogota/cedritos/",
    "suba": f"{BASE_URL}/apartamentos/venta/bogota/suba/",
    "fontibon": f"{BASE_URL}/apartamentos/venta/bogota/fontibon/",
    "kennedy": f"{BASE_URL}/apartamentos/venta/bogota/kennedy/",
    "modelia": f"{BASE_URL}/apartamentos/venta/bogota/modelia/",
    "engativa": f"{BASE_URL}/apartamentos/venta/bogota/engativa/",
}

# Ciudades enlazadas en footer que no son Bogotá
FOOTER_CITY_MARKERS = (
    "/medellin/",
    "/cali/",
    "/barranquilla/",
    "/bucaramanga/",
    "/cartagena/",
    "/pereira/",
    "/manizales/",
)


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def absolute_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url.split("?")[0] if "?" in url else url
    joined = urljoin(BASE_URL, url)
    return joined.split("?")[0]


def is_property_listing_href(href: str) -> bool:
    if not href:
        return False
    lowered = href.lower().split("?")[0]
    if "/inmueble/" not in lowered:
        return False
    if any(marker in lowered for marker in FOOTER_CITY_MARKERS):
        return False
    if "bogota" not in lowered and "bogot" not in lowered:
        return False
    return bool(
        re.search(r"venta-(?:apartamento|casa)-", lowered)
        or re.search(r"/inmueble/[^/]+/\d", lowered)
        or re.search(r"/inmueble/[^/]+/M[C]?\d", lowered, re.IGNORECASE)
    )


def parse_bedrooms_from_url(url: str) -> Optional[int]:
    match = re.search(r"(\d+)-habitaciones?", url, re.IGNORECASE)
    return int(match.group(1)) if match else None


def parse_bathrooms_from_url(url: str) -> Optional[int]:
    match = re.search(r"(\d+)-banos?", url, re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_location_metro(card_text: str, href: str) -> str:
    match = re.search(
        r"Apartamento en Venta,\s*([^,|]+)",
        card_text,
        re.IGNORECASE,
    )
    if match:
        return normalize_text(match.group(1))
    match = re.search(r"\|\s*([^|]+)\s*\|\s*Bogot", card_text, re.IGNORECASE)
    if match:
        return normalize_text(match.group(1))
    slug = urlparse(href).path
    parts = slug.split("-")
    if "bogota" in parts:
        idx = parts.index("bogota")
        if idx + 1 < len(parts):
            return normalize_text(parts[idx + 1].replace("-", " "))
    return ""


def extract_title_metro(card_text: str, href: str) -> str:
    lines = [normalize_text(line) for line in card_text.split("\n") if line.strip()]
    for line in lines:
        if "Apartamento en Venta" in line or "Casa en Venta" in line:
            return line[:120]
        if "| Chapinero |" in line or "| Bogot" in line:
            return line[:120]
    slug = urlparse(href).path.replace("/inmueble/", "")
    return normalize_text(slug.replace("-", " "))[:120]


def urls_for_criteria(criteria: SearchCriteria) -> List[str]:
    segment = "casas" if criteria.property_type == "casa" else "apartamentos"
    if not criteria.zones:
        if segment == "casas":
            return [f"{BASE_URL}/casas/venta/bogota/"]
        return [DEFAULT_URL]

    urls: List[str] = []
    for zone in criteria.zones:
        base = ZONE_SCRAPE_URLS.get(zone)
        if base:
            if segment == "casas":
                urls.append(base.replace("/apartamentos/", "/casas/"))
            else:
                urls.append(base)
        else:
            urls.append(f"{BASE_URL}/{segment}/venta/bogota/{zone}/")
    return list(dict.fromkeys(urls))


def dismiss_cookie_banner(page) -> None:
    for sel in [
        "#onetrust-accept-btn-handler",
        "button:has-text('Aceptar')",
        "button:has-text('ACEPTAR')",
    ]:
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible(timeout=600):
                btn.click(timeout=1500)
                return
        except Exception:
            continue


def scroll_to_load_cards(page, rounds: int | None = None, min_links: int = 0) -> None:
    if rounds is None:
        rounds = scroll_rounds_default()
    pause = scroll_pause_ms()
    for _ in range(rounds):
        if min_links and page.locator(LISTING_LINK_SELECTOR).count() >= min_links:
            return
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(pause)


def _scrape_url_on_page(page, url: str, max_listings: int) -> List[Listing]:
    today = date.today().isoformat()
    rows: List[Listing] = []

    goto_page(page, url)
    dismiss_cookie_banner(page)

    link_count = ensure_listing_cards(page, LISTING_LINK_SELECTOR)
    if link_count == 0:
        return []

    if link_count < max_listings:
        scroll_to_load_cards(page, min_links=max_listings)
    img_map = collect_listing_images(page, LISTING_LINK_SELECTOR, BASE_URL)
    price_map = collect_listing_prices(page, LISTING_LINK_SELECTOR)

    link_nodes = page.locator(LISTING_LINK_SELECTOR)
    seen: Set[str] = set()

    for i in range(min(link_nodes.count(), max_listings * 3)):
        if len(rows) >= max_listings:
            break
        anchor = link_nodes.nth(i)
        href = anchor.get_attribute("href") or ""
        if not is_property_listing_href(href):
            continue
        listing_url = absolute_url(href)
        if not listing_url or listing_url in seen:
            continue
        seen.add(listing_url)

        card_text = extract_card_text(anchor)
        price_raw, price_value = lookup_price(
            price_map, listing_url, anchor=anchor, card_text=card_text
        )
        bedrooms = parse_bedrooms(card_text) or parse_bedrooms_from_url(href)
        bathrooms = parse_bathrooms(card_text) or parse_bathrooms_from_url(href)

        row = Listing(
            run_date=today,
            listing_url=listing_url,
            title=extract_title_metro(card_text, href),
            price_raw=price_raw,
            price_value=price_value,
            location=extract_location_metro(card_text, href),
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            area_m2=parse_area(card_text),
            source_text=card_text[:1200],
            image_url=lookup_image(img_map, listing_url, BASE_URL)
            or extract_card_image(anchor, BASE_URL),
        )
        rows.append(row)

    return rows


def scrape_url(url: str, max_listings: int = 40, *, session=None) -> List[Listing]:
    if session is not None:
        return session.run_page(_scrape_url_on_page, url, max_listings)

    with sync_playwright() as p:
        browser = p.chromium.launch(**chromium_launch_kwargs())
        context = new_browser_context(browser)
        page = context.new_page()
        page.set_default_timeout(page_default_timeout())
        rows = _scrape_url_on_page(page, url, max_listings)
        browser.close()
    return rows


def listing_matches_metro(listing: Listing, criteria: SearchCriteria) -> bool:
    """Filtro adaptado: habitaciones y tipo también en la URL de Metrocuadrado."""
    url_lower = listing.listing_url.lower()
    blob = strip_accents(
        f"{listing.title} {listing.location} {listing.source_text} {listing.listing_url}".lower()
    )

    if criteria.property_type == "casa":
        if "venta-casa" not in url_lower and "casa" not in blob:
            return False
    if criteria.property_type == "apartamento" and "venta-casa" in url_lower:
        return False

    if criteria.bedrooms is not None:
        beds = listing.bedrooms or parse_bedrooms_from_url(listing.listing_url)
        if beds is not None and beds != criteria.bedrooms:
            return False
        if beds is None:
            if f"{criteria.bedrooms}-habitacion" in blob or re.search(
                rf"\b{criteria.bedrooms}\s*hab", blob
            ):
                pass
            # Sin dato en tarjeta: no descartar

    if criteria.zones:
        if not any(
            zone in blob or any(kw in blob for kw in KNOWN_ZONES.get(zone, [zone]))
            for zone in criteria.zones
        ):
            return False

    return True


def search_listings(criteria: SearchCriteria, limit: int = 5, *, session=None) -> List[Listing]:
    """Busca en Metrocuadrado según criterios; devuelve hasta ``limit`` resultados."""
    effective = SearchCriteria(
        bedrooms=criteria.bedrooms,
        zones=criteria.zones,
        property_type=criteria.property_type,
        max_results=limit,
    )

    collected: List[Listing] = []
    seen: Set[str] = set()

    urls = urls_for_criteria(effective)
    if is_low_memory():
        urls = urls[:1]

    max_per_url = min(limit + 10, 25)
    harvest_cap = max_per_url * len(urls)
    for url in urls:
        for listing in scrape_url(url, max_listings=max_per_url, session=session):
            if listing.listing_url in seen:
                continue
            seen.add(listing.listing_url)
            collected.append(listing)
            if len(collected) >= harvest_cap:
                break
        if len(collected) >= harvest_cap:
            break

    matched = [item for item in collected if listing_matches_metro(item, effective)]
    if matched:
        return matched[:limit]
    return collected[:limit]
