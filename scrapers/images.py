"""Extrae URL de imagen principal desde la tarjeta del listado."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin


SKIP_IMAGE_MARKERS = (
    "logo",
    "icon",
    "avatar",
    "sprite",
    "banner",
    "pixel",
    "tracking",
    "1x1",
    "placeholder",
    "svg",
)


def is_listing_image(url: str) -> bool:
    if not url or url.startswith("data:"):
        return False
    lowered = url.lower()
    if any(marker in lowered for marker in SKIP_IMAGE_MARKERS):
        return False
    return bool(
        re.search(r"\.(jpe?g|png|webp|gif)", lowered)
        or "multimedia.metrocuadrado" in lowered
        or "cloudinary" in lowered
        or "fincaraiz" in lowered
        or "/images/" in lowered
    )


def normalize_image_url(url: str, base_url: str = "") -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        return f"https:{raw}"
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if base_url:
        return urljoin(base_url, raw)
    return raw


def extract_card_image(anchor, base_url: str = "") -> str:
    """Sube en el DOM desde el enlace del inmueble hasta encontrar una img válida."""
    for level in range(1, 12):
        parent = anchor.locator(f"xpath=ancestor::*[{level}]")
        if parent.count() == 0:
            break
        imgs = parent.locator("img")
        for i in range(min(imgs.count(), 5)):
            img = imgs.nth(i)
            for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                value = img.get_attribute(attr)
                if value and is_listing_image(value):
                    return normalize_image_url(value, base_url)
            srcset = img.get_attribute("srcset") or ""
            if srcset:
                first = srcset.split(",")[0].strip().split()[0]
                if is_listing_image(first):
                    return normalize_image_url(first, base_url)
    return ""
