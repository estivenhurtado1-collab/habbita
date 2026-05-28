"""Tests de extracción de administración."""
from scrapers.admin_fee import parse_admin_fee


def test_admin_colon_format():
    text = "Apartamento 3 hab. Administración: $ 1.200.000 Venta $ 450.000.000"
    assert parse_admin_fee(text) == 1_200_000


def test_admin_same_line():
    text = "Administración $ 850.000 · 80 m² · Chapinero"
    assert parse_admin_fee(text) == 850_000


def test_valor_administracion():
    text = "Valor de administración $450.000 Estrato 4"
    assert parse_admin_fee(text) == 450_000


def test_admin_after_keyword_window():
    text = "Detalles\nAdministración\n$ 620.000\nGaraje 1"
    assert parse_admin_fee(text) == 620_000
