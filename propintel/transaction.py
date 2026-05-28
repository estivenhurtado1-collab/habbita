"""Tipo de operación: compra vs arriendo."""
from __future__ import annotations


def detect_transaction_type(url: str = "", title: str = "", source_text: str = "") -> str:
    blob = f"{url} {title} {source_text}".lower()
    if any(
        token in blob
        for token in (
            "arriendo",
            "alquiler",
            "en-arriendo",
            "/arriendo/",
            "arriendo/",
            "for-rent",
            "renta ",
        )
    ):
        return "arriendo"
    return "compra"


def transaction_label(transaction_type: str) -> str:
    return "Arriendo" if transaction_type == "arriendo" else "Compra"
