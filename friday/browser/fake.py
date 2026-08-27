from __future__ import annotations

from pathlib import Path

from friday.browser.types import (
    BrowserActionResult,
    PageContent,
    SearchHit,
    SearchResult,
    TabInfo,
)


class FakeBrowser:
    """In-memory browser for tests. Does not launch Playwright or a real window."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.hits: list[SearchHit] = [
            SearchHit(
                title="Welcome to Python.org",
                url="https://www.python.org/",
                snippet="The official home of the Python Programming Language.",
            ),
            SearchHit(
                title="Python (programming language)",
                url="https://en.wikipedia.org/wiki/Python_(programming_language)",
                snippet="Python is a high-level programming language.",
            ),
        ]
        self.page = PageContent(
            url="https://example.com/",
            title="Example Domain",
            text="This domain is for use in illustrative examples in documents.",
            extracted=True,
        )
        self.last_url = self.page.url
        self.fail_search = False
        self.fail_open = False
        self._tabs: list[TabInfo] = [
            TabInfo(index=0, url=self.page.url, title=self.page.title)
        ]

    def search(self, query: str) -> SearchResult:
        self.calls.append(("search", query))
        page_url = "https://www.bing.com/search?q=" + query.replace(" ", "+")
        self.last_url = page_url
        if self.fail_search:
            return SearchResult(query=query, page_url=page_url, hits=[], extracted=True)
        return SearchResult(query=query, page_url=page_url, hits=list(self.hits), title="search")

    def open_url(self, url: str) -> PageContent:
        self.calls.append(("open_url", url))
        if self.fail_open:
            return PageContent(url=url, title="", text="", extracted=False)
        self.last_url = url
        return PageContent(
            url=url,
            title=self.page.title,
            text=self.page.text,
            extracted=True,
        )

    def read(self, url: str | None = None) -> PageContent:
        target = url or self.last_url
        self.calls.append(("read", target))
        return PageContent(
            url=target or self.page.url,
            title=self.page.title,
            text=self.page.text,
            extracted=True,
        )

    def click(self, target: str) -> BrowserActionResult:
        self.calls.append(("click", target))
        return BrowserActionResult(ok=True, reply=f"Clicked {target}.", url=self.last_url or "")

    def fill(self, target: str, value: str) -> BrowserActionResult:
        self.calls.append(("fill", target, value))
        return BrowserActionResult(ok=True, reply=f"Filled {target}.", url=self.last_url or "")

    def download(self, target: str, dest_dir: str) -> BrowserActionResult:
        self.calls.append(("download", target, dest_dir))
        path = Path(dest_dir) / "download.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ok")
        return BrowserActionResult(
            ok=True,
            reply=f"Downloaded {path.name} to {path.parent}.",
            url=self.last_url or "",
            path=str(path),
        )

    def tabs(self, url: str | None = None) -> list[TabInfo]:
        self.calls.append(("tabs", url))
        if url:
            tab = TabInfo(index=len(self._tabs), url=url, title="New Tab")
            self._tabs.append(tab)
            self.last_url = url
        return list(self._tabs)

    def close(self) -> None:
        self.calls.append(("close",))
