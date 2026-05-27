"""Score de inversión y análisis (heurístico + OpenAI opcional)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# Promedio estimado COP/m² por barrio (MVP — calibrar con datos reales)
ZONE_AVG_M2: dict[str, float] = {
    "chapinero": 8_200_000,
    "usaquen": 9_500_000,
    "chico": 10_000_000,
    "cedritos": 7_800_000,
    "teusaquillo": 6_800_000,
    "suba": 5_200_000,
    "kennedy": 4_500_000,
    "fontibon": 4_200_000,
    "engativa": 4_800_000,
    "modelia": 5_500_000,
    "bogota": 6_000_000,
}

ZONE_VALORIZATION: dict[str, float] = {
    "chapinero": 6.5,
    "usaquen": 5.0,
    "cedritos": 4.5,
    "teusaquillo": 5.5,
    "suba": 7.0,
    "kennedy": 4.0,
    "fontibon": 3.5,
    "engativa": 4.2,
    "modelia": 4.8,
    "bogota": 5.0,
}

TRANSIT_ZONES = {"chapinero", "teusaquillo", "usaquen", "cedritos", "engativa"}


@dataclass
class IntelResult:
    score: int
    score_label: str
    valorization_pct: float
    analysis_text: str
    price_per_m2: Optional[float]
    vs_zone_pct: Optional[float]


def detect_zone(text: str) -> str:
    lowered = (text or "").lower()
    for zone in ZONE_AVG_M2:
        if zone != "bogota" and zone in lowered:
            return zone
    return "bogota"


def score_label_from_score(score: int) -> str:
    if score >= 80:
        return "Excelente oportunidad"
    if score >= 65:
        return "Buena inversión"
    if score >= 45:
        return "Precio promedio"
    return "Posible sobreprecio"


def compute_intel(
    price: Optional[int],
    area_m2: Optional[float],
    neighborhood: str,
    bedrooms: Optional[int],
    locality: str = "Bogotá",
    portal: str = "",
) -> IntelResult:
    zone = detect_zone(f"{neighborhood} {locality}")
    avg_m2 = ZONE_AVG_M2.get(zone, ZONE_AVG_M2["bogota"])
    val_trend = ZONE_VALORIZATION.get(zone, 5.0)

    price_per_m2: Optional[float] = None
    vs_zone_pct: Optional[float] = None
    if price and area_m2 and area_m2 > 0:
        price_per_m2 = price / area_m2
        vs_zone_pct = ((price_per_m2 - avg_m2) / avg_m2) * 100

    score = 50
    if vs_zone_pct is not None:
        if vs_zone_pct <= -12:
            score += 28
        elif vs_zone_pct <= -5:
            score += 18
        elif vs_zone_pct <= 5:
            score += 5
        elif vs_zone_pct <= 15:
            score -= 12
        else:
            score -= 22

    score += min(10, int(val_trend))
    if zone in TRANSIT_ZONES:
        score += 6
    if bedrooms and bedrooms >= 2:
        score += 4
    if portal == "metrocuadrado":
        score += 2

    score = max(0, min(100, score))
    label = score_label_from_score(score)

    if vs_zone_pct is not None and vs_zone_pct < 0:
        analysis = (
            f"Este inmueble está aproximadamente {abs(vs_zone_pct):.0f}% por debajo del "
            f"promedio de {zone.capitalize()} y tiene potencial de valorización "
            f"{'alto' if val_trend >= 6 else 'medio'}."
        )
    elif vs_zone_pct is not None and vs_zone_pct > 8:
        analysis = (
            f"El precio por m² supera el promedio de {zone.capitalize()} en {vs_zone_pct:.0f}%. "
            "Conviene comparar con alternativas similares antes de decidir."
        )
    else:
        analysis = (
            f"Precio alineado con el mercado de {zone.capitalize()}. "
            f"Tendencia de valorización estimada: {val_trend:.1f}% anual."
        )

    return IntelResult(
        score=score,
        score_label=label,
        valorization_pct=val_trend,
        analysis_text=analysis,
        price_per_m2=price_per_m2,
        vs_zone_pct=vs_zone_pct,
    )


def maybe_enhance_with_openai(analysis: str, title: str, zone: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return analysis
    try:
        import openai

        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Eres analista inmobiliario en Bogotá. Responde en 2 frases en español.",
                },
                {
                    "role": "user",
                    "content": f"Inmueble: {title}. Zona: {zone}. Análisis base: {analysis}",
                },
            ],
            max_tokens=120,
        )
        text = resp.choices[0].message.content
        return text.strip() if text else analysis
    except Exception:
        return analysis
