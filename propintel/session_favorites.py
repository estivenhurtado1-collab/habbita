"""Favoritos en sesión (modo prueba sin registro)."""
from __future__ import annotations

from typing import List, Optional, Set

from propintel.config import SESSION_FAVORITES_MAX, TRIAL_MODE
from propintel.repository import (
    add_favorite,
    get_properties_by_ids,
    is_favorite,
    list_favorites,
    remove_favorite,
    remove_favorites_bulk,
)


def _session_fav_list(request) -> List[int]:
    raw = request.session.get("guest_favorites", [])
    if not isinstance(raw, list):
        return []
    out: List[int] = []
    for item in raw:
        try:
            pid = int(item)
        except (TypeError, ValueError):
            continue
        if pid not in out:
            out.append(pid)
    return out[:SESSION_FAVORITES_MAX]


def _save_session_favs(request, ids: List[int]) -> None:
    request.session["guest_favorites"] = ids[:SESSION_FAVORITES_MAX]


def fav_ids_for_request(request, user: Optional[dict] = None) -> Set[int]:
    if TRIAL_MODE or not user:
        return set(_session_fav_list(request))
    return {f["id"] for f in list_favorites(user["id"])}


def favorites_for_request(request, user: Optional[dict] = None) -> List[dict]:
    ids = list(fav_ids_for_request(request, user))
    if not ids:
        return []
    return get_properties_by_ids(ids)


def is_fav_request(request, user: Optional[dict], prop_id: int) -> bool:
    if TRIAL_MODE or not user:
        return prop_id in fav_ids_for_request(request, user)
    return is_favorite(user["id"], prop_id)


def add_favorite_request(request, user: Optional[dict], prop_id: int) -> tuple[bool, str]:
    if not TRIAL_MODE and user:
        return add_favorite(user["id"], prop_id)
    ids = _session_fav_list(request)
    if prop_id in ids:
        return True, "Ya está en favoritos."
    if len(ids) >= SESSION_FAVORITES_MAX:
        return False, f"Máximo {SESSION_FAVORITES_MAX} favoritos en esta sesión."
    ids.append(prop_id)
    _save_session_favs(request, ids)
    return True, "Guardado en favoritos."


def remove_favorite_request(request, user: Optional[dict], prop_id: int) -> None:
    if not TRIAL_MODE and user:
        remove_favorite(user["id"], prop_id)
        return
    _save_session_favs(request, [i for i in _session_fav_list(request) if i != prop_id])


def remove_favorites_bulk_request(
    request, user: Optional[dict], prop_ids: List[int]
) -> int:
    if not TRIAL_MODE and user:
        return remove_favorites_bulk(user["id"], prop_ids)
    drop = {int(x) for x in prop_ids}
    kept = [i for i in _session_fav_list(request) if i not in drop]
    removed = len(_session_fav_list(request)) - len(kept)
    _save_session_favs(request, kept)
    return removed
