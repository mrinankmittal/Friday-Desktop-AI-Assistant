from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str = ""


@dataclass
class SearchResult:
    query: str
    page_url: str
    hits: list[SearchHit] = field(default_factory=list)
    title: str = ""
    extracted: bool = True


@dataclass
class PageContent:
    url: str
    title: str = ""
    text: str = ""
    extracted: bool = True


@dataclass
class BrowserActionResult:
    ok: bool
    reply: str
    url: str = ""
    path: str = ""


@dataclass
class TabInfo:
    index: int
    url: str
    title: str = ""


class BrowserDriver(Protocol):
    """Web control surface. Playwright implements this; tests use a fake."""

    name: str

    def search(self, query: str) -> SearchResult: ...

    def open_url(self, url: str) -> PageContent: ...

    def read(self, url: str | None = None) -> PageContent: ...

    def click(self, target: str) -> BrowserActionResult: ...

    def fill(self, target: str, value: str) -> BrowserActionResult: ...

    def download(self, target: str, dest_dir: str) -> BrowserActionResult: ...

    def tabs(self, url: str | None = None) -> list[TabInfo]: ...

    def close(self) -> None: ...
