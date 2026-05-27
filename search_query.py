"""Parseo de consultas en lenguaje natural y filtrado de inmuebles."""
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Set

from fincaraiz_daily_bot import Listing, TARGET_URL, normalize_text, scrape_listings

# Palabras clave -> zonas internas
KNOWN_ZONES = {
    "teusaquillo": ["teusaquillo"],
    "chapinero": ["chapinero"],
    "usaquen": ["usaquen", "usaquén"],
    "cedritos": ["cedritos"],
    "suba": ["suba"],
    "fontibon": ["fontibon", "fontibón"],
    "kennedy": ["kennedy"],
    "modelia": ["modelia"],
    "engativa": ["engativa", "engativá"],
}

# URLs de listados por zona (FincaRaiz)
ZONE_SCRAPE_URLS = {
    "teusaquillo": [
        "https://www.fincaraiz.com.co/venta/apartamentos/bogota/bogota-dc",
    ],
    "chapinero": [
        "https://www.fincaraiz.com.co/venta/apartamentos/chapinero-central/zona-chapinero/bogota",
        "https://www.fincaraiz.com.co/venta/apartamentos/chapinero-alto/zona-chapinero/bogota",
        "https://www.fincaraiz.com.co/venta/apartamentos/chapinero-central/bogota",
    ],
    "usaquen": [
        "https://www.fincaraiz.com.co/venta/apartamentos/usaquen/bogota",
    ],
    "cedritos": [
        "https://www.fincaraiz.com.co/venta/apartamentos/cedritos/zona-norte/bogota",
    ],
    "suba": [
        "https://www.fincaraiz.com.co/venta/apartamentos/suba/bogota",
    ],
}


@dataclass
class SearchCriteria:
    bedrooms: Optional[int] = None
    zones: List[str] = field(default_factory=list)
    property_type: Optional[str] = None  # apartamento | casa
    max_results: int = 5


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def parse_search_query(text: str, max_results: int = 5) -> SearchCriteria:
    raw = normalize_text(text)
    lowered = strip_accents(raw.lower())

    bedrooms = None
    bed_match = re.search(r"(\d+)\s*(?:hab(?:itaciones?)?|cuartos?|dormitorios?)", lowered)
    if bed_match:
        bedrooms = int(bed_match.group(1))

    property_type = None
    if re.search(r"\b(apartamento|apto|apartamentos)\b", lowered):
        property_type = "apartamento"
    elif re.search(r"\b(casa|casas)\b", lowered):
        property_type = "casa"

    zones: List[str] = []
    for zone_key, keywords in KNOWN_ZONES.items():
        if any(kw in lowered for kw in keywords):
            zones.append(zone_key)

    return SearchCriteria(
        bedrooms=bedrooms,
        zones=zones,
        property_type=property_type,
        max_results=max_results,
    )


def listing_blob(listing: Listing) -> str:
    return strip_accents(
        f"{listing.title} {listing.location} {listing.source_text} {listing.listing_url}".lower()
    )


def listing_matches_zone(listing: Listing, zone_keys: List[str]) -> bool:
    if not zone_keys:
        return True
    if listing_from_zone_urls(listing, zone_keys):
        return True
    blob = listing_blob(listing)
    for zone in zone_keys:
        keywords = KNOWN_ZONES.get(zone, [zone])
        if any(kw in blob for kw in keywords):
            return True
    return False


def listing_matches_bedrooms(listing: Listing, bedrooms: int) -> bool:
    if listing.bedrooms is not None:
        return listing.bedrooms == bedrooms
    blob = listing_blob(listing)
    patterns = [
        rf"\b{bedrooms}\s*habs?\.",
        rf"\b{bedrooms}\s*hab(?:itaciones?)?\b",
        rf"unidades desde:\s*{bedrooms}\s*hab",
        rf"{bedrooms}\s*habitacion",
    ]
    if any(re.search(p, blob) for p in patterns):
        return True
    # Sin dato de habitaciones en la tarjeta: no descartar (el portal sí tiene el dato)
    return True


def listing_from_zone_urls(listing: Listing, zone_keys: List[str]) -> bool:
    if not zone_keys:
        return False
    url = strip_accents(listing.listing_url.lower())
    for zone in zone_keys:
        if zone in url:
            return True
        for kw in KNOWN_ZONES.get(zone, [zone]):
            if kw in url:
                return True
    return False


def listing_matches_type(listing: Listing, property_type: str) -> bool:
    url = listing.listing_url.lower()
    blob = listing_blob(listing)
    if property_type == "apartamento":
        if "-casa-en-venta-" in url and "apartamento" not in url:
            return False
        return "apartamento" in url or "apartamento" in blob or "/proyectos-vivienda/" in url
    if property_type == "casa":
        return "casa" in url or "casa" in blob
    return True


def listing_matches(listing: Listing, criteria: SearchCriteria) -> bool:
    if criteria.property_type and not listing_matches_type(listing, criteria.property_type):
        return False
    if criteria.bedrooms is not None and not listing_matches_bedrooms(listing, criteria.bedrooms):
        return False
    if not listing_matches_zone(listing, criteria.zones):
        return False
    return True


def scrape_urls_for_criteria(criteria: SearchCriteria) -> List[str]:
    if not criteria.zones:
        return [TARGET_URL]
    urls: List[str] = []
    for zone in criteria.zones:
        urls.extend(ZONE_SCRAPE_URLS.get(zone, [TARGET_URL]))
    urls = list(dict.fromkeys(urls))
    try:
        from scrapers.browser_utils import is_low_memory

        if is_low_memory():
            return urls[:1]
    except ImportError:
        pass
    return urls


def search_listings(
    criteria: SearchCriteria,
    pages_per_url: int | None = None,
    *,
    session=None,
) -> List[Listing]:
    if pages_per_url is None:
        try:
            from scrapers.browser_utils import is_low_memory

            pages_per_url = 1 if is_low_memory() else 2
        except ImportError:
            pages_per_url = 2
    urls = scrape_urls_for_criteria(criteria)
    collected: List[Listing] = []
    seen: Set[str] = set()

    harvest_cap = max(criteria.max_results * 4, 20)
    max_per_url = min(harvest_cap, 30)
    for url in urls:
        for listing in scrape_listings(
            url,
            pages_per_url,
            session=session,
            max_listings=max_per_url,
        ):
            if listing.listing_url in seen:
                continue
            seen.add(listing.listing_url)
            collected.append(listing)
            if len(collected) >= harvest_cap:
                break
        if len(collected) >= harvest_cap:
            break

    matched = [item for item in collected if listing_matches(item, criteria)]
    if matched:
        return matched[: criteria.max_results]

    # Fallback: misma zona / tipo aunque el filtro de texto sea estricto
    if collected and criteria.zones:
        zone_only = [
            item
            for item in collected
            if listing_matches_zone(item, criteria.zones)
            and (not criteria.property_type or listing_matches_type(item, criteria.property_type))
        ]
        if zone_only:
            return zone_only[: criteria.max_results]

    if collected:
        return collected[: criteria.max_results]

    return []


def format_criteria_summary(criteria: SearchCriteria) -> str:
    parts = []
    if criteria.property_type:
        parts.append(criteria.property_type)
    if criteria.bedrooms is not None:
        parts.append(f"{criteria.bedrooms} hab")
    if criteria.zones:
        parts.append(" o ".join(criteria.zones))
    return ", ".join(parts) if parts else "sin filtros claros"


def format_listing_result(index: int, listing: Listing) -> str:
    hab = f"{listing.bedrooms} hab" if listing.bedrooms else "hab: N/D"
    banos = f"{listing.bathrooms} ba" if listing.bathrooms else ""
    area = f"{listing.area_m2:g} m2" if listing.area_m2 else ""
    extras = " | ".join(x for x in [hab, banos, area] if x)
    loc = listing.location or "ubicacion no indicada"
    price = listing.price_raw or "precio no indicado"
    title = (listing.title or "Inmueble")[:90]
    return (
        f"{index}. {title}\n"
        f"   {price} | {extras}\n"
        f"   {loc}\n"
        f"   {listing.listing_url}"
    )


def format_search_response(criteria: SearchCriteria, results: List[Listing]) -> str:
    summary = format_criteria_summary(criteria)
    if not results:
        return (
            f"No encontre inmuebles para: {summary}.\n\n"
            "Prueba ampliando zonas o quitando habitaciones exactas.\n"
            "Ejemplo: apartamento 2 habitaciones en chapinero o teusaquillo"
        )

    lines = [f"Top {len(results)} resultados ({summary}):", ""]
    for idx, listing in enumerate(results, start=1):
        lines.append(format_listing_result(idx, listing))
        lines.append("")
    return "\n".join(lines).strip()
