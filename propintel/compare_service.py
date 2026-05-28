"""Comparador por URLs (free 2 / premium 5)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from propintel.enrich import extract_neighborhood, external_id_from_url, fingerprint
from propintel.intel import TRANSIT_ZONES, compute_intel, detect_zone, maybe_enhance_with_openai
from propintel.repository import upsert_property
from propintel.transaction import detect_transaction_type
from scrapers.listing_detail import scrape_listing_details


def comparison_summary(properties: List[dict]) -> str:
    parts: List[str] = []
    for prop in properties:
        label = (prop.get("neighborhood") or prop.get("title") or "Inmueble").strip()
        if len(label) > 36:
            label = label[:33] + "…"
        parts.append(label)
    if len(parts) <= 3:
        return " · ".join(parts) if parts else "Comparación"
    return " · ".join(parts[:3]) + f" (+{len(parts) - 3})"


def compare_limit_for_user(user: Optional[dict], *, is_premium: bool) -> int:
    from propintel.config import COMPARE_LIMIT_FREE, COMPARE_LIMIT_PREMIUM

    if is_premium:
        return COMPARE_LIMIT_PREMIUM
    return COMPARE_LIMIT_FREE


def resolve_compare_transaction(
    urls: List[str],
    properties: List[dict],
    form_value: str = "",
) -> str:
    if form_value in ("compra", "arriendo"):
        return form_value
    for url in urls:
        if detect_transaction_type(url) == "arriendo":
            return "arriendo"
    for prop in properties:
        if prop.get("transaction_type") == "arriendo":
            return "arriendo"
    return "compra"


def _enrich_detail(data: dict, portal: str, transaction_type: str = "compra") -> dict[str, Any]:
    txn = transaction_type or detect_transaction_type(
        data.get("original_url", ""),
        data.get("title", ""),
        data.get("source_text", ""),
    )
    neighborhood = extract_neighborhood(
        data.get("location", ""),
        data.get("title", ""),
        data["original_url"],
    )
    intel = compute_intel(
        price=data.get("price"),
        area_m2=data.get("area_m2"),
        neighborhood=neighborhood,
        bedrooms=data.get("bedrooms"),
        portal=portal,
        transaction_type=txn,
    )
    analysis = maybe_enhance_with_openai(
        intel.analysis_text,
        data.get("title", ""),
        neighborhood,
    )
    return {
        "external_id": external_id_from_url(data["original_url"]),
        "portal": portal,
        "fingerprint": fingerprint(
            portal,
            data["original_url"],
            data.get("price"),
            data.get("area_m2"),
            data.get("title", ""),
            txn,
        ),
        "title": data.get("title"),
        "price": data.get("price"),
        "price_per_m2": intel.price_per_m2,
        "neighborhood": neighborhood,
        "locality": "Bogotá",
        "address_approx": neighborhood,
        "area_m2": data.get("area_m2"),
        "bedrooms": data.get("bedrooms"),
        "bathrooms": data.get("bathrooms"),
        "parking": None,
        "stratum": None,
        "admin_fee": data.get("admin_fee"),
        "description": data.get("source_text", "")[:2000],
        "score": intel.score,
        "valorization_pct": intel.valorization_pct,
        "analysis_text": analysis,
        "score_label": intel.score_label,
        "original_url": data["original_url"],
        "published_at": None,
        "image_url": data.get("image_url"),
        "transaction_type": txn,
        "vs_zone_pct": intel.vs_zone_pct,
    }


def valorization_tip(prop: dict, all_props: List[dict]) -> str:
    val = float(prop.get("valorization_pct") or 0)
    zone = prop.get("neighborhood") or detect_zone(
        f"{prop.get('title', '')} {prop.get('original_url', '')}"
    )
    zone_name = zone.capitalize() if zone != "bogota" else "Bogotá"
    vals = [float(p.get("valorization_pct") or 0) for p in all_props]
    is_top = len(all_props) > 1 and val >= max(vals) - 0.01

    if is_top:
        lead = (
            f"Mayor potencial de valorización en este grupo (~{val:.1f}% anual en {zone_name}). "
        )
    elif val >= 6:
        lead = f"Buena proyección de valorización (~{val:.1f}% anual en {zone_name}). "
    elif val >= 4.5:
        lead = f"Valorización moderada (~{val:.1f}% anual en {zone_name}). "
    else:
        lead = f"Valorización conservadora (~{val:.1f}% anual en {zone_name}). "

    admin = prop.get("admin_fee")
    if admin and prop.get("price"):
        ratio = (admin * 12) / prop["price"] * 100
        if ratio > 1.2:
            lead += "La administración pesa en el costo total; negocia o compara con opciones más bajas. "
        else:
            lead += "Administración razonable frente al precio de compra. "

    score = prop.get("score") or 0
    if score >= 70:
        lead += "Score de inversión favorable para compra."
    elif score >= 50:
        lead += "Revisa precio/m² frente a similares en la zona."
    else:
        lead += "Precio por encima del mercado; conviene negociar."
    return lead.strip()


def rental_compare_tip(prop: dict, all_props: List[dict]) -> str:
    zone = prop.get("neighborhood") or detect_zone(
        f"{prop.get('title', '')} {prop.get('original_url', '')}"
    )
    zone_name = zone.capitalize() if zone != "bogota" else "Bogotá"
    price = prop.get("price")
    ppm2 = prop.get("price_per_m2")
    vs = prop.get("vs_zone_pct")
    rents = [p.get("price") for p in all_props if p.get("price")]
    parts: List[str] = []

    if price and len(rents) > 1 and price == min(rents):
        parts.append(f"Canon mensual más bajo del grupo en {zone_name}.")
    elif price and len(rents) > 1:
        parts.append("Canon mensual competitivo frente a las otras opciones.")

    if ppm2 and vs is not None:
        if vs <= -10:
            parts.append(
                f"Precio por m² por debajo del promedio de arriendo en la zona (~{abs(vs):.0f}%)."
            )
        elif vs >= 12:
            parts.append(f"Precio por m² alto para {zone_name}; conviene negociar.")
        else:
            parts.append(f"Precio por m² alineado con el mercado de arriendo en {zone_name}.")
    elif ppm2:
        parts.append(f"Canon por m²: ${ppm2:,.0f}/m².".replace(",", "."))

    parts.append(f"Ubicación: {zone_name}.")
    if zone in TRANSIT_ZONES:
        parts.append("Zona con buena conectividad y servicios.")

    admin = prop.get("admin_fee")
    if admin:
        parts.append(f"Administración adicional: ${admin:,.0f}/mes.".replace(",", "."))

    score = prop.get("score") or 0
    if score >= 70:
        parts.append("Relación precio-ubicación favorable para arrendar.")
    elif score < 45:
        parts.append("Canon elevado respecto al mercado; revisa alternativas.")
    return " ".join(parts)


def attach_compare_tips(properties: List[dict], transaction_type: str = "compra") -> List[dict]:
    txn = transaction_type or (properties[0].get("transaction_type") if properties else "compra")
    for prop in properties:
        if txn == "arriendo":
            prop["compare_tip"] = rental_compare_tip(prop, properties)
        else:
            prop["compare_tip"] = valorization_tip(prop, properties)
    return properties


def compare_from_urls(
    urls: List[str],
    *,
    persist: bool = True,
    transaction_type: str = "compra",
) -> Tuple[List[dict], Dict[str, str]]:
    errors: Dict[str, str] = {}
    properties: List[dict] = []
    txn = resolve_compare_transaction(urls, [], transaction_type)

    scraped = scrape_listing_details(urls)
    for url, data, err in scraped:
        if err or not data:
            errors[url] = err or "No se pudo leer el inmueble"
            continue
        portal = data.get("portal") or "fincaraiz"
        item_txn = detect_transaction_type(
            url, data.get("title", ""), data.get("source_text", "")
        )
        if item_txn == "arriendo":
            txn = "arriendo"
        payload = _enrich_detail(data, portal, item_txn or txn)
        if persist:
            stored = upsert_property(payload)
            row = stored if stored else payload
        else:
            row = payload
        properties.append(row)

    final_txn = resolve_compare_transaction(urls, properties, transaction_type)
    return attach_compare_tips(properties, final_txn), errors


def merge_properties_by_ids(
    ids: List[int],
    url_props: List[dict],
    transaction_type: str = "compra",
) -> List[dict]:
    from propintel.repository import get_properties_by_ids

    by_id = {p["id"]: p for p in get_properties_by_ids(ids)}
    ordered: List[dict] = []
    seen_urls: set[str] = set()
    for pid in ids:
        if pid in by_id:
            ordered.append(by_id[pid])
            seen_urls.add((by_id[pid].get("original_url") or "").lower())
    for prop in url_props:
        url_key = (prop.get("original_url") or "").lower()
        if url_key and url_key not in seen_urls:
            ordered.append(prop)
            seen_urls.add(url_key)
    txn = resolve_compare_transaction([], ordered, transaction_type)
    return attach_compare_tips(ordered, txn)
