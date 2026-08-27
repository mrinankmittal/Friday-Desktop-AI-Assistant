"""Multi-source research helpers for spoken reports."""

from __future__ import annotations

from friday.browser.types import BrowserDriver, SearchHit
from friday.memory.store import MemoryStore
from friday.memory.types import SearchHit as DocHit
from friday.providers.llm import complete_chat

_MAX_SOURCES = 3
_PAGE_CHARS = 1200


def web_research_report(query: str, browser: BrowserDriver) -> str:
    cleaned = query.strip()
    if not cleaned:
        return "What should I research?"
    result = browser.search(cleaned)
    hits = list(result.hits[:_MAX_SOURCES])
    if not hits:
        return f"I couldn't find web results for {cleaned}."

    sources: list[tuple[SearchHit, str]] = []
    for hit in hits:
        text = ""
        try:
            page = browser.read(hit.url)
            text = (page.text or "").strip()
        except Exception:
            text = hit.snippet or ""
        if len(text) > _PAGE_CHARS:
            text = text[:_PAGE_CHARS] + "..."
        sources.append((hit, text or hit.snippet or ""))

    bullets = []
    for index, (hit, text) in enumerate(sources, start=1):
        bullets.append(
            f"[{index}] {hit.title} ({hit.url})\n{text or '(no extract)'}"
        )
    prompt = (
        f"Write a short spoken research brief on: {cleaned}\n"
        "Use only the sources below. Mention source numbers like source 1. "
        "At most 5 short sentences, then one sentence listing the sources.\n\n"
        + "\n\n".join(bullets)
    )
    try:
        reply = complete_chat(prompt).strip()
    except Exception:
        reply = ""
    if reply:
        return reply
    # Offline / LLM failure fallback with citations.
    lines = [f"Quick findings for {cleaned}."]
    for index, (hit, text) in enumerate(sources, start=1):
        snippet = (text or hit.snippet or hit.title).split(". ")[0][:160]
        lines.append(f"Source {index}, {hit.title}: {snippet}.")
    return " ".join(lines)


def docs_research_report(query: str, memory: MemoryStore) -> str:
    cleaned = query.strip()
    if not cleaned:
        return "What should I look up in your documents?"
    hits: list[DocHit] = memory.search(cleaned, limit=_MAX_SOURCES)
    if not hits:
        return (
            f"I didn't find that in your documents. "
            f"Say ingest a file first, then ask again."
        )
    bullets = []
    for index, hit in enumerate(hits, start=1):
        label = hit.title or hit.source or "document"
        text = hit.text.strip()
        if len(text) > _PAGE_CHARS:
            text = text[:_PAGE_CHARS] + "..."
        bullets.append(f"[{index}] {label}\n{text}")
    prompt = (
        f"Summarize the user's documents for: {cleaned}\n"
        "Cite sources by number. Keep it under 5 short spoken sentences.\n\n"
        + "\n\n".join(bullets)
    )
    try:
        reply = complete_chat(prompt).strip()
    except Exception:
        reply = ""
    if reply:
        return reply
    parts = [f"From your documents about {cleaned}:"]
    for index, hit in enumerate(hits, start=1):
        label = hit.title or hit.source or "document"
        snippet = hit.text.strip().split(". ")[0][:140]
        parts.append(f"Source {index} ({label}): {snippet}.")
    return " ".join(parts)
