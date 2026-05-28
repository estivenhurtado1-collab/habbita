"""Criterios de búsqueda extendidos (MVP PropIntel)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SearchCriteria:
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    parking: Optional[int] = None
    stratum: Optional[int] = None
    zones: List[str] = field(default_factory=list)
    property_type: Optional[str] = None  # apartamento | casa
    transaction_type: str = "compra"  # compra | arriendo
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    max_results: int = 10
    portals: List[str] = field(default_factory=lambda: ["fincaraiz", "metrocuadrado"])


def criteria_from_legacy(legacy) -> SearchCriteria:
    """Compatibilidad con search_query.SearchCriteria."""
    return SearchCriteria(
        bedrooms=legacy.bedrooms,
        zones=list(legacy.zones),
        property_type=legacy.property_type,
        max_results=legacy.max_results,
    )


def to_legacy(criteria: SearchCriteria):
    from search_query import SearchCriteria as Legacy

    legacy = Legacy(
        bedrooms=criteria.bedrooms,
        zones=criteria.zones,
        property_type=criteria.property_type,
        max_results=criteria.max_results,
    )
    legacy.transaction_type = criteria.transaction_type
    return legacy
