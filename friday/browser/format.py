from __future__ import annotations

from friday.browser.types import PageContent, SearchResult

_ORDINALS = ("First", "Second", "Third", "Fourth", "Fifth")
_SNIPPET_LIMIT = 140
_READ_LIMIT = 400


def format_search(result: SearchResult) -> str:
    query = result.query.strip() or "that"
    if not result.hits:
        if not result.extracted:
            return f"I opened a web search for {query} in your browser."
        return f"I couldn't find web results for {query}."

    shown = result.hits[:3]
    parts = [f"I found {len(result.hits)} results for {query}."]
    for index, hit in enumerate(shown):
        label = _ORDINALS[index]
        snippet = _clip(hit.snippet, _SNIPPET_LIMIT)
        if snippet:
            parts.append(f"{label}: {hit.title}. {snippet}")
        else:
            parts.append(f"{label}: {hit.title}.")
    return " ".join(parts)


def format_open(page: PageContent) -> str:
    if not page.url:
        return "I couldn't open that page."
    title = page.title.strip()
    if title:
        return f"Opened {title}."
    if not page.extracted:
        return "I opened that page in your browser."
    return f"Opened {page.url}."


def format_read(page: PageContent) -> str:
    if not page.url and not page.text:
        return "There is no page to read yet. Search the web or go to a site first."
    title = page.title.strip()
    body = _clip(page.text, _READ_LIMIT)
    if not body:
        if not page.extracted:
            return "I opened the page, but I need Playwright to read the text."
        if title:
            return f"The page is titled {title}, but I couldn't read any text."
        return "I couldn't read any text on that page."
    if title:
        return f"{title}. {body}"
    return body


def _clip(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"
