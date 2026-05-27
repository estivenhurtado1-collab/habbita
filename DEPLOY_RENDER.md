# Publicar Habitta ia en Render — paso a paso

Render es el hosting: guarda tu app en internet y te da un enlace público.

---

## Lo que necesitas antes

1. Cuenta en **GitHub** (github.com).
2. El proyecto subido a un repositorio (sin el archivo `.env`).
3. Cuenta en **Render** (render.com) — puedes registrarte con GitHub.

### Subir el proyecto a GitHub (si aún no lo hiciste)

En PowerShell, dentro de la carpeta del proyecto:

```powershell
cd "C:\Users\estiv\OneDrive\Documentos\cursor\ejemplo carpeta descargas"
git init
git add .
git commit -m "Habitta ia - MVP"
```

Crea un repo vacío en GitHub (botón **New repository**) y luego:

```powershell
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git branch -M main
git push -u origin main
```

(Sustituye `TU_USUARIO` y `TU_REPO` por los tuyos.)

---

## Método 1 — Blueprint (automático, recomendado)

Usa el archivo `render.yaml` que ya está en el proyecto.

1. Entra a https://dashboard.render.com
2. Clic en **New +** → **Blueprint**
3. Conecta tu cuenta de **GitHub** si te lo pide.
4. Elige el repositorio donde subiste Habitta ia.
5. Render mostrará el servicio `habitta-ia` del archivo `render.yaml`.
6. Clic en **Apply**.

Render creará el servicio. La primera vez el **build puede tardar 10–15 minutos** (descarga Playwright).

7. Cuando diga **Live**, abre la URL que aparece arriba (ej. `https://habitta-ia.onrender.com`).

8. Prueba: `https://TU-URL.onrender.com/health`  
   Debe verse: `{"status":"ok","app":"habitta-ia"}`

### Plan y disco en Render

El `render.yaml` pide plan **Starter** y disco de **1 GB** en `/data` (para no perder usuarios ni propiedades).

- Si Render pide **tarjeta** para Starter, es normal (~USD 7/mes).
- **Plan Free**: la app se “duerme” tras inactividad (la primera visita tarda ~1 min en despertar) y **no guarda** la base de datos entre reinicios. Sirve solo para probar, no para usuarios reales.

---

## Método 2 — Crear el servicio a mano

Si Blueprint falla, hazlo manual:

1. **New +** → **Web Service**
2. Conecta el mismo repositorio de GitHub.
3. Configuración:
   - **Name:** `habitta-ia`
   - **Region:** Oregon (o la más cercana)
   - **Branch:** `main`
   - **Runtime:** `Docker`
   - **Dockerfile path:** `./Dockerfile`
   - **Instance type:** Starter (recomendado)
4. **Advanced** → **Health Check Path:** `/health`
5. **Environment variables** (Environment):

   | Key | Value |
   |-----|--------|
   | `ENVIRONMENT` | `production` |
   | `SECRET_KEY` | (genera uno, ver abajo) |
   | `PROPINTEL_DB` | `/data/propintel.db` |

   Generar `SECRET_KEY` en tu PC:

   ```powershell
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

6. **Disks** → **Add disk**
   - Mount path: `/data`
   - Size: 1 GB  
   (Solo en planes de pago.)

7. **Create Web Service** y espera el deploy.

---

## Después del deploy

- Comparte la URL de Render (WhatsApp, Instagram, etc.).
- Regístrate en la app desde el celular de un amigo para comprobar que funciona.
- Las búsquedas tardan **30–90 segundos**; es normal.
- Si el build falla, en Render abre **Logs** y revisa el error (copia el mensaje si necesitas ayuda).

---

## Problemas frecuentes

| Problema | Qué hacer |
|----------|-----------|
| Build muy lento o falla por memoria | Usa plan **Starter** o superior (más RAM). |
| “SECRET_KEY es obligatorio” | Añade variable `SECRET_KEY` en Environment. |
| Se borran usuarios al redeploy | Activa disco persistente en `/data` y `PROPINTEL_DB=/data/propintel.db`. |
| Primera visita muy lenta | Plan Free: el servicio estaba dormido; espera o usa Starter. |
| Búsqueda sin resultados | Los portales a veces bloquean IPs de servidores; prueba de nuevo o revisa Logs. |

---

## Dominio propio (opcional)

En el servicio → **Settings** → **Custom Domains** → sigue las instrucciones de Render para apuntar tu dominio.

---

## Resumen

1. Código en GitHub  
2. Render → Blueprint o Web Service con Docker  
3. Variables `ENVIRONMENT`, `SECRET_KEY`, `PROPINTEL_DB`  
4. Disco en `/data` (Starter)  
5. Compartir la URL `.onrender.com`
