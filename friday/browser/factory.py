from __future__ import annotations

import logging

from friday.browser.playwright_driver import PlaywrightBrowser
from friday.browser.settings import BrowserSettings
from friday.browser.system import SystemBrowser
from friday.browser.types import BrowserDriver

logger = logging.getLogger("friday.browser")

_browser: BrowserDriver | None = None


def playwright_importable() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def create_browser(settings: BrowserSettings | None = None) -> BrowserDriver:
    config = settings or BrowserSettings.from_env()
    requested = config.provider
    if requested == "system":
        return SystemBrowser()
    if requested == "playwright":
        if not playwright_importable():
            logger.warning("Playwright is not installed; using the OS browser")
            return SystemBrowser()
        return PlaywrightBrowser(config)
    if playwright_importable():
        return PlaywrightBrowser(config)
    logger.info("Playwright is not installed; web search will open the OS browser")
    return SystemBrowser()


def get_browser() -> BrowserDriver:
    global _browser
    if _browser is None:
        _browser = create_browser()
    return _browser


def set_browser(browser: BrowserDriver | None) -> None:
    """Tests inject a fake. Pass ``None`` to restore the default."""
    global _browser
    _browser = browser
