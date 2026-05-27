"""Habitta ia — aplicación web MVP."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, List, Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from propintel.auth import authenticate, create_user, get_user_by_id, set_plan, update_user_profile  # noqa: E402
from propintel.config import (  # noqa: E402
    FREE_SEARCHES_PER_DAY,
    PREMIUM_PRICE_COP,
    RESULTS_LIMIT_FREE,
    RESULTS_LIMIT_PREMIUM,
    SECRET_KEY,
)
from propintel.db import init_db  # noqa: E402
from propintel.geo import coords_for_neighborhood  # noqa: E402
from propintel.repository import (  # noqa: E402
    add_favorite,
    can_search,
    create_alert,
    get_properties_by_ids,
    get_property,
    is_favorite,
    list_alerts,
    list_favorites,
    log_search,
    market_stats,
    list_recommendations,
    map_properties,
    recent_searches,
    remove_favorite,
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
    }
    ctx.update(extra)
    return ctx


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
        return int(raw.strip()) if raw and raw.strip().isdigit() else None

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
    if c.transaction_type:
        parts.append(c.transaction_type)
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
async def home(request: Request) -> HTMLResponse:
    user = get_session_user(request)
    stats = market_stats()
    recs = list_recommendations(6)
    recent = recent_searches(user["id"], 5) if user else []
    return templates.TemplateResponse(
        request,
        "home.html",
        base_context(
            request,
            stats=stats,
            recommendations=recs,
            recent_searches=recent,
        ),
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

    # Playwright sync no puede correr dentro del event loop de FastAPI
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
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "parking": parking,
                "stratum": stratum,
                "price_min": price_min,
                "price_max": price_max,
                "zones": criteria.zones,
                "portal_fincaraiz": "fincaraiz" in criteria.portals,
                "portal_metrocuadrado": "metrocuadrado" in criteria.portals,
            },
        ),
    )


@app.get("/propiedad/{prop_id}", response_class=HTMLResponse)
async def property_detail(request: Request, prop_id: int) -> HTMLResponse:
    prop = get_property(prop_id)
    if not prop:
        return RedirectResponse("/buscar", status_code=302)
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
    return templates.TemplateResponse(
        request, "favorites.html", base_context(request, favorites=favs)
    )


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


@app.get("/comparar", response_class=HTMLResponse)
async def compare_page(request: Request, ids: str = "") -> HTMLResponse:
    user = get_session_user(request)
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()][:4]
    props = get_properties_by_ids(id_list)
    if user and user.get("plan") != "premium" and len(id_list) > 2:
        request.session["flash"] = "Comparador completo: plan Premium."
    return templates.TemplateResponse(
        request, "compare.html", base_context(request, properties=props)
    )


@app.get("/mapa", response_class=HTMLResponse)
async def map_page(request: Request) -> HTMLResponse:
    props = map_properties(100)
    markers = []
    for p in props:
        lat, lng = coords_for_neighborhood(p.get("neighborhood", ""))
        markers.append({**p, "lat": lat, "lng": lng})
    return templates.TemplateResponse(
        request, "map.html", base_context(request, markers=json.dumps(markers))
    )


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
) -> RedirectResponse:
    user = get_session_user(request)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)
    budget_val = int(budget) if budget.strip().isdigit() else None
    update_user_profile(
        user["id"],
        name=name,
        budget=budget_val,
        goal=goal or None,
        property_type_pref=property_type_pref or None,
        favorite_zones=favorite_zones,
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


@app.get("/reporte/{prop_id}/pdf")
async def report_pdf(request: Request, prop_id: int):
    user = get_session_user(request)
    if not user or user.get("plan") != "premium":
        return RedirectResponse("/premium", status_code=302)
    prop = get_property(prop_id)
    if not prop:
        return RedirectResponse("/buscar", status_code=302)

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 750, "Habitta ia — Reporte")
    c.setFont("Helvetica", 11)
    y = 720
    for line in [
        f"Título: {prop.get('title', '')[:80]}",
        f"Precio: {format_cop(prop.get('price'))}",
        f"Barrio: {prop.get('neighborhood', '')}",
        f"m²: {prop.get('area_m2') or 'N/D'}",
        f"Score: {prop.get('score')}/100 — {prop.get('score_label', '')}",
        f"Valorización est.: {prop.get('valorization_pct')}%",
        "",
        prop.get("analysis_text", "")[:400],
        "",
        f"URL: {prop.get('original_url', '')}",
    ]:
        c.drawString(50, y, line[:90])
        y -= 18
    c.showPage()
    c.save()
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=habitta-{prop_id}.pdf"},
    )


@app.get("/auth/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/") -> HTMLResponse:
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
        return RedirectResponse("/", status_code=303)
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "auth_register.html",
            base_context(request, error=str(e)),
        )


@app.get("/auth/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/auth/google")
async def google_login() -> RedirectResponse:
    return RedirectResponse(
        "/auth/login?error=google_pending",
        status_code=302,
    )
