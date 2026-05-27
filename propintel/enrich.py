"""Convierte listados scrapeados a propiedades enriquecidas."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from propintel.intel import compute_intel, detect_zone, maybe_enhance_with_openai


def external_id_from_url(url: str) -> str:
    path = url.rstrip("/").split("/")[-1]
    return path or hashlib.md5(url.encode()).hexdigest()[:16]


def fingerprint(portal: str, url: str, price: Optional[int], area: Optional[float], title: str) -> str:
    price_bucket = (price or 0) // 1_000_000
    area_bucket = int(area or 0)
    raw = f"{portal}|{price_bucket}|{area_bucket}|{title[:60].lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def extract_neighborhood(location: str, title: str, url: str) -> str:
    blob = f"{location} {title} {url}".lower()
    zone = detect_zone(blob)
    if zone != "bogota":
        return zone.capitalize()
    if location:
        return location.split(",")[0].strip()
    return "Bogotá"


def extract_parking(text: str, url: str) -> Optional[int]:
    blob = f"{text} {url}".lower()
    match = re.search(r"(\d+)\s*garajes?", blob)
    if match:
        return int(match.group(1))
    if "sin garaje" in blob or "0-garajes" in blob:
        return 0
    if "garaje" in blob or "parqueadero" in blob:
        return 1
    return None


def extract_stratum(text: str) -> Optional[int]:
    match = re.search(r"estrato\s*(\d)", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def listing_to_property_dict(listing: Any, portal: str) -> dict:
    price = getattr(listing, "price_value", None)
    area = getattr(listing, "area_m2", None)
    title = getattr(listing, "title", "") or "Inmueble"
    location = getattr(listing, "location", "") or ""
    url = getattr(listing, "listing_url", "") or ""
    source = getattr(listing, "source_text", "") or ""

    neighborhood = extract_neighborhood(location, title, url)
    intel = compute_intel(
        price=price,
        area_m2=area,
        neighborhood=neighborhood,
        bedrooms=getattr(listing, "bedrooms", None),
        portal=portal,
    )
    analysis = maybe_enhance_with_openai(intel.analysis_text, title, neighborhood)

    return {
        "external_id": external_id_from_url(url),
        "portal": portal,
        "fingerprint": fingerprint(portal, url, price, area, title),
        "title": title,
        "price": price,
        "price_per_m2": intel.price_per_m2,
        "neighborhood": neighborhood,
        "locality": "Bogotá",
        "address_approx": location or neighborhood,
        "area_m2": area,
        "bedrooms": getattr(listing, "bedrooms", None),
        "bathrooms": getattr(listing, "bathrooms", None),
        "parking": extract_parking(source, url),
        "stratum": extract_stratum(source),
        "admin_fee": None,
        "description": source[:2000] if source else None,
        "score": intel.score,
        "valorization_pct": intel.valorization_pct,
        "analysis_text": analysis,
        "score_label": intel.score_label,
        "original_url": url,
        "published_at": getattr(listing, "run_date", None),
        "image_url": getattr(listing, "image_url", None) or None,
        "transaction_type": "compra",
    }
