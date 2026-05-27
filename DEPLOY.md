# Publicar Habitta ia en internet

Tu app usa **FastAPI + Playwright** (navegador para scrapear). No sirve GitHub Pages ni hosting estático: necesitas un servidor con Docker.

Opciones recomendadas (de más fácil a más control):

| Opción | Costo aprox. | Para quién |
|--------|----------------|------------|
| [Railway](https://railway.app) | ~USD 5/mes (crédito inicial gratis) | **Recomendado** |
| [Render](https://render.com) | Plan Starter ~USD 7/mes (disco persistente) | Alternativa |
| Túnel ngrok | Gratis (URL temporal) | Probar en 5 minutos |
| VPS (DigitalOcean, etc.) | ~USD 6/mes | Si sabes Linux |

---

## Antes de publicar

1. Sube el código a **GitHub** (repositorio privado o público).
2. No subas `.env` (ya está en `.gitignore`).
3. Genera un secreto para sesiones:
   ```powershell
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Guárdalo como `SECRET_KEY`.

---

## Opción A — Railway (recomendada)

1. Crea cuenta en https://railway.app e inicia sesión con GitHub.
2. **New Project** → **Deploy from GitHub repo** → elige tu repositorio.
3. Railway detectará el `Dockerfile` automáticamente.
4. En **Variables** del servicio, añade:
   | Variable | Valor |
   |----------|--------|
   | `ENVIRONMENT` | `production` |
   | `SECRET_KEY` | (el que generaste) |
   | `PROPINTEL_DB` | `/data/propintel.db` |
5. **Volumes** → Add Volume → monta en `/data` (1 GB).  
   Sin volumen, la base de datos se borra en cada redeploy.
6. **Settings** → **Networking** → **Generate Domain**  
   Obtendrás una URL tipo `https://habitta-ia-production.up.railway.app`
7. Espera el build (5–10 min la primera vez por Playwright).

**Health check:** `https://TU-DOMINIO/health` debe responder `{"status":"ok"}`.

---

## Opción B — Render

**Guía completa:** [DEPLOY_RENDER.md](DEPLOY_RENDER.md)

Resumen: GitHub → Render Dashboard → **New Blueprint** → tu repo → Apply → URL `https://habitta-ia.onrender.com`

---

## Opción C — Probar rápido con ngrok (sin deploy)

Con el servidor local encendido:

```powershell
pip install ngrok  # o descarga ngrok.com
ngrok http 8000
```

Comparte la URL `https://xxxx.ngrok-free.app` (cambia cada vez en plan gratis).

---

## Probar Docker en tu PC

```powershell
cd "ruta\al\proyecto"
docker build -t habitta-ia .
docker run -p 8000:8000 -e SECRET_KEY=tu-secreto -e ENVIRONMENT=production -v habitta-data:/data habitta-ia
```

Abre http://localhost:8000

---

## Después de publicar

- Comparte el enlace en redes / WhatsApp.
- Cada búsqueda tarda **30–90 s** (scraping real); el hosting debe permitir timeouts largos.
- Los portales pueden **limitar** IPs de datacenter; si falla el scrape en producción, prueba otro proveedor o un VPS en región cercana.
- Uso personal / MVP: respeta términos de Finca Raíz y Metrocuadrado.
- Para pagos Premium reales: integra **Wompi** o **Mercado Pago** (aún no implementado).

---

## Dominio propio (opcional)

En Railway/Render: **Custom Domain** → apunta un CNAME de tu dominio (ej. `app.tudominio.com`) al host que te den.

---

## Resumen de variables

| Variable | Obligatorio | Descripción |
|----------|-------------|-------------|
| `ENVIRONMENT` | Sí (prod) | `production` |
| `SECRET_KEY` | Sí | Sesiones y cookies |
| `PROPINTEL_DB` | Recomendado | `/data/propintel.db` con volumen |
| `PORT` | No | Lo define Railway/Render (default 8000) |
| `OPENAI_API_KEY` | No | Mejora textos de análisis IA |
