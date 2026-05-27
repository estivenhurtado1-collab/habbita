"""Playwright con menos RAM (Render / planes pequeños)."""
from __future__ import annotations

import os
from typing import Any


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
    if route.request.resource_type in ("image", "media", "font"):
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


def goto_page(page, url: str, timeout: int = 90000) -> None:
    wait_until = "domcontentloaded" if is_low_memory() else "networkidle"
    page.goto(url, wait_until=wait_until, timeout=timeout)
