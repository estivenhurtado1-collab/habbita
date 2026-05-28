"""Persistencia de propiedades, favoritos, búsquedas y alertas."""
from __future__ import annotations

import json
from datetime import date
from typing import Any, List, Optional

from propintel.config import FREE_FAVORITES_MAX, FREE_SEARCHES_PER_DAY
from propintel.db import connect, row_to_dict, utc_now


def update_property_admin_fee(property_id: int, admin_fee: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE properties SET admin_fee = ?, updated_at = ? WHERE id = ?",
            (admin_fee, utc_now(), property_id),
        )
        conn.commit()


def upsert_property(data: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    with connect() as conn:
        existing = conn.execute(
            "SELECT id, price FROM properties WHERE fingerprint = ? OR original_url = ?",
            (data["fingerprint"], data["original_url"]),
        ).fetchone()

        if existing:
            prop_id = existing["id"]
            old_price = existing["price"]
            conn.execute(
                """
                UPDATE properties SET
                    title = ?, price = COALESCE(?, price), price_per_m2 = ?, neighborhood = ?,
                    area_m2 = ?, bedrooms = ?, bathrooms = ?, parking = ?,
                    stratum = ?, admin_fee = COALESCE(?, admin_fee),
                    score = ?, valorization_pct = ?,
                    analysis_text = ?, score_label = ?,
                    image_url = COALESCE(NULLIF(?, ''), image_url),
                    updated_at = ?, is_active = 1
                WHERE id = ?
                """,
                (
                    data.get("title"),
                    data.get("price"),
                    data.get("price_per_m2"),
                    data.get("neighborhood"),
                    data.get("area_m2"),
                    data.get("bedrooms"),
                    data.get("bathrooms"),
                    data.get("parking"),
                    data.get("stratum"),
                    data.get("admin_fee"),
                    data.get("score"),
                    data.get("valorization_pct"),
                    data.get("analysis_text"),
                    data.get("score_label"),
                    data.get("image_url"),
                    now,
                    prop_id,
                ),
            )
            if data.get("price") and old_price and data["price"] != old_price:
                conn.execute(
                    "INSERT INTO price_history (property_id, price, recorded_at) VALUES (?, ?, ?)",
                    (prop_id, data["price"], now),
                )
        else:
            cur = conn.execute(
                """
                INSERT INTO properties (
                    external_id, portal, fingerprint, title, price, price_per_m2,
                    neighborhood, locality, address_approx, area_m2, bedrooms, bathrooms,
                    parking, stratum, admin_fee, description, score, valorization_pct,
                    analysis_text, score_label, original_url, published_at, image_url,
                    transaction_type, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["external_id"],
                    data["portal"],
                    data["fingerprint"],
                    data.get("title"),
                    data.get("price"),
                    data.get("price_per_m2"),
                    data.get("neighborhood"),
                    data.get("locality", "Bogotá"),
                    data.get("address_approx"),
                    data.get("area_m2"),
                    data.get("bedrooms"),
                    data.get("bathrooms"),
                    data.get("parking"),
                    data.get("stratum"),
                    data.get("admin_fee"),
                    data.get("description"),
                    data.get("score"),
                    data.get("valorization_pct"),
                    data.get("analysis_text"),
                    data.get("score_label"),
                    data["original_url"],
                    data.get("published_at"),
                    data.get("image_url"),
                    data.get("transaction_type", "compra"),
                    now,
                    now,
                ),
            )
            prop_id = cur.lastrowid
            if data.get("price"):
                conn.execute(
                    "INSERT INTO price_history (property_id, price, recorded_at) VALUES (?, ?, ?)",
                    (prop_id, data["price"], now),
                )
        conn.commit()
        row = conn.execute("SELECT * FROM properties WHERE id = ?", (prop_id,)).fetchone()
    return row_to_dict(row)  # type: ignore[return-value]


def get_property(prop_id: int) -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM properties WHERE id = ? AND is_active = 1", (prop_id,)
        ).fetchone()
    return row_to_dict(row)


def get_property_by_url(url: str) -> Optional[dict[str, Any]]:
    normalized = (url or "").strip().split("?")[0].rstrip("/")
    if not normalized:
        return None
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM properties
            WHERE is_active = 1
              AND (original_url = ? OR original_url LIKE ?)
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (normalized, f"{normalized}%"),
        ).fetchone()
    return row_to_dict(row)


def get_properties_by_ids(ids: List[int]) -> List[dict[str, Any]]:
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM properties WHERE id IN ({placeholders}) AND is_active = 1",
            ids,
        ).fetchall()
    return [row_to_dict(r) for r in rows if r]  # type: ignore[misc]


def count_searches_today(user_id: Optional[int]) -> int:
    today = date.today().isoformat()
    with connect() as conn:
        if user_id:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c FROM searches
                WHERE user_id = ? AND created_at LIKE ?
                """,
                (user_id, f"{today}%"),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM searches WHERE user_id IS NULL AND created_at LIKE ?",
                (f"{today}%",),
            ).fetchone()
    return int(row["c"]) if row else 0


def can_search(user: Optional[dict[str, Any]]) -> tuple[bool, str]:
    from propintel.config import TRIAL_MODE

    if TRIAL_MODE:
        return True, ""
    if user and user.get("plan") == "premium":
        return True, ""
    count = count_searches_today(user["id"] if user else None)
    if count >= FREE_SEARCHES_PER_DAY:
        return False, f"Límite gratuito: {FREE_SEARCHES_PER_DAY} búsquedas por día. Pasa a Premium."
    return True, ""


def log_search(
    user_id: Optional[int],
    filters: dict[str, Any],
    result_count: int,
) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO searches (user_id, filters, result_count, created_at) VALUES (?, ?, ?, ?)",
            (user_id, json.dumps(filters), result_count, utc_now()),
        )
        conn.commit()


def count_favorites(user_id: int) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM favorites WHERE user_id = ?", (user_id,)
        ).fetchone()
    return int(row["c"]) if row else 0


def add_favorite(user_id: int, property_id: int, list_name: str = "General") -> tuple[bool, str]:
    user_plan = "free"
    with connect() as conn:
        u = conn.execute("SELECT plan FROM users WHERE id = ?", (user_id,)).fetchone()
        if u:
            user_plan = u["plan"]
    if user_plan != "premium" and count_favorites(user_id) >= FREE_FAVORITES_MAX:
        return False, f"Máximo {FREE_FAVORITES_MAX} favoritos en plan gratuito."

    with connect() as conn:
        try:
            conn.execute(
                """
                INSERT INTO favorites (user_id, property_id, list_name, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, property_id, list_name, utc_now()),
            )
            conn.commit()
            return True, "Guardado en favoritos."
        except Exception:
            return False, "Ya está en favoritos."


def remove_favorite(user_id: int, property_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM favorites WHERE user_id = ? AND property_id = ?",
            (user_id, property_id),
        )
        conn.commit()


def remove_favorites_bulk(user_id: int, property_ids: list[int]) -> int:
    """Quita varios favoritos; devuelve cuántos se eliminaron."""
    ids = [int(i) for i in property_ids if i]
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    with connect() as conn:
        cur = conn.execute(
            f"DELETE FROM favorites WHERE user_id = ? AND property_id IN ({placeholders})",
            [user_id, *ids],
        )
        conn.commit()
        return cur.rowcount


def list_favorites(user_id: int) -> List[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT p.*, f.list_name, f.created_at AS favorited_at
            FROM favorites f
            JOIN properties p ON p.id = f.property_id
            WHERE f.user_id = ?
            ORDER BY f.created_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [row_to_dict(r) for r in rows if r]  # type: ignore[misc]


def is_favorite(user_id: int, property_id: int) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND property_id = ?",
            (user_id, property_id),
        ).fetchone()
    return row is not None


def list_alerts(user_id: int) -> List[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = row_to_dict(r)
        if d and isinstance(d.get("parameters"), str):
            d["parameters"] = json.loads(d["parameters"])
        out.append(d)
    return out  # type: ignore[return-value]


def create_alert(user_id: int, alert_type: str, parameters: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO alerts (user_id, alert_type, parameters, active, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (user_id, alert_type, json.dumps(parameters), utc_now()),
        )
        conn.commit()


def log_comparison(
    user_id: int,
    property_ids: List[int],
    summary: str,
) -> None:
    ids = [int(i) for i in property_ids if i]
    if not ids:
        return
    recent = list_comparison_history(user_id, 1)
    if recent and recent[0].get("property_ids") == ids:
        return
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO comparisons (user_id, property_ids, summary, item_count, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, json.dumps(ids), summary, len(ids), utc_now()),
        )
        conn.commit()


def list_comparison_history(user_id: int, limit: int = 15) -> List[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, property_ids, summary, item_count, created_at
            FROM comparisons
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    out: List[dict[str, Any]] = []
    for row in rows:
        d = row_to_dict(row)
        if not d:
            continue
        raw_ids = d.get("property_ids")
        if isinstance(raw_ids, str):
            try:
                pids = [int(x) for x in json.loads(raw_ids or "[]")]
            except (json.JSONDecodeError, TypeError, ValueError):
                pids = []
        else:
            pids = []
        if not pids:
            continue
        out.append(
            {
                "id": d["id"],
                "property_ids": pids,
                "ids_param": ",".join(str(i) for i in pids),
                "summary": d.get("summary") or f"{len(pids)} inmueble(s)",
                "item_count": int(d.get("item_count") or len(pids)),
                "created_at": d.get("created_at") or "",
            }
        )
    return out


def recent_searches(user_id: int, limit: int = 5) -> List[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM searches WHERE user_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        d = row_to_dict(r)
        if d and isinstance(d.get("filters"), str):
            d["filters"] = json.loads(d["filters"])
        out.append(d)
    return out  # type: ignore[return-value]


def market_stats() -> dict[str, Any]:
    with connect() as conn:
        top_zones = conn.execute(
            """
            SELECT neighborhood, COUNT(*) AS cnt, AVG(price_per_m2) AS avg_m2
            FROM properties WHERE is_active = 1
            GROUP BY neighborhood ORDER BY cnt DESC LIMIT 5
            """
        ).fetchall()
        avg_score = conn.execute(
            "SELECT AVG(score) AS s FROM properties WHERE is_active = 1"
        ).fetchone()
    return {
        "top_zones": [dict(z) for z in top_zones],
        "avg_score": round(avg_score["s"], 1) if avg_score and avg_score["s"] else None,
    }


def list_recommendations(limit: int = 6) -> List[dict[str, Any]]:
    """Propiedades para inicio/favoritos — prioriza las que tienen foto."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM properties
            WHERE is_active = 1
            ORDER BY
                CASE WHEN image_url IS NOT NULL AND image_url != '' THEN 0 ELSE 1 END,
                score DESC,
                updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [row_to_dict(r) for r in rows if r]  # type: ignore[misc]


def map_properties(limit: int = 80) -> List[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, price, neighborhood, score, valorization_pct,
                   price_per_m2, original_url, portal, image_url
            FROM properties
            WHERE is_active = 1
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [row_to_dict(r) for r in rows if r]  # type: ignore[misc]
