"""SQLite — esquema y conexión."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator, Optional

from propintel.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'free',
    budget INTEGER,
    favorite_zones TEXT DEFAULT '[]',
    property_type_pref TEXT,
    goal TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT NOT NULL,
    portal TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    title TEXT,
    price INTEGER,
    price_per_m2 REAL,
    neighborhood TEXT,
    locality TEXT DEFAULT 'Bogotá',
    address_approx TEXT,
    area_m2 REAL,
    bedrooms INTEGER,
    bathrooms INTEGER,
    parking INTEGER,
    stratum INTEGER,
    admin_fee INTEGER,
    description TEXT,
    score INTEGER,
    valorization_pct REAL,
    analysis_text TEXT,
    score_label TEXT,
    original_url TEXT NOT NULL UNIQUE,
    published_at TEXT,
    image_url TEXT,
    transaction_type TEXT DEFAULT 'compra',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL,
    price INTEGER NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (property_id) REFERENCES properties(id)
);

CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    property_id INTEGER NOT NULL,
    list_name TEXT DEFAULT 'General',
    created_at TEXT NOT NULL,
    UNIQUE(user_id, property_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (property_id) REFERENCES properties(id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    alert_type TEXT NOT NULL,
    parameters TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    filters TEXT NOT NULL,
    result_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ends_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_properties_portal ON properties(portal);
CREATE INDEX IF NOT EXISTS idx_properties_neighborhood ON properties(neighborhood);
CREATE INDEX IF NOT EXISTS idx_searches_user_date ON searches(user_id, created_at);
"""


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


_db_initialized = False


def init_db() -> None:
    global _db_initialized
    if _db_initialized:
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _db_initialized = True
    finally:
        conn.close()


@contextmanager
def connect() -> Generator[sqlite3.Connection, None, None]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return dict(row)


def json_loads(raw: str, default: Any = None) -> Any:
    try:
        return json.loads(raw or "null")
    except json.JSONDecodeError:
        return default if default is not None else {}
