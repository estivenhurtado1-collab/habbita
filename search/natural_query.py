"""Interpretación de consultas en lenguaje natural (landing y bot)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

from search_query import KNOWN_ZONES, strip_accents


@dataclass
class ParsedQuery:
    raw: str
    intent: str = "search"  # search | compare
    transaction_type: str = "compra"
    property_type: str = "apartamento"
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    zones: List[str] = field(default_factory=list)
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    labels: List[str] = field(default_factory=list)
    txn_from_text: bool = False
    prop_from_text: bool = False

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "transaction_type": self.transaction_type,
            "property_type": self.property_type,
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "zones": self.zones,
            "price_min": self.price_min,
            "price_max": self.price_max,
            "labels": self.labels,
            "summary": " · ".join(self.labels) if self.labels else "",
        }


def _normalize(text: str) -> str:
    return strip_accents(re.sub(r"\s+", " ", (text or "").strip()).lower())


def _parse_money_token(raw: str, *, rent: bool) -> Optional[int]:
    text = (raw or "").strip().lower()
    dec = re.match(r"^(\d+)[.,](\d+)\s*(millones?|millon|m)?$", text)
    if dec:
        val = float(f"{dec.group(1)}.{dec.group(2)}")
        return int(val * 1_000_000)
    cleaned = text.replace(".", "").replace(",", "").replace(" ", "")
    m = re.match(r"^(\d+)(m|millones?|millon)?$", cleaned, re.I)
    if not m:
        return None
    val = int(m.group(1))
    suffix = (m.group(2) or "").lower()
    if suffix.startswith("m") or suffix.startswith("millon"):
        val *= 1_000_000
    elif rent and val < 100_000:
        val *= 1_000_000
    elif not rent and val < 10_000:
        val *= 1_000_000
    return val


def _parse_prices(text: str, rent: bool) -> tuple[Optional[int], Optional[int]]:
    lo, hi = None, None
    between = re.search(
        r"(?:entre|de)\s+\$?\s*([\d.,]+)\s*(?:millones?|m)?\s*(?:y|a|-)\s*\$?\s*([\d.,]+)\s*(?:millones?|m)?",
        text,
        re.I,
    )
    if between:
        lo = _parse_money_token(between.group(1), rent=rent)
        hi = _parse_money_token(between.group(2), rent=rent)
        return lo, hi

    for pat in (
        r"(?:hasta|maximo|max|menos de|bajo)\s+\$?\s*([\d.,]+)\s*(?:millones?|m)?",
        r"(?:presupuesto|canon|precio)\s+(?:de|max)?\s*\$?\s*([\d.,]+)\s*(?:millones?|m)?",
    ):
        m = re.search(pat, text, re.I)
        if m:
            hi = _parse_money_token(m.group(1), rent=rent)
            break

    for pat in (
        r"(?:desde|minimo|min|mas de|sobre)\s+\$?\s*([\d.,]+)\s*(?:millones?|m)?",
    ):
        m = re.search(pat, text, re.I)
        if m:
            lo = _parse_money_token(m.group(1), rent=rent)
            break

    direct = re.findall(r"\$\s*([\d]{1,3}(?:\.\d{3})+|\d{6,})", text)
    if direct and lo is None and hi is None:
        val = _parse_money_token(direct[0], rent=rent)
        if val:
            hi = val
    return lo, hi


def _detect_zones(text: str) -> List[str]:
    found: List[str] = []
    for zone_key, keywords in KNOWN_ZONES.items():
        if zone_key in found:
            continue
        if any(kw in text for kw in keywords):
            found.append(zone_key)
    return found


def _build_labels(parsed: ParsedQuery) -> List[str]:
    labels: List[str] = []
    if parsed.intent == "compare":
        labels.append("Comparar")
    if parsed.txn_from_text:
        labels.append("Arriendo" if parsed.transaction_type == "arriendo" else "Compra")
    if parsed.prop_from_text:
        labels.append("Casa" if parsed.property_type == "casa" else "Apartamento")
    if parsed.bedrooms:
        labels.append(f"{parsed.bedrooms} hab")
    if parsed.bathrooms:
        labels.append(f"{parsed.bathrooms} ba")
    for z in parsed.zones:
        labels.append(z.capitalize())
    if parsed.price_min and parsed.price_max:
        labels.append(f"${parsed.price_min:,} – ${parsed.price_max:,}".replace(",", "."))
    elif parsed.price_max:
        labels.append(f"Hasta ${parsed.price_max:,}".replace(",", "."))
    elif parsed.price_min:
        labels.append(f"Desde ${parsed.price_min:,}".replace(",", "."))
    return labels


def parse_natural_query(text: str) -> ParsedQuery:
    raw = (text or "").strip()
    lowered = _normalize(raw)

    intent = "compare"
    if re.search(r"\bcomparar\b", lowered) and re.search(
        r"fincaraiz|metrocuadrado|https?://", lowered
    ):
        pass
    elif re.search(r"^\s*comparar\b", lowered):
        pass
    else:
        intent = "search"

    txn = "compra"
    txn_from_text = False
    if re.search(r"\barriendo\b|\barrendar\b|\balquiler\b|\brentar\b", lowered):
        txn = "arriendo"
        txn_from_text = True
    elif re.search(r"\bcompra\b|\bventa\b|\bcomprar\b|\binversi[oó]n\b", lowered):
        txn = "compra"
        txn_from_text = True

    prop = "apartamento"
    prop_from_text = False
    if re.search(r"\b(apartamento|apto|apartamentos|apartaestudio)\b", lowered):
        prop = "apartamento"
        prop_from_text = True
    elif re.search(r"\b(casa|casas)\b", lowered):
        prop = "casa"
        prop_from_text = True

    bedrooms = None
    bed_match = re.search(
        r"(\d+)\s*(?:hab(?:itaciones?)?|cuartos?|dormitorios?|hab\b|habs\b)",
        lowered,
    )
    if bed_match:
        bedrooms = int(bed_match.group(1))

    bathrooms = None
    bath_match = re.search(r"(\d+)\s*(?:banos?|ba\b|baños?)", lowered)
    if bath_match:
        bathrooms = int(bath_match.group(1))

    zones = _detect_zones(lowered)
    price_min, price_max = _parse_prices(lowered, rent=txn == "arriendo")

    parsed = ParsedQuery(
        raw=raw,
        intent=intent,
        transaction_type=txn,
        property_type=prop,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        zones=zones,
        price_min=price_min,
        price_max=price_max,
        txn_from_text=txn_from_text,
        prop_from_text=prop_from_text,
    )
    parsed.labels = _build_labels(parsed)
    return parsed


def parsed_to_search_criteria(parsed: ParsedQuery, max_results: int):
    from search.criteria import SearchCriteria

    return SearchCriteria(
        bedrooms=parsed.bedrooms,
        bathrooms=parsed.bathrooms,
        zones=list(parsed.zones),
        property_type=parsed.property_type,
        transaction_type=parsed.transaction_type,
        price_min=parsed.price_min,
        price_max=parsed.price_max,
        max_results=max_results,
        portals=["fincaraiz", "metrocuadrado"],
    )
