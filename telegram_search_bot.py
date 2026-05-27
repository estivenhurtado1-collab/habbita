"""
Bot interactivo de Telegram: escribe una busqueda y recibe hasta 5 inmuebles.

Ejemplo:
  quiero un apartamento de 2 habitaciones en teusaquillo o chapinero

IMPORTANTE: este script debe quedar corriendo en PowerShell.
"""
import logging
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from fincaraiz_daily_bot import TELEGRAM_MAX_MESSAGE_LEN, truncate_message
from search_query import format_search_response, parse_search_query, search_listings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

HELP_TEXT = """Bot de busqueda FincaRaiz

Escribe en lenguaje natural, por ejemplo:
- quiero un apartamento de 2 habitaciones en teusaquillo o chapinero
- apartamento 3 hab en cedritos
- casa 4 habitaciones en suba

Comandos:
/start - ayuda
/help - ayuda

La busqueda tarda ~30-60 segundos.
"""


def send_message(token: str, chat_id: str, text: str, reply_to: int | None = None) -> None:
    payload = {
        "chat_id": chat_id,
        "text": truncate_message(text, TELEGRAM_MAX_MESSAGE_LEN),
        "disable_web_page_preview": True,
    }
    if reply_to is not None:
        payload["reply_to_message_id"] = reply_to

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json=payload,
        timeout=60,
    )
    response.raise_for_status()


def delete_webhook(token: str) -> None:
    response = requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook", timeout=30)
    response.raise_for_status()


def get_updates(token: str, offset: int | None) -> list:
    params: dict = {"timeout": 25}
    if offset is not None:
        params["offset"] = offset
    response = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params=params,
        timeout=70,
    )
    response.raise_for_status()
    return response.json().get("result", [])


def safe_handle_text(token: str, chat_id: str, text: str, message_id: int, allowed_chat_id: str) -> None:
    try:
        handle_text(token, chat_id, text, message_id, allowed_chat_id)
    except Exception:
        logger.exception("Error procesando mensaje")
        try:
            send_message(
                token,
                chat_id,
                "Ocurrio un error procesando tu mensaje. Intenta de nuevo en unos segundos.",
                reply_to=message_id,
            )
        except Exception:
            logger.exception("No se pudo enviar mensaje de error")


def handle_text(token: str, chat_id: str, text: str, message_id: int, allowed_chat_id: str) -> None:
    if str(chat_id) != str(allowed_chat_id):
        send_message(token, chat_id, "No autorizado para usar este bot.")
        return

    command = text.strip().split()[0].lower() if text.strip() else ""
    if command in {"/start", "/help"}:
        send_message(token, chat_id, HELP_TEXT, reply_to=message_id)
        return

    criteria = parse_search_query(text, max_results=5)
    if criteria.bedrooms is None and not criteria.zones and not criteria.property_type:
        send_message(
            token,
            chat_id,
            "Escribe una busqueda de inmuebles. Ejemplo:\n"
            "apartamento 2 habitaciones en teusaquillo o chapinero\n\n"
            + HELP_TEXT,
            reply_to=message_id,
        )
        return

    send_message(
        token,
        chat_id,
        f"Buscando: {text[:120]}...\n(Esto puede tardar un minuto)",
        reply_to=message_id,
    )

    try:
        results = search_listings(criteria, pages_per_url=2)
        response = format_search_response(criteria, results)
    except Exception as exc:
        response = f"Error en la busqueda: {exc}"

    send_message(token, chat_id, response, reply_to=message_id)


def process_updates(token: str, allowed_chat_id: str, offset: int | None) -> int | None:
    updates = get_updates(token, offset)
    for update in updates:
        offset = update["update_id"] + 1
        message = update.get("message") or update.get("edited_message")
        if not message:
            continue
        text = message.get("text")
        if not text:
            continue
        chat_id = message["chat"]["id"]
        message_id = message["message_id"]
        logger.info("Mensaje de %s: %s", chat_id, text[:80])
        safe_handle_text(token, chat_id, text, message_id, allowed_chat_id)
    return offset


def run_bot() -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    allowed_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not allowed_chat_id:
        raise SystemExit("Configura TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env")

    delete_webhook(token)
    logger.info("Bot de busqueda activo. Escribe en Telegram (@Promaxestiven_bot).")

    offset = None
    # Procesar mensajes que llegaron mientras el bot estaba apagado
    for _ in range(20):
        pending = get_updates(token, offset)
        if not pending:
            break
        for update in pending:
            offset = update["update_id"] + 1
            message = update.get("message") or update.get("edited_message")
            if not message or not message.get("text"):
                continue
            safe_handle_text(
                token,
                message["chat"]["id"],
                message["text"],
                message["message_id"],
                allowed_chat_id,
            )

    while True:
        try:
            offset = process_updates(token, allowed_chat_id, offset)
        except Exception:
            logger.exception("Error en ciclo de polling")
            time.sleep(3)
        time.sleep(0.3)


if __name__ == "__main__":
    run_bot()
