# Bot diario de precios - FincaRaiz Bogota

Este bot extrae inmuebles de venta en Bogota, guarda historial diario en SQLite, compara precios contra el dia anterior y envia un resumen a Telegram.

## 1) Instalacion

En PowerShell, dentro de esta carpeta:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

## 2) Configurar Telegram

1. Crea un bot con [@BotFather](https://t.me/BotFather) y copia el token.
2. Copia `.env.example` a `.env` (si no existe) y completa:

```env
TELEGRAM_BOT_TOKEN=tu_token
TELEGRAM_CHAT_ID=
```

3. Abre tu bot en Telegram y envia `/start`.
4. Ejecuta una vez el script: detectara automaticamente tu `TELEGRAM_CHAT_ID` si dejaste el campo vacio.

Opcional: pega el chat id manualmente en `.env` (numero, o negativo si es grupo).

**Seguridad:** no subas `.env` a git (ya esta en `.gitignore`). Si el token se filtro, revocalo en BotFather.

## 3) Busqueda por mensaje en Telegram (interactivo)

**Debes dejar el bot encendido** (si cierras la ventana, no responde).

Opcion A - doble clic:

```text
iniciar_bot_telegram.bat
```

Opcion B - PowerShell:

```powershell
python .\telegram_search_bot.py
```

Veras: `Bot de busqueda activo`. Ahi si escribe en Telegram.

Luego escribe al bot **@Promaxestiven_bot** algo como:

```text
quiero un apartamento de 2 habitaciones en teusaquillo o chapinero
```

El bot responde con **hasta 5 inmuebles** que coinciden (precio, habitaciones, zona y enlace).

Zonas reconocidas (puedes combinar con "o"): teusaquillo, chapinero, usaquen, cedritos, suba, fontibon, kennedy, modelia, engativa.

## 4) Reporte diario automatico

```powershell
python .\fincaraiz_daily_bot.py --pages 3
```

Argumentos utiles:

- `--pages 3`: numero maximo de paginas a recorrer.
- `--db fincaraiz_history.db`: ruta de SQLite.
- `--reports-dir reports`: carpeta de reportes CSV.
- `--telegram-token` / `--telegram-chat-id`: sobreescriben variables de `.env`.

## 5) Archivos generados

- `fincaraiz_history.db`: historial diario.
- `reports\price_changes_YYYY-MM-DD.csv`: cambios de precio.
- `reports\new_listings_YYYY-MM-DD.csv`: inmuebles nuevos.
- `reports\removed_listings_YYYY-MM-DD.csv`: inmuebles retirados.

## 6) Programacion diaria en Windows (Task Scheduler)

1. Abre **Programador de tareas** > **Crear tarea basica**.
2. Nombre: `FincaRaiz Daily Bot`.
3. Desencadenador: **Diariamente** (ej. 7:00 AM).
4. Accion: **Iniciar un programa**.
5. Configura:

| Campo | Valor ejemplo |
|-------|----------------|
| Programa/script | `C:\Users\estiv\OneDrive\Documentos\cursor\ejemplo carpeta descargas\.venv\Scripts\python.exe` |
| Agregar argumentos | `fincaraiz_daily_bot.py --pages 3` |
| Iniciar en | `C:\Users\estiv\OneDrive\Documentos\cursor\ejemplo carpeta descargas` |

6. En **Condiciones**, desmarca "Iniciar solo si el equipo esta conectado a CA" si usas laptop.
7. Guarda y prueba con **Ejecutar**.

Requisitos: `.env` en la carpeta del proyecto y Python/venv instalados.

## 7) Mensaje en Telegram (reporte diario)

El bot envia:

- total de inmuebles extraidos,
- conteo de cambios, nuevos y retirados,
- top 5 cambios de precio (titulo, precio anterior/nuevo, % y URL).

La primera ejecucion solo registra datos; desde la segunda dia habra comparacion.

## 8) Notas

- Respeta terminos del sitio y evita frecuencias agresivas.
- Si la web cambia estructura, puede requerir ajustar selectores del scraper.
