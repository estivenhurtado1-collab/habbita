"""Autenticación email/contraseña."""
from __future__ import annotations

import json
from typing import Any, Optional

import bcrypt

from propintel.db import connect, row_to_dict, utc_now

# Límite de bcrypt (bytes UTF-8)
BCRYPT_MAX_BYTES = 72
MIN_PASSWORD_LEN = 6


def _normalize_password(password: str) -> bytes:
    raw = (password or "").encode("utf-8")
    if len(raw) > BCRYPT_MAX_BYTES:
        raw = raw[:BCRYPT_MAX_BYTES]
    return raw


def validate_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD_LEN:
        raise ValueError("La contraseña debe tener al menos 6 caracteres.")
    if len((password or "").encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError("La contraseña es demasiado larga (máximo 72 caracteres).")


def hash_password(password: str) -> str:
    validate_password(password)
    hashed = bcrypt.hashpw(_normalize_password(password), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            _normalize_password(password),
            password_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def create_user(
    name: str,
    email: str,
    password: str,
    budget: Optional[int] = None,
    favorite_zones: Optional[list[str]] = None,
    property_type_pref: Optional[str] = None,
    goal: Optional[str] = None,
) -> dict[str, Any]:
    email_clean = email.strip().lower()
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?", (email_clean,)
        ).fetchone()
        if existing:
            raise ValueError("Ya existe una cuenta con ese email.")

        cur = conn.execute(
            """
            INSERT INTO users (
                name, email, password_hash, plan, budget, favorite_zones,
                property_type_pref, goal, created_at
            ) VALUES (?, ?, ?, 'free', ?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                email_clean,
                hash_password(password),
                budget,
                json.dumps(favorite_zones or []),
                property_type_pref,
                goal,
                utc_now(),
            ),
        )
        conn.commit()
        user_id = cur.lastrowid
    return get_user_by_id(user_id)  # type: ignore[arg-type]


def authenticate(email: str, password: str) -> Optional[dict[str, Any]]:
    email_clean = email.strip().lower()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email_clean,)
        ).fetchone()
    user = row_to_dict(row)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    user.pop("password_hash", None)
    return user


def get_user_by_id(user_id: int) -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    user = row_to_dict(row)
    if user:
        user.pop("password_hash", None)
        if isinstance(user.get("favorite_zones"), str):
            try:
                user["favorite_zones"] = json.loads(user["favorite_zones"])
            except json.JSONDecodeError:
                user["favorite_zones"] = []
    return user


def update_user_profile(
    user_id: int,
    name: Optional[str] = None,
    budget: Optional[int] = None,
    favorite_zones: Optional[list[str]] = None,
    property_type_pref: Optional[str] = None,
    goal: Optional[str] = None,
    home_zone: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    user = get_user_by_id(user_id)
    if not user:
        return None
    with connect() as conn:
        conn.execute(
            """
            UPDATE users SET
                name = COALESCE(?, name),
                budget = COALESCE(?, budget),
                favorite_zones = COALESCE(?, favorite_zones),
                property_type_pref = COALESCE(?, property_type_pref),
                goal = COALESCE(?, goal),
                home_zone = ?
            WHERE id = ?
            """,
            (
                name,
                budget,
                json.dumps(favorite_zones) if favorite_zones is not None else None,
                property_type_pref,
                goal,
                (home_zone or "").strip() or None,
                user_id,
            ),
        )
        conn.commit()
    return get_user_by_id(user_id)


def set_plan(user_id: int, plan: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE users SET plan = ? WHERE id = ?", (plan, user_id))
        conn.commit()
