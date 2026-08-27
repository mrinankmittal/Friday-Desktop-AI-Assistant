from __future__ import annotations

import webbrowser
from urllib.parse import quote_plus

from friday.browser.types import BrowserActionResult, PageContent, SearchResult, TabInfo
from friday.browser.urls import normalize_url

BING_SEARCH = "https://www.bing.com/search?q="


class SystemBrowser:
    """Opens the OS default browser. Cannot extract titles or page text."""

    name = "system"

    def __init__(self) -> None:
        self.last_url: str | None = None

    def search(self, query: str) -> SearchResult:
        page_url = BING_SEARCH + quote_plus(query)
        opened = bool(webbrowser.open(page_url))
        self.last_url = page_url
        return SearchResult(
            query=query,
            page_url=page_url,
            hits=[],
            extracted=False,
            title="search" if opened else "",
        )

    def open_url(self, url: str) -> PageContent:
        target = normalize_url(url) or url
        opened = bool(webbrowser.open(target))
        self.last_url = target
        return PageContent(url=target, title="", text="", extracted=False)

    def read(self, url: str | None = None) -> PageContent:
        target = url or self.last_url or ""
        if target:
            webbrowser.open(target)
        return PageContent(url=target, title="", text="", extracted=False)

    def click(self, target: str) -> BrowserActionResult:
        return BrowserActionResult(
            ok=False,
            reply="Click needs the Playwright browser. Install Playwright for Friday.",
        )

    def fill(self, target: str, value: str) -> BrowserActionResult:
        return BrowserActionResult(
            ok=False,
            reply="Fill needs the Playwright browser. Install Playwright for Friday.",
        )

    def download(self, target: str, dest_dir: str) -> BrowserActionResult:
        del dest_dir
        if target.lower().startswith("http"):
            webbrowser.open(target)
            return BrowserActionResult(
                ok=True,
                reply="Opened the download link in your default browser.",
                url=target,
            )
        return BrowserActionResult(
            ok=False,
            reply="Download needs the Playwright browser for named buttons.",
        )

    def tabs(self, url: str | None = None) -> list[TabInfo]:
        if url:
            target = normalize_url(url) or url
            webbrowser.open(target)
            self.last_url = target
            return [TabInfo(index=0, url=target, title="")]
        return []

    def close(self) -> None:
        return None
