"""Orquestación de búsqueda multi-portal + persistencia."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from typing import Any, Dict, List

from propintel.enrich import listing_to_property_dict
from propintel.repository import upsert_property
from scrapers.browser_utils import (
    ScrapeSession,
    portal_wall_timeout_sec,
    search_fast_enabled,
    search_parallel_enabled,
)
from search.criteria import SearchCriteria, to_legacy

logger = logging.getLogger(__name__)
PER_PORTAL_LIMIT = 5


def _search_fincaraiz(criteria: SearchCriteria, session=None) -> list[Any]:
    legacy = to_legacy(criteria)
    pages = 1
    try:
        from search.aggregator import fincaraiz_search

        return fincaraiz_search(legacy, limit=criteria.max_results)
    except ImportError:
        from search_query import search_listings

        return search_listings(legacy, pages_per_url=pages, session=session)


def _search_metrocuadrado(criteria: SearchCriteria, session=None) -> list[Any]:
    legacy = to_legacy(criteria)
    try:
        from search.aggregator import metrocuadrado_search

        return metrocuadrado_search(legacy, limit=criteria.max_results)
    except ImportError:
        pass
    from scrapers.metrocuadrado import search_listings

    return search_listings(legacy, limit=criteria.max_results, session=session)


def _passes_filters(prop: dict, criteria: SearchCriteria) -> bool:
    price = prop.get("price")
    # Sin precio scrapeado: mostrar igual (evita vaciar resultados por precio incierto)
    if criteria.price_min and price is not None and price < criteria.price_min:
        return False
    if criteria.price_max and price is not None and price > criteria.price_max:
        return False
    if criteria.bathrooms and prop.get("bathrooms") and prop["bathrooms"] < criteria.bathrooms:
        return False
    if criteria.parking is not None and prop.get("parking") is not None:
        if prop["parking"] < criteria.parking:
            return False
    if criteria.stratum and prop.get("stratum") and prop["stratum"] != criteria.stratum:
        return False
    return True


def _process_listings(
    portal: str,
    listings: list[Any],
    criteria: SearchCriteria,
    seen_fp: set[str],
    limit: int,
) -> List[dict]:
    per_portal: List[dict] = []
    for listing in listings:
        if len(per_portal) >= limit:
            break
        data = listing_to_property_dict(listing, portal)
        if data["fingerprint"] in seen_fp:
            continue
        if not _passes_filters(data, criteria):
            continue
        seen_fp.add(data["fingerprint"])
        stored = upsert_property(data)
        if stored:
            per_portal.append(stored)
    per_portal.sort(key=lambda p: p.get("score") or 0, reverse=True)
    return per_portal


def _run_portal(
    portal: str,
    portal_criteria: SearchCriteria,
    criteria: SearchCriteria,
    seen_fp: set[str],
    portal_limit: int,
    session=None,
) -> tuple[str, List[dict], str | None]:
    try:
        if portal == "fincaraiz":
            listings = _search_fincaraiz(portal_criteria, session=session)
        elif portal == "metrocuadrado":
            listings = _search_metrocuadrado(portal_criteria, session=session)
        else:
            return portal, [], None
        rows = _process_listings(portal, listings, criteria, seen_fp, portal_limit)
        return portal, rows, None
    except Exception as exc:
        logger.exception("Error scraping %s", portal)
        return portal, [], str(exc)


def _run_portal_isolated(
    portal: str,
    portal_criteria: SearchCriteria,
    criteria: SearchCriteria,
    portal_limit: int,
) -> tuple[str, List[dict], str | None]:
    """Hilo propio: cada portal abre su Chromium (SEARCH_PARALLEL)."""
    seen_fp: set[str] = set()
    with ScrapeSession() as session:
        return _run_portal(
            portal, portal_criteria, criteria, seen_fp, portal_limit, session=session
        )


def _run_portal_timed(
    portal: str,
    portal_criteria: SearchCriteria,
    criteria: SearchCriteria,
    portal_limit: int,
) -> tuple[str, List[dict], str | None]:
    timeout = portal_wall_timeout_sec()
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(
            _run_portal_isolated,
            portal,
            portal_criteria,
            criteria,
            portal_limit,
        )
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeout:
            logger.warning("Portal %s superó %ss", portal, timeout)
            return portal, [], f"Tiempo agotado ({timeout}s)"


def search_and_store(criteria: SearchCriteria) -> tuple[List[dict], Dict[str, str]]:
    """Busca en cada portal y devuelve (lista plana, errores por portal)."""
    portal_limit = min(PER_PORTAL_LIMIT, criteria.max_results)
    portal_criteria = SearchCriteria(
        bedrooms=criteria.bedrooms,
        bathrooms=criteria.bathrooms,
        parking=criteria.parking,
        stratum=criteria.stratum,
        zones=criteria.zones,
        property_type=criteria.property_type,
        transaction_type=criteria.transaction_type,
        price_min=criteria.price_min,
        price_max=criteria.price_max,
        max_results=portal_limit * 2,
        portals=criteria.portals,
    )

    errors: Dict[str, str] = {}
    by_portal: Dict[str, List[dict]] = {}
    seen_fp: set[str] = set()

    active = [p for p in criteria.portals if p in ("fincaraiz", "metrocuadrado")]
    active.sort(key=lambda p: 0 if p == "fincaraiz" else 1)
    parallel = search_parallel_enabled() and len(active) > 1
    runner = _run_portal_timed if parallel else None
    total_rows = 0

    if parallel:
        with ThreadPoolExecutor(max_workers=len(active)) as pool:
            futures = {
                pool.submit(
                    runner,
                    portal,
                    portal_criteria,
                    criteria,
                    portal_limit,
                ): portal
                for portal in active
            }
            for fut in as_completed(futures):
                key, rows, err = fut.result()
                by_portal[key] = rows
                if err:
                    errors[key] = err
    else:
        with ScrapeSession() as session:
            for portal in active:
                key, rows, err = _run_portal(
                    portal,
                    portal_criteria,
                    criteria,
                    seen_fp,
                    portal_limit,
                    session=session,
                )
                by_portal[key] = rows
                if err:
                    errors[key] = err
                total_rows += len(rows)
                if (
                    search_fast_enabled()
                    and total_rows >= portal_limit
                    and not err
                ):
                    break

    combined: List[dict] = []
    for portal in criteria.portals:
        combined.extend(by_portal.get(portal, []))

    if len(combined) > criteria.max_results:
        combined.sort(key=lambda p: p.get("score") or 0, reverse=True)
        balanced: List[dict] = []
        used_ids: set[int] = set()
        for portal in criteria.portals:
            portal_rows = [p for p in by_portal.get(portal, []) if p["id"] not in used_ids]
            for row in portal_rows[:2]:
                balanced.append(row)
                used_ids.add(row["id"])
        remaining = [p for p in combined if p["id"] not in used_ids]
        remaining.sort(key=lambda p: p.get("score") or 0, reverse=True)
        for row in remaining:
            if len(balanced) >= criteria.max_results:
                break
            balanced.append(row)
        combined = balanced[: criteria.max_results]

    return combined, errors


def group_by_portal(properties: List[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {"fincaraiz": [], "metrocuadrado": []}
    for prop in properties:
        portal = prop.get("portal", "")
        if portal in grouped:
            grouped[portal].append(prop)
    return grouped
