# Habitta ia — MVP

Plataforma inmobiliaria inteligente para **Bogotá**: agrega Finca Raíz y Metrocuadrado con score de inversión, análisis IA y modelo freemium.

## Ejecutar

```powershell
pip install -r requirements.txt
playwright install chromium
python -m uvicorn web.app:app --reload --host 127.0.0.1 --port 8000
```

O doble clic en `iniciar_web.bat` → http://127.0.0.1:8000

## Variables de entorno

Copia `.env.example` a `.env`:

- `SECRET_KEY` — sesiones (obligatorio en producción)
- `OPENAI_API_KEY` — opcional, mejora textos de análisis

## Planes

| Gratis | Premium ($30.000 COP/mes — demo en `/premium`) |
|--------|-----------------------------------------------|
| 2 búsquedas/día | Ilimitadas |
| 5 favoritos | Ilimitados |
| Score + análisis base | PDF, historial precio, alertas avanzadas |

## Estructura

- `propintel/` — DB, auth, scoring IA, búsqueda
- `scrapers/` — Metrocuadrado (Finca Raíz vía `search_query`)
- `web/` — UI FastAPI + plantillas

## Publicar en internet

Guía paso a paso: **[DEPLOY_RENDER.md](DEPLOY_RENDER.md)** (Render) · [DEPLOY.md](DEPLOY.md) (otras opciones).

## Pendiente para producción

- PostgreSQL (opcional; ahora SQLite + volumen)
- Pagos MercadoPago/Wompi
- Login Google (OAuth)
- Scraping programado (cron)
- Mapbox y deduplicación avanzada por imágenes
