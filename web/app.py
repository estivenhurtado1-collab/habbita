"""Habitta ia — aplicación web MVP."""
from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import quote, unquote, urlparse

import requests
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from propintel.auth import authenticate, create_user, get_user_by_id, set_plan, update_user_profile  # noqa: E402
from propintel.config import (  # noqa: E402
    COMPARE_LIMIT_FREE,
    COMPARE_LIMIT_PREMIUM,
    FREE_SEARCHES_PER_DAY,
    PREMIUM_PRICE_COP,
    RESULTS_LIMIT_FREE,
    RESULTS_LIMIT_PREMIUM,
    SECRET_KEY,
)
from propintel.compare_service import (  # noqa: E402
    compare_from_urls,
    compare_limit_for_user,
    comparison_summary,
    merge_properties_by_ids,
    resolve_compare_transaction,
)
from scrapers.listing_detail import detect_portal, parse_urls_from_text, scrape_listing_detail  # noqa: E402
from propintel.db import init_db, utc_now  # noqa: E402
from propintel.geo import markers_for_home_map, markers_for_properties  # noqa: E402
from propintel.repository import (  # noqa: E402
    add_favorite,
    can_search,
    create_alert,
    get_properties_by_ids,
    get_property,
    update_property_admin_fee,
    is_favorite,
    list_alerts,
    list_favorites,
    log_search,
    list_comparison_history,
    list_recommendations,
    log_comparison,
    recent_searches,
    remove_favorite,
    remove_favorites_bulk,
)
from propintel.search_service import group_by_portal, search_and_store  # noqa: E402
from search.criteria import SearchCriteria  # noqa: E402
from search_query import KNOWN_ZONES  # noqa: E402

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

init_db()

app = FastAPI(title="Habitta ia", description="Inteligencia inmobiliaria — Bogotá")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

ZONE_OPTIONS = sorted(KNOWN_ZONES.keys())


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "app": "habitta-ia"})


def format_cop(value: Optional[int]) -> str:
    if value is None:
        return "N/D"
    return f"${value:,.0f}".replace(",", ".")


templates.env.filters["format_cop"] = format_cop


def _script_json(value: Any) -> str:
    """JSON seguro para incrustar en HTML (evita romper <script>)."""
    from markupsafe import Markup

    raw = json.dumps(value, ensure_ascii=False)
    raw = raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return Markup(raw)  # type: ignore[return-value]


templates.env.filters["tojson"] = _script_json


def search_summary_filters(filters: Any) -> str:
    """Resumen legible de filtros guardados en `searches.filters`."""
    if not filters or not isinstance(filters, dict):
        return "Búsqueda en Bogotá"
    parts: list[str] = []
    prop = filters.get("property_type")
    if prop:
        parts.append(str(prop).capitalize())
    beds = filters.get("bedrooms")
    if beds:
        parts.append(f"{beds} hab")
    zones = filters.get("zones") or []
    if zones:
        parts.append(", ".join(str(z).capitalize() for z in zones))
    pmin, pmax = filters.get("price_min"), filters.get("price_max")
    if pmin or pmax:
        lo = format_cop(pmin) if pmin else "—"
        hi = format_cop(pmax) if pmax else "—"
        parts.append(f"{lo} – {hi}")
    portals = filters.get("portals") or []
    if portals:
        labels = {"fincaraiz": "Finca Raíz", "metrocuadrado": "Metrocuadrado"}
        parts.append(" · ".join(labels.get(p, p) for p in portals))
    return " · ".join(parts) if parts else "Búsqueda en Bogotá"


templates.env.filters["search_summary"] = search_summary_filters


def image_display_url(url: Optional[str]) -> str:
    """Proxy local: los portales suelen bloquear hotlinking directo."""
    if not url or not str(url).strip():
        return ""
    raw = str(url).strip()
    if raw.startswith("/"):
        return raw
    if not raw.startswith("http"):
        return raw
    return f"/img?u={quote(raw, safe='')}"


templates.env.filters["image_display_url"] = image_display_url


def _referer_for_image(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "metrocuadrado" in host:
        return "https://www.metrocuadrado.com/"
    if "fincaraiz" in host:
        return "https://www.fincaraiz.com.co/"
    return url


@app.get("/img")
async def proxy_image(u: str = Query("", alias="u")) -> Response:
    url = unquote(u)
    if not url.startswith("http"):
        return Response(status_code=404)

    def fetch() -> tuple[bytes, str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": _referer_for_image(url),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        last_exc: Exception | None = None
        for referer in (headers["Referer"], "https://www.google.com/"):
            try:
                resp = requests.get(
                    url,
                    headers={**headers, "Referer": referer},
                    timeout=12,
                    allow_redirects=True,
                )
                resp.raise_for_status()
                ctype = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
                if not ctype.startswith("image/"):
                    ctype = "image/jpeg"
                return resp.content, ctype
            except Exception as exc:
                last_exc = exc
        raise last_exc or RuntimeError("fetch failed")

    try:
        body, ctype = await asyncio.to_thread(fetch)
        return Response(
            content=body,
            media_type=ctype,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except Exception:
        return Response(status_code=404)


def get_session_user(request: Request) -> Optional[dict[str, Any]]:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return get_user_by_id(int(uid))


def guest_search_count(request: Request) -> int:
    today = date.today().isoformat()
    data = request.session.get("guest_searches", {})
    if data.get("date") != today:
        return 0
    return int(data.get("count", 0))


def inc_guest_search(request: Request) -> None:
    today = date.today().isoformat()
    data = request.session.get("guest_searches", {})
    if data.get("date") != today:
        data = {"date": today, "count": 0}
    data["count"] = int(data.get("count", 0)) + 1
    request.session["guest_searches"] = data


def base_context(request: Request, **extra) -> dict[str, Any]:
    user = get_session_user(request)
    ctx = {
        "request": request,
        "user": user,
        "is_premium": bool(user and user.get("plan") == "premium"),
        "premium_price": PREMIUM_PRICE_COP,
        "zones": ZONE_OPTIONS,
        "city": "Bogotá",
        "app_started": bool(request.session.get("app_started")),
    }
    ctx.update(extra)
    return ctx


def criteria_from_natural_query(text: str, max_results: int):
    from search.natural_query import parse_natural_query, parsed_to_search_criteria

    parsed = parse_natural_query(text)
    return parsed_to_search_criteria(parsed, max_results), parsed


async def _render_search_results(
    request: Request,
    criteria: SearchCriteria,
    *,
    bedrooms_form: str = "",
    bathrooms_form: str = "",
    parking_form: str = "",
    stratum_form: str = "",
    price_min_form: str = "",
    price_max_form: str = "",
) -> HTMLResponse:
    user = get_session_user(request)
    properties, portal_errors = await asyncio.to_thread(search_and_store, criteria)
    results_by_portal = group_by_portal(properties)
    if user:
        log_search(user["id"], criteria.__dict__, len(properties))
    else:
        inc_guest_search(request)

    fav_ids = set()
    if user:
        fav_ids = {f["id"] for f in list_favorites(user["id"])}

    return templates.TemplateResponse(
        request,
        "results.html",
        base_context(
            request,
            properties=properties,
            results_by_portal=results_by_portal,
            portal_errors=portal_errors,
            criteria=criteria,
            criteria_summary=summary_from_criteria(criteria),
            fav_ids=fav_ids,
            form={
                "property_type": criteria.property_type,
                "transaction_type": criteria.transaction_type,
                "bedrooms": bedrooms_form,
                "bathrooms": bathrooms_form,
                "parking": parking_form,
                "stratum": stratum_form,
                "price_min": price_min_form,
                "price_max": price_max_form,
                "zones": criteria.zones,
                "portal_fincaraiz": "fincaraiz" in criteria.portals,
                "portal_metrocuadrado": "metrocuadrado" in criteria.portals,
            },
        ),
    )


def criteria_from_form(
    property_type: str,
    transaction_type: str,
    bedrooms: str,
    bathrooms: str,
    parking: str,
    stratum: str,
    price_min: str,
    price_max: str,
    zones: List[str],
    portal_fincaraiz: Optional[str],
    portal_metrocuadrado: Optional[str],
    max_results: int,
) -> SearchCriteria:
    def parse_int(raw: str) -> Optional[int]:
        digits = re.sub(r"[^\d]", "", (raw or "").strip())
        return int(digits) if digits else None

    portals = []
    if portal_fincaraiz is not None:
        portals.append("fincaraiz")
    if portal_metrocuadrado is not None:
        portals.append("metrocuadrado")
    if not portals:
        portals = ["fincaraiz", "metrocuadrado"]

    prop = (property_type or "apartamento").lower()
    if prop not in ("apartamento", "casa"):
        prop = "apartamento"

    return SearchCriteria(
        bedrooms=parse_int(bedrooms),
        bathrooms=parse_int(bathrooms),
        parking=parse_int(parking),
        stratum=parse_int(stratum),
        zones=[z for z in zones if z in KNOWN_ZONES],
        property_type=prop,
        transaction_type=transaction_type or "compra",
        price_min=parse_int(price_min),
        price_max=parse_int(price_max),
        max_results=max_results,
        portals=portals,
    )


def summary_from_criteria(c: SearchCriteria) -> str:
    parts = []
    if c.transaction_type == "arriendo":
        parts.append("Arriendo")
    elif c.transaction_type:
        parts.append("Compra")
    if c.property_type:
        parts.append(c.property_type)
    if c.bedrooms:
        parts.append(f"{c.bedrooms} hab")
    if c.zones:
        parts.append(" o ".join(c.zones))
    if c.price_min or c.price_max:
        pmin = format_cop(c.price_min) if c.price_min else "—"
        pmax = format_cop(c.price_max) if c.price_max else "—"
        parts.append(f"{pmin} – {pmax}")
    return ", ".join(parts) if parts else "Bogotá"


@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "landing.html", base_context(request))


@app.get("/inicio", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> HTMLResponse:
    user = get_session_user(request)
    recs = list_recommendations(6)
    recent = recent_searches(user["id"], 5) if user else []
    home_favorites: list = []
    home_map_marker_list: list = []
    if user:
        home_favorites = list_favorites(user["id"])
        home_map_marker_list = markers_for_home_map(
            home_favorites, user.get("home_zone")
        )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        base_context(
            request,
            recommendations=recs,
            recent_searches=recent,
            home_favorites=home_favorites,
            home_map_marker_list=home_map_marker_list,
            home_map_has_markers=bool(home_map_marker_list),
        ),
    )


@app.get("/api/consulta/preview")
async def consulta_preview(q: str = Query("")) -> JSONResponse:
    from search.natural_query import parse_natural_query

    return JSONResponse(parse_natural_query(q).to_dict())


@app.post("/consultar", response_class=HTMLResponse)
async def consultar_submit(
    request: Request,
    query: str = Form(...),
) -> HTMLResponse:
    request.session["app_started"] = True
    text = (query or "").strip()

    if not text:
        return RedirectResponse("/inicio", status_code=303)

    urls = parse_urls_from_text(text)
    if urls or (
        re.search(r"\bcomparar\b", text.lower())
        and re.search(r"fincaraiz|metrocuadrado", text.lower())
    ):
        if urls:
            request.session["compare_prefill_urls"] = urls[:5]
        return RedirectResponse("/comparar", status_code=303)

    if re.search(r"^\s*comparar\b", text.lower()):
        return RedirectResponse("/comparar", status_code=303)

    user = get_session_user(request)
    is_premium = user and user.get("plan") == "premium"
    limit = RESULTS_LIMIT_PREMIUM if is_premium else RESULTS_LIMIT_FREE

    if user:
        ok, msg = can_search(user)
        if not ok:
            return templates.TemplateResponse(
                request,
                "landing.html",
                base_context(request, error=msg, show_premium_cta=True),
            )
    else:
        if guest_search_count(request) >= FREE_SEARCHES_PER_DAY:
            return templates.TemplateResponse(
                request,
                "landing.html",
                base_context(
                    request,
                    error="Regístrate gratis para más búsquedas o pasa a Premium.",
                    show_login_cta=True,
                ),
            )

    criteria, _parsed = criteria_from_natural_query(text, limit)
    return await _render_search_results(
        request,
        criteria,
        bedrooms_form=str(criteria.bedrooms or ""),
        bathrooms_form=str(criteria.bathrooms or ""),
        price_min_form=str(criteria.price_min or ""),
        price_max_form=str(criteria.price_max or ""),
    )


@app.get("/buscar", response_class=HTMLResponse)
async def search_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "search.html", base_context(request))


@app.post("/buscar", response_class=HTMLResponse)
async def search_submit(
    request: Request,
    property_type: str = Form("apartamento"),
    transaction_type: str = Form("compra"),
    bedrooms: str = Form(""),
    bathrooms: str = Form(""),
    parking: str = Form(""),
    stratum: str = Form(""),
    price_min: str = Form(""),
    price_max: str = Form(""),
    zones: List[str] = Form(default=[]),
    portal_fincaraiz: Optional[str] = Form(None),
    portal_metrocuadrado: Optional[str] = Form(None),
) -> HTMLResponse:
    user = get_session_user(request)
    is_premium = user and user.get("plan") == "premium"
    limit = RESULTS_LIMIT_PREMIUM if is_premium else RESULTS_LIMIT_FREE

    if user:
        ok, msg = can_search(user)
        if not ok:
            return templates.TemplateResponse(
                request,
                "search.html",
                base_context(request, error=msg, show_premium_cta=True),
            )
    else:
        if guest_search_count(request) >= FREE_SEARCHES_PER_DAY:
            return templates.TemplateResponse(
                request,
                "search.html",
                base_context(
                    request,
                    error="Regístrate gratis para más búsquedas o pasa a Premium.",
                    show_login_cta=True,
                ),
            )

    criteria = criteria_from_form(
        property_type,
        transaction_type,
        bedrooms,
        bathrooms,
        parking,
        stratum,
        price_min,
        price_max,
        zones,
        portal_fincaraiz,
        portal_metrocuadrado,
        limit,
    )

    request.session["app_started"] = True
    resp = await _render_search_results(
        request,
        criteria,
        bedrooms_form=bedrooms,
        bathrooms_form=bathrooms,
        parking_form=parking,
        stratum_form=stratum,
        price_min_form=price_min,
        price_max_form=price_max,
    )
    return resp


@app.get("/propiedad/{prop_id}", response_class=HTMLResponse)
async def property_detail(request: Request, prop_id: int) -> HTMLResponse:
    prop = get_property(prop_id)
    if not prop:
        return RedirectResponse("/buscar", status_code=302)
    if not prop.get("admin_fee") and prop.get("original_url") and detect_portal(prop["original_url"]):
        try:
            data = await asyncio.to_thread(scrape_listing_detail, prop["original_url"])
            fee = data.get("admin_fee")
            if fee:
                update_property_admin_fee(prop_id, int(fee))
                prop["admin_fee"] = int(fee)
        except Exception:
            pass
    user = get_session_user(request)
    fav = is_favorite(user["id"], prop_id) if user else False
    with_history = []
    from propintel.db import connect

    with connect() as conn:
        rows = conn.execute(
            "SELECT price, recorded_at FROM price_history WHERE property_id = ? ORDER BY recorded_at",
            (prop_id,),
        ).fetchall()
        with_history = [dict(r) for r in rows]
    return templates.TemplateResponse(
        request,
        "property.html",
        base_context(request, prop=prop, is_fav=fav, price_history=with_history),
    )


@app.get("/favoritos", response_class=HTMLResponse)
async def favorites_page(request: Request) -> HTMLResponse:
    user = get_session_user(request)
    if not user:
        return RedirectResponse("/auth/login?next=/favoritos", status_code=302)
    favs = list_favorites(user["id"])
    fav_marker_list = markers_for_properties(favs) if favs else []
    return templates.TemplateResponse(
        request,
        "favorites.html",
        base_context(
            request,
            favorites=favs,
            favorite_marker_list=fav_marker_list,
        ),
    )


@app.post("/favoritos/quitar")
async def favorites_remove_bulk(
    request: Request, prop_ids: List[int] = Form(default=[])
) -> RedirectResponse:
    user = get_session_user(request)
    if not user:
        return RedirectResponse("/auth/login?next=/favoritos", status_code=302)
    removed = remove_favorites_bulk(user["id"], prop_ids)
    if removed:
        request.session["flash"] = (
            f"Se borró {removed} favorito." if removed == 1 else f"Se borraron {removed} favoritos."
        )
    return RedirectResponse("/favoritos", status_code=303)


@app.post("/favoritos/{prop_id}")
async def favorites_add(request: Request, prop_id: int) -> RedirectResponse:
    user = get_session_user(request)
    if not user:
        return RedirectResponse(f"/auth/login?next=/propiedad/{prop_id}", status_code=302)
    ok, msg = add_favorite(user["id"], prop_id)
    request.session["flash"] = msg if ok else msg
    return RedirectResponse(f"/propiedad/{prop_id}", status_code=303)


@app.post("/favoritos/{prop_id}/quitar")
async def favorites_remove(request: Request, prop_id: int) -> RedirectResponse:
    user = get_session_user(request)
    if user:
        remove_favorite(user["id"], prop_id)
    return RedirectResponse("/favoritos", status_code=303)


@app.get("/alertas", response_class=HTMLResponse)
async def alerts_page(request: Request) -> HTMLResponse:
    user = get_session_user(request)
    if not user:
        return RedirectResponse("/auth/login?next=/alertas", status_code=302)
    alerts = list_alerts(user["id"])
    return templates.TemplateResponse(
        request, "alerts.html", base_context(request, alerts=alerts)
    )


@app.post("/alertas")
async def alerts_create(
    request: Request,
    alert_type: str = Form("nueva_zona"),
    zone: str = Form("chapinero"),
) -> RedirectResponse:
    user = get_session_user(request)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)
    if user.get("plan") != "premium" and alert_type != "nueva_zona":
        request.session["flash"] = "Alertas avanzadas requieren Premium."
        return RedirectResponse("/premium", status_code=303)
    create_alert(user["id"], alert_type, {"zone": zone})
    request.session["flash"] = "Alerta creada."
    return RedirectResponse("/alertas", status_code=303)


def _compare_limit(request: Request) -> int:
    user = get_session_user(request)
    is_premium = bool(user and user.get("plan") == "premium")
    return compare_limit_for_user(user, is_premium=is_premium)


GUEST_COMPARE_HISTORY_MAX = 10
COMPARE_HISTORY_LIMIT = 15


def _guest_comparison_history(request: Request) -> list[dict[str, Any]]:
    entries = request.session.get("guest_comparisons", [])
    if not isinstance(entries, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in entries[:GUEST_COMPARE_HISTORY_MAX]:
        if not isinstance(entry, dict):
            continue
        pids = [int(x) for x in entry.get("property_ids", []) if x]
        if not pids:
            continue
        out.append(
            {
                "property_ids": pids,
                "ids_param": ",".join(str(i) for i in pids),
                "summary": entry.get("summary") or f"{len(pids)} inmueble(s)",
                "item_count": int(entry.get("item_count") or len(pids)),
                "created_at": entry.get("created_at") or "",
            }
        )
    return out


def _append_guest_comparison(request: Request, props: list) -> None:
    ids = [int(p["id"]) for p in props if p.get("id")]
    if not ids:
        return
    entry = {
        "property_ids": ids,
        "summary": comparison_summary(props),
        "item_count": len(ids),
        "created_at": utc_now(),
    }
    entries = request.session.get("guest_comparisons", [])
    if not isinstance(entries, list):
        entries = []
    entries = [e for e in entries if isinstance(e, dict) and e.get("property_ids") != ids]
    entries.insert(0, entry)
    request.session["guest_comparisons"] = entries[:GUEST_COMPARE_HISTORY_MAX]


def _compare_history_for_request(request: Request) -> list[dict[str, Any]]:
    user = get_session_user(request)
    if user:
        return list_comparison_history(user["id"], COMPARE_HISTORY_LIMIT)
    return _guest_comparison_history(request)


def _record_comparison(request: Request, props: list) -> None:
    if not props:
        return
    ids = [int(p["id"]) for p in props if p.get("id")]
    if not ids:
        return
    summary = comparison_summary(props)
    user = get_session_user(request)
    if user:
        log_comparison(user["id"], ids, summary)
    else:
        _append_guest_comparison(request, props)


def _compare_url_rows(submitted: list[str] | None, limit: int) -> list[str]:
    """Filas del formulario: al menos 2 campos vacíos si caben, hasta el límite del plan."""
    rows = [str(u or "") for u in (submitted or [])]
    if not rows:
        rows = [""] * min(2, limit)
    while len(rows) < min(2, limit):
        rows.append("")
    return rows[:limit]


def _compare_context(request: Request, properties: list, **extra: Any) -> dict[str, Any]:
    limit = extra.get("compare_limit", COMPARE_LIMIT_FREE)
    if "compare_urls" not in extra:
        extra["compare_urls"] = _compare_url_rows(None, limit)
    if "compare_history" not in extra:
        extra["compare_history"] = _compare_history_for_request(request)
    ctx = base_context(
        request,
        properties=properties,
        compare_markers=json.dumps(markers_for_properties(properties)) if properties else "[]",
        **extra,
    )
    return ctx


@app.get("/comparar", response_class=HTMLResponse)
async def compare_page(request: Request, ids: str = "") -> HTMLResponse:
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    limit = _compare_limit(request)
    props = merge_properties_by_ids(id_list[:limit], [], transaction_type="compra")
    compare_txn = props[0].get("transaction_type", "compra") if props else "compra"
    prefill = request.session.pop("compare_prefill_urls", None)
    compare_urls = _compare_url_rows(prefill if prefill else None, limit)
    if prefill:
        request.session["app_started"] = True
    return templates.TemplateResponse(
        request,
        "compare.html",
        _compare_context(
            request,
            props,
            compare_limit=limit,
            compare_limit_free=COMPARE_LIMIT_FREE,
            compare_limit_premium=COMPARE_LIMIT_PREMIUM,
            url_errors={},
            compare_transaction=compare_txn,
            compare_urls=compare_urls,
        ),
    )


@app.post("/comparar", response_class=HTMLResponse)
async def compare_submit(
    request: Request,
    urls: List[str] = Form(default=[]),
    ids: str = Form(""),
    transaction_type: str = Form("compra"),
) -> HTMLResponse:
    user = get_session_user(request)
    is_premium = bool(user and user.get("plan") == "premium")
    limit = compare_limit_for_user(user, is_premium=is_premium)
    url_rows = _compare_url_rows(urls, limit)

    id_list = [int(x) for x in (ids or "").split(",") if x.strip().isdigit()]
    url_list = parse_urls_from_text("\n".join(url_rows))

    if not url_list and not id_list:
        return templates.TemplateResponse(
            request,
            "compare.html",
            _compare_context(
                request,
                [],
                error="Agrega al menos un enlace de Finca Raíz o Metrocuadrado.",
                compare_limit=limit,
                compare_limit_free=COMPARE_LIMIT_FREE,
                compare_limit_premium=COMPARE_LIMIT_PREMIUM,
                url_errors={},
                compare_urls=url_rows,
            ),
        )

    slots = limit - len(id_list)
    if slots < 0:
        id_list = id_list[:limit]
        slots = 0
    if len(url_list) > slots:
        url_list = url_list[: max(0, slots)]
        if not is_premium:
            request.session["flash"] = (
                f"Plan gratuito: máximo {COMPARE_LIMIT_FREE} inmuebles "
                f"({COMPARE_LIMIT_PREMIUM} con Premium)."
            )

    url_errors: dict[str, str] = {}
    url_props: list = []
    if url_list:
        url_props, url_errors = await asyncio.to_thread(
            compare_from_urls, url_list, transaction_type=transaction_type
        )

    props = merge_properties_by_ids(id_list, url_props, transaction_type=transaction_type)
    if props:
        _record_comparison(request, props)

    request.session["app_started"] = True
    compare_txn = resolve_compare_transaction(url_list, props, transaction_type)
    return templates.TemplateResponse(
        request,
        "compare.html",
        _compare_context(
            request,
            props,
            compare_limit=limit,
            compare_limit_free=COMPARE_LIMIT_FREE,
            compare_limit_premium=COMPARE_LIMIT_PREMIUM,
            url_errors=url_errors,
            compare_urls=url_rows,
            compare_transaction=compare_txn,
        ),
    )


@app.get("/mapa")
async def map_page_redirect() -> RedirectResponse:
    return RedirectResponse("/comparar", status_code=302)


@app.get("/perfil", response_class=HTMLResponse)
async def profile_page(request: Request) -> HTMLResponse:
    user = get_session_user(request)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)
    return templates.TemplateResponse(request, "profile.html", base_context(request))


@app.post("/perfil")
async def profile_update(
    request: Request,
    name: str = Form(...),
    budget: str = Form(""),
    goal: str = Form(""),
    property_type_pref: str = Form(""),
    favorite_zones: List[str] = Form(default=[]),
    home_zone: str = Form(""),
) -> RedirectResponse:
    user = get_session_user(request)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)
    budget_val = int(budget) if budget.strip().isdigit() else None
    zone_val = home_zone.strip().lower() if home_zone else None
    if zone_val and zone_val not in ZONE_OPTIONS:
        zone_val = None
    update_user_profile(
        user["id"],
        name=name,
        budget=budget_val,
        goal=goal or None,
        property_type_pref=property_type_pref or None,
        favorite_zones=favorite_zones,
        home_zone=zone_val,
    )
    request.session["flash"] = "Perfil actualizado."
    return RedirectResponse("/perfil", status_code=303)


@app.get("/premium", response_class=HTMLResponse)
async def premium_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "pricing.html", base_context(request))


@app.post("/premium/activar-demo")
async def premium_demo(request: Request) -> RedirectResponse:
    user = get_session_user(request)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)
    set_plan(user["id"], "premium")
    request.session["flash"] = "Premium activado (demo MVP)."
    return RedirectResponse("/perfil", status_code=303)


@app.get("/auth/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/inicio") -> HTMLResponse:
    return templates.TemplateResponse(
        request, "auth_login.html", base_context(request, next_url=next)
    )


@app.post("/auth/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    user = authenticate(email, password)
    if not user:
        return templates.TemplateResponse(
            request,
            "auth_login.html",
            base_context(request, error="Email o contraseña incorrectos.", next_url=next),
        )
    request.session["user_id"] = user["id"]
    return RedirectResponse(next or "/", status_code=303)


@app.get("/auth/register", response_class=HTMLResponse)
async def register_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "auth_register.html", base_context(request))


@app.post("/auth/register")
async def register_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    budget: str = Form(""),
    goal: str = Form("comprar"),
    property_type_pref: str = Form("apartamento"),
    favorite_zones: List[str] = Form(default=[]),
) -> RedirectResponse:
    try:
        budget_val = int(budget) if budget.strip().isdigit() else None
        user = create_user(
            name=name,
            email=email,
            password=password,
            budget=budget_val,
            favorite_zones=favorite_zones,
            property_type_pref=property_type_pref,
            goal=goal,
        )
        request.session["user_id"] = user["id"]
        return RedirectResponse("/inicio", status_code=303)
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "auth_register.html",
            base_context(request, error=str(e)),
        )


@app.get("/auth/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/inicio", status_code=303)


@app.get("/auth/google")
async def google_login() -> RedirectResponse:
    return RedirectResponse(
        "/auth/login?error=google_pending",
        status_code=302,
    )
