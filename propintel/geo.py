"""Coordenadas aproximadas de barrios (mapa MVP)."""
ZONE_COORDS: dict[str, tuple[float, float]] = {
    "chapinero": (4.6486, -74.0628),
    "usaquen": (4.7110, -74.0322),
    "chico": (4.6533, -74.0540),
    "cedritos": (4.7210, -74.0510),
    "teusaquillo": (4.6280, -74.0890),
    "suba": (4.7570, -74.0830),
    "kennedy": (4.6280, -74.1540),
    "fontibon": (4.6760, -74.1450),
    "engativa": (4.7020, -74.1200),
    "modelia": (4.6680, -74.1280),
    "bogotá": (4.6097, -74.0817),
    "bogota": (4.6097, -74.0817),
}


def coords_for_neighborhood(name: str) -> tuple[float, float]:
    key = (name or "bogota").lower().strip()
    for zone, coords in ZONE_COORDS.items():
        if zone in key:
            return coords
    return ZONE_COORDS["bogota"]


COMPARE_MARKER_COLORS = ("#2563eb", "#16a34a", "#d97706", "#dc2626", "#7c3aed")


def markers_for_properties(properties: list) -> list[dict]:
    """Marcadores Leaflet para inmuebles en comparación (evita solapamiento en mismo barrio)."""
    seen: dict[tuple[float, float], int] = {}
    markers: list[dict] = []
    for index, prop in enumerate(properties):
        lat, lng = coords_for_neighborhood(prop.get("neighborhood", ""))
        key = (round(lat, 4), round(lng, 4))
        offset = seen.get(key, 0)
        seen[key] = offset + 1
        markers.append(
            {
                "id": prop.get("id"),
                "original_url": prop.get("original_url"),
                "title": prop.get("title") or "Inmueble",
                "neighborhood": prop.get("neighborhood") or "Bogotá",
                "price": prop.get("price"),
                "score": prop.get("score"),
                "valorization_pct": prop.get("valorization_pct"),
                "lat": lat + offset * 0.004,
                "lng": lng + offset * 0.004,
                "index": index + 1,
                "color": COMPARE_MARKER_COLORS[index % len(COMPARE_MARKER_COLORS)],
            }
        )
    return markers


HOME_MARKER_COLOR = "#dc2626"


def markers_for_home_map(
    favorites: list,
    home_zone: str | None = None,
) -> list[dict]:
    """Marcadores de favoritos + ubicación «donde vives» para el mapa del inicio."""
    markers = markers_for_properties(favorites)
    zone = (home_zone or "").strip().lower()
    if zone:
        lat, lng = coords_for_neighborhood(zone)
        markers.append(
            {
                "id": None,
                "title": "Donde vives",
                "neighborhood": zone.capitalize(),
                "price": None,
                "score": None,
                "lat": lat,
                "lng": lng,
                "index": 0,
                "color": HOME_MARKER_COLOR,
                "is_home": True,
            }
        )
    return markers
