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
