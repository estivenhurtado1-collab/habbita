"""Extracción fiable del precio de venta en tarjetas de listados."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

# Venta apartamento/casa Bogotá — fuera de rango suele ser admin, m², etc.
MIN_SALE_COP = 45_000_000
MAX_SALE_COP = 20_000_000_000
MIN_RENT_COP = 400_000
MAX_RENT_COP = 30_000_000

_PRICE_RE = re.compile(
    r"\$\s*([\d]{1,3}(?:[.\s]\d{3})+|\d{6,})",
    re.IGNORECASE,
)

_BAD_CONTEXT = re.compile(
    r"admin|administraci|arriendo|alquiler|\/\s*m[²2]|por\s*m[²2]|"
    r"cuota|descuento\s*\d|ahorro|cr[eé]dito|hipoteca|enganche|"
    r"separaci[oó]n|cuota inicial",
    re.IGNORECASE,
)

_DESDE_CONTEXT = re.compile(r"\bdesde\b", re.IGNORECASE)


def price_bounds(transaction_type: str = "compra") -> tuple[int, int]:
    if transaction_type == "arriendo":
        return MIN_RENT_COP, MAX_RENT_COP
    return MIN_SALE_COP, MAX_SALE_COP


def parse_price_value(price_text: str, *, transaction_type: str = "compra") -> Optional[int]:
    if not price_text:
        return None
    digits = re.sub(r"[^\d]", "", price_text)
    if not digits:
        return None
    try:
        value = int(digits)
    except ValueError:
        return None
    lo, hi = price_bounds(transaction_type)
    if value < lo or value > hi:
        return None
    return value


def _listing_key(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.split("?")[0].rstrip("/").lower())
    return f"{parsed.netloc}{parsed.path}"


def _bad_near_amount(context: str, raw: str) -> bool:
    pos = context.find(raw)
    if pos < 0:
        pos = max(0, len(context) - len(raw))
    window = context[max(0, pos - 8) : pos + len(raw) + 6]
    return bool(_BAD_CONTEXT.search(window))


def _score_candidate(
    raw: str,
    value: int,
    context: str,
    *,
    in_price_element: bool,
    transaction_type: str = "compra",
) -> int:
    lo, hi = price_bounds(transaction_type)
    if value < lo or value > hi:
        return -10_000
    score = 0
    if in_price_element:
        score += 120
    if transaction_type == "compra" and _bad_near_amount(context, raw):
        score -= 200
    if _DESDE_CONTEXT.search(context[max(0, context.find(raw) - 12) : context.find(raw) + 1]):
        score -= 40
    if transaction_type == "arriendo":
        if 800_000 <= value <= 12_000_000:
            score += 40
        if re.search(r"arriendo|alquiler|canon|mensual", context, re.I):
            score += 50
        if value < 600_000:
            score -= 60
    else:
        if value >= 120_000_000:
            score += 25
        if value >= 250_000_000:
            score += 15
        if value < 8_000_000:
            score -= 80
    return score


def pick_best_price(
    candidates: List[Tuple[str, int, str, bool]],
    *,
    transaction_type: str = "compra",
) -> Tuple[str, Optional[int]]:
    """Elige el precio principal (venta o canon mensual) entre candidatos."""
    if not candidates:
        return "", None
    scored = [
        (
            raw,
            value,
            _score_candidate(
                raw, value, ctx, in_price_element=in_el, transaction_type=transaction_type
            ),
        )
        for raw, value, ctx, in_el in candidates
    ]
    scored.sort(key=lambda x: x[2], reverse=True)
    best_raw, best_val, best_score = scored[0]
    if best_score < 0:
        return "", None
    return best_raw, best_val


def extract_prices_from_text(
    text: str, *, transaction_type: str = "compra"
) -> List[Tuple[str, int, str]]:
    """Devuelve [(raw, value, contexto_40_chars), ...]."""
    if not text:
        return []
    found: List[Tuple[str, int, str]] = []
    seen: set[int] = set()
    for match in _PRICE_RE.finditer(text):
        raw = f"$ {match.group(1)}"
        value = parse_price_value(raw, transaction_type=transaction_type)
        if not value or value in seen:
            continue
        seen.add(value)
        start = max(0, match.start() - 22)
        end = min(len(text), match.end() + 22)
        ctx = text[start:end]
        found.append((raw, value, ctx))
    return found


def extract_price_text(text: str, *, transaction_type: str = "compra") -> str:
    """Compatibilidad: mejor candidato en texto plano."""
    raw, _ = pick_best_price(
        [(r, v, c, False) for r, v, c in extract_prices_from_text(text, transaction_type=transaction_type)],
        transaction_type=transaction_type,
    )
    return raw


def extract_price_from_card(
    anchor,
    card_text: str,
    *,
    strict: bool = False,
    transaction_type: str = "compra",
) -> Tuple[str, Optional[int]]:
    """Precio desde nodos DOM de la tarjeta y, si falla, del texto."""
    candidates: List[Tuple[str, int, str, bool]] = []

    for level in range(1, 10):
        parent = anchor.locator(f"xpath=ancestor::*[{level}]")
        if parent.count() == 0:
            break
        root = parent.first
        price_nodes = root.locator(
            "[class*='price' i], [class*='precio' i], [class*='Price' i], "
            "[data-price], [itemprop='price'], [class*='amount' i]"
        )
        for i in range(min(price_nodes.count(), 6)):
            node = price_nodes.nth(i)
            node_text = (node.inner_text() or "").strip()
            for raw, value, ctx in extract_prices_from_text(
                node_text, transaction_type=transaction_type
            ):
                candidates.append((raw, value, ctx, True))

    if not strict:
        for raw, value, ctx in extract_prices_from_text(
            card_text, transaction_type=transaction_type
        ):
            candidates.append((raw, value, ctx, False))

    # Deduplicar por valor
    by_value: Dict[int, Tuple[str, int, str, bool]] = {}
    for raw, value, ctx, in_el in candidates:
        prev = by_value.get(value)
        if prev is None or (in_el and not prev[3]):
            by_value[value] = (raw, value, ctx, in_el)
    unique = list(by_value.values())
    raw, val = pick_best_price(unique, transaction_type=transaction_type)
    return raw, val


_JS_COLLECT_PRICES = """
(linkSelector) => {
  const key = (href) => {
    try {
      const u = new URL(href, location.origin);
      return (u.hostname + u.pathname).toLowerCase().replace(/\\/$/, "");
    } catch (e) {
      return (href || "").split("?")[0].toLowerCase();
    }
  };
  const parseNum = (s) => {
    const d = (s || "").replace(/[^\\d]/g, "");
    if (!d) return 0;
    const n = parseInt(d, 10);
    return Number.isFinite(n) ? n : 0;
  };
  const badCtx = (ctx) =>
    /admin|administraci|arriendo|alquiler|\\/\\s*m[²2]|por\\s*m|cuota|ahorro|hipoteca/i.test(ctx);
  const pickFromRoot = (root) => {
    if (!root) return null;
    const scored = [];
    const add = (raw, inPriceEl) => {
      const m = String(raw).match(/\\$\\s*([\\d.\\s]+)/);
      if (!m) return;
      const value = parseNum(m[1]);
      if (value < 45000000 || value > 20000000000) return;
      const idx = (root.innerText || "").indexOf(m[0]);
      const ctx = (root.innerText || "").slice(Math.max(0, idx - 40), idx + m[0].length + 40);
      if (badCtx(ctx)) return;
      let score = inPriceEl ? 100 : 0;
      if (/\\bdesde\\b/i.test(ctx)) score -= 35;
      if (value >= 120000000) score += 20;
      scored.push({ raw: m[0], value, score });
    };
    for (const el of root.querySelectorAll(
      '[class*="price" i], [class*="precio" i], [data-price], [itemprop="price"]'
    )) {
      const t = el.textContent || "";
      (t.match(/\\$\\s*[\\d.\\s]+/g) || []).forEach((p) => add(p, true));
    }
    const full = root.innerText || "";
    (full.match(/\\$\\s*[\\d.\\s]+/g) || []).forEach((p) => add(p, false));
    if (!scored.length) return null;
    scored.sort((a, b) => b.score - a.score || b.value - a.value);
    return scored[0];
  };
  const out = {};
  for (const a of document.querySelectorAll(linkSelector)) {
    const href = a.href || a.getAttribute("href") || "";
    if (!href) continue;
    let root = a.closest("article, li, [class*='card' i], [class*='Card']");
    if (!root) root = a.parentElement;
    for (let i = 0; i < 8 && root; i++) {
      const hit = pickFromRoot(root);
      if (hit) {
        out[key(href)] = hit.raw;
        break;
      }
      root = root.parentElement;
    }
  }
  return out;
}
"""


def collect_listing_prices(page: Any, link_selector: str) -> Dict[str, str]:
    try:
        raw: dict[str, str] = page.evaluate(_JS_COLLECT_PRICES, link_selector)
    except Exception:
        return {}
    return {k: v for k, v in (raw or {}).items() if v}


def lookup_price(
    price_map: Dict[str, str],
    listing_url: str,
    anchor=None,
    card_text: str = "",
    *,
    transaction_type: str = "",
) -> Tuple[str, Optional[int]]:
    strict = "/proyectos-vivienda/" in (listing_url or "").lower()
    key = _listing_key(listing_url)
    txn = transaction_type or (
        "arriendo" if "arriendo" in (listing_url or "").lower() or "alquiler" in (listing_url or "").lower() else "compra"
    )

    def accept(raw: str) -> Tuple[str, Optional[int]]:
        val = parse_price_value(raw, transaction_type=txn)
        if not val:
            return "", None
        if strict and _DESDE_CONTEXT.search(raw):
            return "", None
        return raw, val

    if key in price_map:
        return accept(price_map[key])
    for map_key, raw in price_map.items():
        if key.endswith(map_key) or map_key.endswith(key):
            r, v = accept(raw)
            if v:
                return r, v
    if anchor is not None:
        return extract_price_from_card(
            anchor, card_text, strict=strict, transaction_type=txn
        )
    if strict:
        return "", None
    raw = extract_price_text(card_text, transaction_type=txn)
    return raw, parse_price_value(raw, transaction_type=txn)
