"""Configuración central."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
DB_PATH = Path(os.getenv("PROPINTEL_DB", ROOT / "propintel.db"))
SECRET_KEY = os.getenv("SECRET_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
PORT = int(os.getenv("PORT", "8000"))

if not SECRET_KEY:
    if ENVIRONMENT == "production":
        raise RuntimeError("SECRET_KEY es obligatorio en producción.")
    SECRET_KEY = "cambiar-en-desarrollo-habitta-dev"

if ENVIRONMENT == "production" and SECRET_KEY.startswith("cambiar"):
    raise RuntimeError("Configura un SECRET_KEY seguro en producción.")

FREE_SEARCHES_PER_DAY = 2
FREE_FAVORITES_MAX = 5
PREMIUM_PRICE_COP = 30_000

RESULTS_LIMIT_FREE = 10
RESULTS_LIMIT_PREMIUM = 30

COMPARE_LIMIT_FREE = 2
COMPARE_LIMIT_PREMIUM = 5
