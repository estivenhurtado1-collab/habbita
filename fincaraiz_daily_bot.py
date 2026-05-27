import argparse
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


TARGET_URL = "https://www.fincaraiz.com.co/venta/casas-y-apartamentos/bogota/bogota-dc"
BASE_URL = "https://www.fincaraiz.com.co"
DEFAULT_DB = "fincaraiz_history.db"
DEFAULT_REPORTS_DIR = "reports"
TELEGRAM_MAX_MESSAGE_LEN = 4000


@dataclass
class Listing:
    run_date: str
    listing_url: str
    title: str
    price_raw: str
    price_value: Optional[int]
    location: str
    bedrooms: Optional[int]
    bathrooms: Optional[int]
    area_m2: Optional[float]
    source_text: str
    image_url: str = ""


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def absolute_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"{BASE_URL}{url}"


def parse_price_value(price_text: str) -> Optional[int]:
    if not price_text:
        return None
    # Accepts values like $ 357.960.000 or $1,466,775,344
    digits = re.sub(r"[^\d]", "", price_text)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def parse_bedrooms(text: str) -> Optional[int]:
    patterns = [
        r"(\d+)\s*Habs?\.",
        r"(\d+)\s*Hab(?:itaciones?)?",
        r"Unidades desde:\s*(\d+)\s*Hab",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def parse_bathrooms(text: str) -> Optional[int]:
    match = re.search(r"(\d+)\s*Ba", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def parse_area(text: str) -> Optional[float]:
    match = re.search(r"(\d+(?:[\.,]\d+)?)\s*m²", text, re.IGNORECASE)
    if not match:
        return None
    raw = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def extract_price_text(text: str) -> str:
    match = re.search(r"(\$\s*[\d\.,]+)", text)
    return match.group(1) if match else ""


def extract_location(text: str) -> str:
    # Examples: "... en nueva colina, bogotá"
    match = re.search(r"en\s+([^,]+,\s*bogotá)", text, re.IGNORECASE)
    if match:
        return normalize_text(match.group(1))
    match = re.search(
        r"Apartamento en\s+([^,]+(?:,\s*Bogotá)?)",
        text,
        re.IGNORECASE,
    )
    return normalize_text(match.group(1)) if match else ""


def is_property_listing_href(href: str) -> bool:
    if not href:
        return False
    lowered = href.lower().split("?")[0]
    if re.search(r"/apartamento-en-venta(?:-en)?-[^/]+/\d+$", lowered):
        return True
    if re.search(r"/casa-en-venta(?:-en)?-[^/]+/\d+$", lowered):
        return True
    if re.search(r"/proyectos-vivienda/[^/]+/\d+$", lowered):
        return "bogota" in lowered or "bogot" in lowered
    return False


LISTING_LINK_SELECTOR = (
    "a[href*='/apartamento-en-venta'], "
    "a[href*='/casa-en-venta'], "
    "a[href*='/proyectos-vivienda/']"
)


def extract_card_text(anchor) -> str:
    """Sube en el DOM hasta encontrar el bloque completo del inmueble."""
    best = normalize_text(anchor.inner_text())
    for level in range(1, 10):
        parent = anchor.locator(f"xpath=ancestor::*[{level}]")
        if parent.count() == 0:
            break
        candidate = normalize_text(parent.inner_text())
        if len(candidate) < len(best):
            continue
        lowered = candidate.lower()
        has_price = "$" in candidate or "desde" in lowered
        has_details = "hab" in lowered or "m²" in lowered or "m2" in lowered
        if has_price and (has_details or len(candidate) > 180):
            best = candidate
        if len(candidate) > 350 and has_price:
            return candidate
    return best


def scrape_listings(url: str, max_pages: int) -> List[Listing]:
    today = date.today().isoformat()
    all_rows: List[Listing] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(45000)

        for page_idx in range(1, max_pages + 1):
            current_url = url if page_idx == 1 else f"{url}/pagina{page_idx}"
            print(f"[INFO] Extrayendo página {page_idx}: {current_url}")
            page.goto(current_url, wait_until="networkidle", timeout=90000)

            try:
                page.wait_for_selector(LISTING_LINK_SELECTOR, timeout=30000)
            except PlaywrightTimeoutError:
                print(f"[WARN] No se encontraron tarjetas en página {page_idx}.")
                continue

            link_nodes = page.locator(LISTING_LINK_SELECTOR)
            seen = set()

            for i in range(link_nodes.count()):
                anchor = link_nodes.nth(i)
                href = anchor.get_attribute("href") or ""
                if not is_property_listing_href(href):
                    continue
                listing_url = absolute_url(href)
                if not listing_url or listing_url in seen:
                    continue
                seen.add(listing_url)

                card_text = extract_card_text(anchor)
                title_match = re.search(
                    r"Apartamento en venta en [^$]+|Casa en venta en [^$]+|"
                    r"[\w\s]+, apartamentos? en venta en [^$]+",
                    card_text,
                    re.IGNORECASE,
                )
                if title_match:
                    title = normalize_text(title_match.group(0))[:120]
                elif "Desde" in card_text:
                    title = card_text.split("Desde")[0].strip()[:120]
                else:
                    title = card_text[:120]
                price_raw = extract_price_text(card_text)
                image_url = ""
                try:
                    from scrapers.images import extract_card_image

                    image_url = extract_card_image(anchor, BASE_URL)
                except Exception:
                    pass

                row = Listing(
                    run_date=today,
                    listing_url=listing_url,
                    title=title,
                    price_raw=price_raw,
                    price_value=parse_price_value(price_raw),
                    location=extract_location(card_text),
                    bedrooms=parse_bedrooms(card_text),
                    bathrooms=parse_bathrooms(card_text),
                    area_m2=parse_area(card_text),
                    source_text=card_text[:1200],
                    image_url=image_url,
                )
                all_rows.append(row)

        browser.close()

    # Keep most complete row per URL
    dedup: dict[str, Listing] = {}
    for row in all_rows:
        current = dedup.get(row.listing_url)
        if current is None:
            dedup[row.listing_url] = row
            continue
        current_score = (
            int(bool(current.price_value))
            + int(bool(current.bedrooms))
            + int(bool(current.area_m2))
            + int(bool(current.image_url))
        )
        new_score = (
            int(bool(row.price_value))
            + int(bool(row.bedrooms))
            + int(bool(row.area_m2))
            + int(bool(row.image_url))
        )
        if new_score > current_score:
            dedup[row.listing_url] = row

    return list(dedup.values())


def open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS listings_history (
            run_date TEXT NOT NULL,
            listing_url TEXT NOT NULL,
            title TEXT,
            price_raw TEXT,
            price_value INTEGER,
            location TEXT,
            bedrooms INTEGER,
            bathrooms INTEGER,
            area_m2 REAL,
            source_text TEXT,
            inserted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (run_date, listing_url)
        )
        """
    )
    return conn


def save_day(conn: sqlite3.Connection, rows: Iterable[Listing]) -> None:
    conn.executemany(
        """
        INSERT OR REPLACE INTO listings_history (
            run_date, listing_url, title, price_raw, price_value, location,
            bedrooms, bathrooms, area_m2, source_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row.run_date,
                row.listing_url,
                row.title,
                row.price_raw,
                row.price_value,
                row.location,
                row.bedrooms,
                row.bathrooms,
                row.area_m2,
                row.source_text,
            )
            for row in rows
        ],
    )
    conn.commit()


def load_dates(conn: sqlite3.Connection) -> List[str]:
    data = conn.execute("SELECT DISTINCT run_date FROM listings_history ORDER BY run_date DESC").fetchall()
    return [d[0] for d in data]


def compare_days(conn: sqlite3.Connection, today: str, previous: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    today_df = pd.read_sql_query(
        "SELECT * FROM listings_history WHERE run_date = ?",
        conn,
        params=[today],
    )
    prev_df = pd.read_sql_query(
        "SELECT * FROM listings_history WHERE run_date = ?",
        conn,
        params=[previous],
    )

    merged = today_df.merge(
        prev_df[["listing_url", "price_value", "price_raw"]],
        on="listing_url",
        how="inner",
        suffixes=("_today", "_prev"),
    )
    changed = merged[
        merged["price_value_today"].notna()
        & merged["price_value_prev"].notna()
        & (merged["price_value_today"] != merged["price_value_prev"])
    ].copy()
    changed["delta"] = changed["price_value_today"] - changed["price_value_prev"]
    changed["delta_pct"] = (changed["delta"] / changed["price_value_prev"]) * 100

    new_listings = today_df[~today_df["listing_url"].isin(prev_df["listing_url"])].copy()
    removed_listings = prev_df[~prev_df["listing_url"].isin(today_df["listing_url"])].copy()
    return changed, new_listings, removed_listings


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def generate_reports(
    reports_dir: Path,
    today: str,
    changes: pd.DataFrame,
    new_listings: pd.DataFrame,
    removed_listings: pd.DataFrame,
) -> None:
    ensure_dir(reports_dir)
    changes_path = reports_dir / f"price_changes_{today}.csv"
    new_path = reports_dir / f"new_listings_{today}.csv"
    removed_path = reports_dir / f"removed_listings_{today}.csv"

    changes.to_csv(changes_path, index=False, encoding="utf-8-sig")
    new_listings.to_csv(new_path, index=False, encoding="utf-8-sig")
    removed_listings.to_csv(removed_path, index=False, encoding="utf-8-sig")

    print(f"[OK] Reporte cambios: {changes_path}")
    print(f"[OK] Reporte nuevos: {new_path}")
    print(f"[OK] Reporte retirados: {removed_path}")


def format_cop(value: Optional[int]) -> str:
    if value is None:
        return "N/D"
    return f"${value:,.0f}".replace(",", ".")


def truncate_message(message: str, max_len: int = TELEGRAM_MAX_MESSAGE_LEN) -> str:
    if len(message) <= max_len:
        return message
    return message[: max_len - 20].rstrip() + "\n\n...(mensaje recortado)"


def resolve_chat_id_from_updates(token: str) -> Optional[str]:
    endpoint = f"https://api.telegram.org/bot{token}/getUpdates"
    response = requests.get(endpoint, timeout=30)
    response.raise_for_status()
    updates = response.json().get("result", [])
    for item in reversed(updates):
        message = item.get("message") or item.get("edited_message")
        if message and "chat" in message:
            return str(message["chat"]["id"])
    return None


def build_telegram_message(
    today: str,
    listings_count: int,
    previous_day: Optional[str],
    changes: pd.DataFrame,
    new_listings: pd.DataFrame,
    removed_listings: pd.DataFrame,
    first_run: bool,
) -> str:
    lines = [f"FincaRaiz bot ({today})", f"Inmuebles extraidos: {listings_count}"]

    if first_run or not previous_day:
        lines.append("Primera ejecucion: aun no hay dia anterior para comparar.")
        return truncate_message("\n".join(lines))

    lines.append(f"Comparacion vs {previous_day}")
    lines.append(
        f"Cambios de precio: {len(changes)} | Nuevos: {len(new_listings)} | Retirados: {len(removed_listings)}"
    )

    if not changes.empty:
        lines.append("\nTop 5 cambios de precio:")
        top = changes.reindex(changes["delta"].abs().sort_values(ascending=False).index).head(5)
        for _, row in top.iterrows():
            title = normalize_text(str(row.get("title", "")))[:80] or "Sin titulo"
            prev_price = format_cop(int(row["price_value_prev"]) if pd.notna(row["price_value_prev"]) else None)
            today_price = format_cop(int(row["price_value_today"]) if pd.notna(row["price_value_today"]) else None)
            delta_pct = row.get("delta_pct")
            pct_txt = f" ({delta_pct:+.1f}%)" if pd.notna(delta_pct) else ""
            lines.append(f"- {title}")
            lines.append(f"  {prev_price} -> {today_price}{pct_txt}")
            lines.append(f"  {row.get('listing_url', '')}")

    return truncate_message("\n".join(lines))


def send_telegram_message(token: str, chat_id: str, message: str) -> None:
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(
        endpoint,
        json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
        timeout=30,
    )
    response.raise_for_status()


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    parser = argparse.ArgumentParser(
        description="Scraper diario de FincaRaiz (Bogota venta casas y apartamentos)."
    )
    parser.add_argument("--url", default=TARGET_URL, help="URL objetivo para scraping.")
    parser.add_argument("--pages", type=int, default=3, help="Numero maximo de paginas a recorrer.")
    parser.add_argument("--db", default=DEFAULT_DB, help="Ruta del archivo SQLite.")
    parser.add_argument(
        "--reports-dir",
        default=DEFAULT_REPORTS_DIR,
        help="Directorio para exportar reportes CSV diarios.",
    )
    parser.add_argument(
        "--telegram-token",
        default=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        help="Token del bot de Telegram (o variable TELEGRAM_BOT_TOKEN).",
    )
    parser.add_argument(
        "--telegram-chat-id",
        default=os.getenv("TELEGRAM_CHAT_ID", ""),
        help="Chat ID destino (o variable TELEGRAM_CHAT_ID).",
    )
    args = parser.parse_args()

    telegram_token = args.telegram_token.strip()
    telegram_chat_id = args.telegram_chat_id.strip()
    if telegram_token and not telegram_chat_id:
        telegram_chat_id = resolve_chat_id_from_updates(telegram_token) or ""
        if telegram_chat_id:
            print(f"[INFO] Chat ID detectado automaticamente: {telegram_chat_id}")
        else:
            print(
                "[WARN] TELEGRAM_CHAT_ID vacio. Envia /start a tu bot en Telegram "
                "y vuelve a ejecutar, o define TELEGRAM_CHAT_ID en .env"
            )

    db_path = Path(args.db).resolve()
    reports_dir = Path(args.reports_dir).resolve()

    listings = scrape_listings(args.url, max_pages=max(args.pages, 1))
    if not listings:
        print("[WARN] No se encontraron inmuebles para guardar.")
        return

    print(f"[INFO] Inmuebles unicos extraidos: {len(listings)}")
    conn = open_db(db_path)
    try:
        save_day(conn, listings)
        dates = load_dates(conn)
        today = date.today().isoformat()
        if len(dates) < 2:
            print("[INFO] Primera ejecucion registrada. Aun no hay dia anterior para comparar.")
            if telegram_token and telegram_chat_id:
                msg = build_telegram_message(
                    today=today,
                    listings_count=len(listings),
                    previous_day=None,
                    changes=pd.DataFrame(),
                    new_listings=pd.DataFrame(),
                    removed_listings=pd.DataFrame(),
                    first_run=True,
                )
                send_telegram_message(telegram_token, telegram_chat_id, msg)
                print("[OK] Mensaje enviado a Telegram.")
            return

        previous_day = next((d for d in dates if d != today), None)
        if not previous_day:
            print("[INFO] Solo hay datos del dia actual. Ejecuta manana para comparacion.")
            if telegram_token and telegram_chat_id:
                msg = build_telegram_message(
                    today=today,
                    listings_count=len(listings),
                    previous_day=None,
                    changes=pd.DataFrame(),
                    new_listings=pd.DataFrame(),
                    removed_listings=pd.DataFrame(),
                    first_run=True,
                )
                send_telegram_message(telegram_token, telegram_chat_id, msg)
                print("[OK] Mensaje enviado a Telegram.")
            return

        changes, new_listings, removed_listings = compare_days(conn, today, previous_day)
        generate_reports(reports_dir, today, changes, new_listings, removed_listings)

        print(
            f"[OK] Resumen ({today} vs {previous_day}) -> "
            f"Cambios: {len(changes)}, Nuevos: {len(new_listings)}, Retirados: {len(removed_listings)}"
        )
        if telegram_token and telegram_chat_id:
            msg = build_telegram_message(
                today=today,
                listings_count=len(listings),
                previous_day=previous_day,
                changes=changes,
                new_listings=new_listings,
                removed_listings=removed_listings,
                first_run=False,
            )
            send_telegram_message(telegram_token, telegram_chat_id, msg)
            print("[OK] Mensaje enviado a Telegram.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
