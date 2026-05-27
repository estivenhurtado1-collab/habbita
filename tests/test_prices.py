"""Tests de extracción de precio."""
from scrapers.prices import extract_price_text, parse_price_value, pick_best_price


def test_rejects_admin_fee():
    text = "Apartamento 3 hab Administración $ 1.200.000 Venta $ 450.000.000"
    raw = extract_price_text(text)
    assert parse_price_value(raw) == 450_000_000


def test_rejects_per_m2():
    text = "Área 80 m² Precio $ 5.800.000 /m² Total $ 520.000.000"
    raw = extract_price_text(text)
    assert parse_price_value(raw) == 520_000_000


def test_rejects_tiny_amount():
    assert parse_price_value("$ 850.000") is None


def test_pick_best_prefers_sale_price():
    candidates = [
        ("$ 1.500.000", 1_500_000, "Administración mensual $ 1.500.000", False),
        ("$ 380.000.000", 380_000_000, "Venta $ 380.000.000", True),
    ]
    raw, val = pick_best_price(candidates)
    assert val == 380_000_000
