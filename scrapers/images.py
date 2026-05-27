"""Extrae URL de imagen principal desde la tarjeta del listado."""
from __future__ import annotations

import re
from typing import Any, Dict
from urllib.parse import urljoin, urlparse


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
    ".svg",
    "spinner",
    "loading",
)


LISTING_IMAGE_HINTS = (
    "fincaraiz",
    "metrocuadrado",
    "multimedia",
    "cloudinary",
    "imagekit",
    "amazonaws",
    "arstatic",
    "metroimg",
    "staticfinca",
    "/images/",
    "/fotos/",
    "/photo",
    "/media/",
)


def is_listing_image(url: str) -> bool:
    if not url or url.startswith("data:"):
        return False
    lowered = url.lower()
    if any(marker in lowered for marker in SKIP_IMAGE_MARKERS):
        return False
    if re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", lowered):
        return True
    return any(hint in lowered for hint in LISTING_IMAGE_HINTS)


def normalize_image_url(url: str, base_url: str = "") -> str:
    raw = (url or "").strip().replace("&amp;", "&")
    if not raw:
        return ""
    if raw.startswith("//"):
        return f"https:{raw}"
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if base_url:
        return urljoin(base_url, raw)
    return raw


def listing_url_key(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.split("?")[0].rstrip("/").lower())
    return f"{parsed.netloc}{parsed.path}"


_JS_COLLECT_IMAGES = """
(linkSelector) => {
  const key = (href) => {
    try {
      const u = new URL(href, location.origin);
      return (u.hostname + u.pathname).toLowerCase().replace(/\\/$/, "");
    } catch (e) {
      return (href || "").split("?")[0].toLowerCase();
    }
  };
  const bad = (u) => !u || u.startsWith("data:") || /logo|icon|placeholder|1x1|sprite|spinner/i.test(u);
  const pick = (root) => {
    if (!root) return "";
    for (const img of root.querySelectorAll("img")) {
      for (const attr of ["data-src", "data-lazy-src", "data-original", "data-lazy", "data-url", "src"]) {
        const v = img.getAttribute(attr);
        if (!bad(v)) return v;
      }
      const ss = img.getAttribute("srcset");
      if (ss) {
        const u = ss.split(",")[0].trim().split(/\\s+/)[0];
        if (!bad(u)) return u;
      }
    }
    for (const el of root.querySelectorAll("[style*='background']")) {
      const m = (el.getAttribute("style") || "").match(/url\\(['"]?([^'")\\s]+)/i);
      if (m && !bad(m[1])) return m[1];
    }
    return "";
  };
  const out = {};
  for (const a of document.querySelectorAll(linkSelector)) {
    const href = a.href || a.getAttribute("href") || "";
    if (!href) continue;
    let root = a.closest("article, li, [class*='card' i], [class*='Card'], [data-testid]");
    if (!root) root = a.parentElement;
    for (let i = 0; i < 8 && root; i++) {
      const url = pick(root);
      if (url) {
        out[key(href)] = url;
        break;
      }
      root = root.parentElement;
    }
  }
  return out;
}
"""


def collect_listing_images(page: Any, link_selector: str, base_url: str = "") -> Dict[str, str]:
    """Mapa listing_url_key -> image_url desde el DOM ya cargado."""
    try:
        raw: dict[str, str] = page.evaluate(_JS_COLLECT_IMAGES, link_selector)
    except Exception:
        return {}
    out: Dict[str, str] = {}
    for href, img in (raw or {}).items():
        normalized = normalize_image_url(img, base_url)
        if normalized and is_listing_image(normalized):
            out[href] = normalized
    return out


def lookup_image(img_map: Dict[str, str], listing_url: str, base_url: str = "") -> str:
    if not img_map:
        return ""
    key = listing_url_key(listing_url)
    if key in img_map:
        return img_map[key]
    for map_key, url in img_map.items():
        if key.endswith(map_key) or map_key.endswith(key):
            return url
    return ""


def extract_card_image(anchor, base_url: str = "") -> str:
    """Sube en el DOM desde el enlace del inmueble hasta encontrar una img válida."""
    for level in range(1, 12):
        parent = anchor.locator(f"xpath=ancestor::*[{level}]")
        if parent.count() == 0:
            break
        imgs = parent.locator("img")
        for i in range(min(imgs.count(), 8)):
            img = imgs.nth(i)
            for attr in (
                "data-src",
                "data-lazy-src",
                "data-original",
                "data-lazy",
                "data-url",
                "src",
            ):
                value = img.get_attribute(attr)
                if value and is_listing_image(value):
                    return normalize_image_url(value, base_url)
            srcset = img.get_attribute("srcset") or ""
            if srcset:
                first = srcset.split(",")[0].strip().split()[0]
                if is_listing_image(first):
                    return normalize_image_url(first, base_url)
        style = parent.first.get_attribute("style") or ""
        match = re.search(r"url\(['\"]?([^'\")\s]+)", style, re.IGNORECASE)
        if match and is_listing_image(match.group(1)):
            return normalize_image_url(match.group(1), base_url)
    return ""
