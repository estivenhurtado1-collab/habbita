"""Playwright con menos RAM (Render free / planes pequeños)."""
from __future__ import annotations

import gc
import os
from contextlib import AbstractContextManager
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def is_low_memory() -> bool:
    return bool(
        os.getenv("RENDER")
        or os.getenv("RENDER_SERVICE_ID")
        or os.getenv("LOW_MEMORY", "").lower() in ("1", "true", "yes")
        or os.getenv("ENVIRONMENT", "").lower() == "production"
    )


def scrape_limits() -> dict[str, int]:
    """Límites de scraping según RAM disponible (misma funcionalidad, menos carga)."""
    if is_low_memory():
        return {
            "harvest_multiplier": 2,
            "harvest_floor": 8,
            "max_per_url_cap": 12,
            "max_zone_urls": 1,
            "portal_timeout_default": 40,
            "portal_scrape_extra": 2,
        }
    return {
        "harvest_multiplier": 4,
        "harvest_floor": 20,
        "max_per_url_cap": 30,
        "max_zone_urls": 99,
        "portal_timeout_default": 50,
        "portal_scrape_extra": 10,
    }


def chromium_launch_kwargs() -> dict[str, Any]:
    args = [
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-extensions",
    ]
    if is_low_memory():
        args.extend(
            [
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-sync",
                "--mute-audio",
                "--no-first-run",
                "--disable-hang-monitor",
            ]
        )
    return {"headless": True, "args": args}


def _block_heavy(route, *, block_images: bool = False) -> None:
    rtype = route.request.resource_type
    if rtype in ("media", "font") or (block_images and rtype == "image"):
        route.abort()
    else:
        route.continue_()


def new_browser_context(browser, *, block_media: bool | None = None, block_images: bool | None = None):
    if block_media is None:
        block_media = is_low_memory()
    if block_images is None:
        block_images = is_low_memory()
    low = is_low_memory()
    context = browser.new_context(
        locale="es-CO",
        viewport={"width": 1024 if low else 1280, "height": 600 if low else 720},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    )
    if block_media or block_images:

        def handler(route):
            _block_heavy(route, block_images=block_images)

        context.route("**/*", handler)
    return context


def goto_page(page, url: str, timeout: int | None = None) -> None:
    if timeout is None:
        timeout = 22000 if is_low_memory() else 40000
    page.goto(url, wait_until="domcontentloaded", timeout=timeout)


def brief_lazy_wait(page) -> None:
    """Espera mínima para que lazy-load y SPAs pinten las tarjetas."""
    page.wait_for_timeout(700 if is_low_memory() else 1200)


def ensure_listing_cards(page, selector: str) -> int:
    """Espera tarjetas; hace scroll si la lista carga vacía (común en Render)."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    brief_lazy_wait(page)
    try:
        page.wait_for_selector(selector, timeout=selector_timeout())
    except PlaywrightTimeoutError:
        pass

    count = page.locator(selector).count()
    if count > 0:
        return count

    if not is_low_memory():
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeoutError:
            pass
        count = page.locator(selector).count()
        if count > 0:
            return count

    for _ in range(2 if is_low_memory() else 4):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(scroll_pause_ms())
        count = page.locator(selector).count()
        if count > 0:
            return count
    return count


def page_default_timeout() -> int:
    return 12000 if is_low_memory() else 22000


def selector_timeout() -> int:
    return 14000 if is_low_memory() else 20000


def scroll_pause_ms() -> int:
    return 350 if is_low_memory() else 800


def scroll_rounds_default() -> int:
    return 1 if is_low_memory() else 2


class ScrapeSession(AbstractContextManager["ScrapeSession"]):
    """Un Chromium y una pestaña reutilizada por búsqueda (menos RAM en Render free)."""

    def __init__(self) -> None:
        self._cm: Any = None
        self._playwright: Any = None
        self.browser: Any = None
        self._context: Any = None
        self._page: Any = None

    def __enter__(self) -> "ScrapeSession":
        from playwright.sync_api import sync_playwright

        self._cm = sync_playwright()
        self._playwright = self._cm.__enter__()
        self.browser = self._playwright.chromium.launch(**chromium_launch_kwargs())
        return self

    def _close_page(self) -> None:
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
        self._context = None
        self._page = None

    def __exit__(self, *args: object) -> None:
        self._close_page()
        if self.browser:
            self.browser.close()
            self.browser = None
        if self._cm:
            self._cm.__exit__(*args)
        gc.collect()

    def _ensure_page(self):
        if self._page is None:
            self._context = new_browser_context(self.browser)
            self._page = self._context.new_page()
            self._page.set_default_timeout(page_default_timeout())
        return self._page

    def run_page(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        page = self._ensure_page()
        try:
            return fn(page, *args, **kwargs)
        except Exception:
            self._close_page()
            raise
        finally:
            if is_low_memory():
                try:
                    page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
                except Exception:
                    pass


def search_parallel_enabled() -> bool:
    if os.getenv("SEARCH_SEQUENTIAL", "").lower() in ("1", "true", "yes"):
        return False
    if os.getenv("SEARCH_PARALLEL", "").lower() in ("1", "true", "yes"):
        return True
    return not is_low_memory()


def search_fast_enabled() -> bool:
    return os.getenv("SEARCH_FAST", "0").lower() in ("1", "true", "yes")


def portal_wall_timeout_sec() -> int:
    default = scrape_limits()["portal_timeout_default"]
    try:
        return max(25, int(os.getenv("SEARCH_PORTAL_TIMEOUT", str(default))))
    except ValueError:
        return default
