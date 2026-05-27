"""Obtiene el TELEGRAM_CHAT_ID tras enviar /start al bot."""
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
if not token:
    print("Define TELEGRAM_BOT_TOKEN en .env")
    raise SystemExit(1)

response = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
response.raise_for_status()
updates = response.json().get("result", [])

if not updates:
    print("No hay mensajes. Abre tu bot en Telegram, envia /start y vuelve a ejecutar este script.")
    raise SystemExit(1)

chat_id = str(updates[-1]["message"]["chat"]["id"])
print(f"TELEGRAM_CHAT_ID={chat_id}")
print("Copia ese valor en tu archivo .env")
