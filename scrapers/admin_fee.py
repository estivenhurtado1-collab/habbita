"""Extracción de cuota de administración (Finca Raíz, Metrocuadrado, etc.)."""
from __future__ import annotations

import re
from typing import Optional

ADMIN_MIN = 80_000
ADMIN_MAX = 15_000_000

_ADMIN_PATTERNS = (
    r"administraci[oó]n(?:\s+mensual)?\s*[:\-]?\s*\$?\s*([\d][\d.\s]*)",
    r"valor\s+(?:de\s+)?administraci[oó]n\s*[:\-]?\s*\$?\s*([\d][\d.\s]*)",
    r"cuota\s+(?:de\s+)?administraci[oó]n\s*[:\-]?\s*\$?\s*([\d][\d.\s]*)",
    r"\$?\s*([\d][\d.\s]{4,})\s*(?:/\s*mes\s*)?(?:de\s+)?administraci",
    r"administraci[oó]n\s+\$\s*([\d][\d.\s]*)",
    r"\badmin\.?\s*[:\-]?\s*\$?\s*([\d][\d.\s]*)",
)

_JS_ADMIN_FEE = """
() => {
  const min = 80000;
  const max = 15000000;
  const toInt = (s) => {
    const digits = (s || "").replace(/[^\\d]/g, "");
    if (!digits) return null;
    const n = parseInt(digits, 10);
    if (n >= min && n <= max) return n;
    return null;
  };
  const fromText = (t) => {
    if (!t) return null;
    const patterns = [
      /administraci[oó]n\\s*[:\\-]?\\s*\\$?\\s*([\\d][\\d.\\s]*)/i,
      /valor\\s+(?:de\\s+)?administraci[oó]n\\s*[:\\-]?\\s*\\$?\\s*([\\d][\\d.\\s]*)/i,
      /\\$\\s*([\\d][\\d.\\s]{4,})\\s*\\/\\s*mes/i,
    ];
    for (const p of patterns) {
      const m = t.match(p);
      if (m) {
        const v = toInt(m[1]);
        if (v) return v;
      }
    }
    const idx = t.search(/administraci[oó]n/i);
    if (idx >= 0) {
      const chunk = t.slice(idx, idx + 90);
      const m = chunk.match(/\\$\\s*([\\d][\\d.\\s]+)/);
      if (m) {
        const v = toInt(m[1]);
        if (v) return v;
      }
    }
    return null;
  };
  const selectors = [
    "[class*='administr' i]",
    "[data-testid*='admin' i]",
    "li", "dt", "dd", "span", "p", "div",
  ];
  for (const sel of selectors) {
    for (const el of document.querySelectorAll(sel)) {
      const t = (el.innerText || "").trim();
      if (!/administraci/i.test(t) || t.length > 160) continue;
      const v = fromText(t);
      if (v) return v;
      const sib = el.nextElementSibling;
      if (sib) {
        const v2 = toInt(sib.innerText);
        if (v2) return v2;
      }
    }
  }
  return fromText(document.body.innerText || "");
}
"""


def _cop_value(raw: str) -> Optional[int]:
    digits = re.sub(r"[^\d]", "", raw or "")
    if not digits:
        return None
    try:
        value = int(digits)
    except ValueError:
        return None
    if ADMIN_MIN <= value <= ADMIN_MAX:
        return value
    return None


def parse_admin_fee(text: str) -> Optional[int]:
    """Busca administración en texto plano (ficha o tarjeta de listado)."""
    if not text:
        return None
    blob = text.replace("\u00a0", " ")
    for pattern in _ADMIN_PATTERNS:
        match = re.search(pattern, blob, re.IGNORECASE)
        if match:
            value = _cop_value(match.group(1))
            if value:
                return value
    for match in re.finditer(r"administraci[oó]n", blob, re.IGNORECASE):
        window = blob[match.start() : match.start() + 100]
        price_match = re.search(r"\$\s*([\d][\d.\s]+)", window)
        if price_match:
            value = _cop_value(price_match.group(1))
            if value:
                return value
    return None


def scrape_admin_fee_from_page(page) -> Optional[int]:
    """Lee administración del DOM ya renderizado (Finca Raíz suele separar label y valor)."""
    try:
        val = page.evaluate(_JS_ADMIN_FEE)
        if isinstance(val, (int, float)):
            n = int(val)
            if ADMIN_MIN <= n <= ADMIN_MAX:
                return n
    except Exception:
        pass
    return None
