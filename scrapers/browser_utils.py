"""Playwright con menos RAM (Render / planes pequeños)."""
from __future__ import annotations

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


def chromium_launch_kwargs() -> dict[str, Any]:
    return {
        "headless": True,
        "args": [
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--disable-extensions",
        ],
    }


def _block_heavy(route) -> None:
    # No bloquear imágenes: muchos portales rellenan src con lazy-load al descargarlas
    if route.request.resource_type in ("media", "font"):
        route.abort()
    else:
        route.continue_()


def new_browser_context(browser, *, block_media: bool | None = None):
    if block_media is None:
        block_media = is_low_memory()
    context = browser.new_context(
        locale="es-CO",
        viewport={"width": 1280, "height": 720},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    )
    if block_media:
        context.route("**/*", _block_heavy)
    return context


def goto_page(page, url: str, timeout: int | None = None) -> None:
    if timeout is None:
        timeout = 14000 if is_low_memory() else 28000
    page.goto(url, wait_until="commit", timeout=timeout)


def brief_lazy_wait(page) -> None:
    """Espera mínima para que lazy-load rellene data-src/src."""
    page.wait_for_timeout(450 if is_low_memory() else 700)


def page_default_timeout() -> int:
    return 12000 if is_low_memory() else 22000


def selector_timeout() -> int:
    return 8000 if is_low_memory() else 14000


def scroll_pause_ms() -> int:
    return 350 if is_low_memory() else 800


def scroll_rounds_default() -> int:
    return 1 if is_low_memory() else 2


class ScrapeSession(AbstractContextManager["ScrapeSession"]):
    """Un solo Chromium por búsqueda (evita ~8–15 s de arranque por portal/URL)."""

    def __init__(self) -> None:
        self._cm: Any = None
        self._playwright: Any = None
        self.browser: Any = None

    def __enter__(self) -> "ScrapeSession":
        from playwright.sync_api import sync_playwright

        self._cm = sync_playwright()
        self._playwright = self._cm.__enter__()
        self.browser = self._playwright.chromium.launch(**chromium_launch_kwargs())
        return self

    def __exit__(self, *args: object) -> None:
        if self.browser:
            self.browser.close()
            self.browser = None
        if self._cm:
            self._cm.__exit__(*args)

    def run_page(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        context = new_browser_context(self.browser)
        page = context.new_page()
        page.set_default_timeout(page_default_timeout())
        try:
            return fn(page, *args, **kwargs)
        finally:
            context.close()


def search_parallel_enabled() -> bool:
    if os.getenv("SEARCH_SEQUENTIAL", "").lower() in ("1", "true", "yes"):
        return False
    if os.getenv("SEARCH_PARALLEL", "").lower() in ("1", "true", "yes"):
        return True
    # Paralelo por defecto fuera de modo low-memory (p. ej. local o plan 2GB)
    return not is_low_memory()


def search_fast_enabled() -> bool:
    return os.getenv("SEARCH_FAST", "1").lower() in ("1", "true", "yes")


def portal_wall_timeout_sec() -> int:
    try:
        return max(18, int(os.getenv("SEARCH_PORTAL_TIMEOUT", "28")))
    except ValueError:
        return 28
