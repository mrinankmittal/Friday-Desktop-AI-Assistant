from __future__ import annotations

from friday.memory.names import (
    found_name_reply,
    missing_name_reply,
    name_from_hit,
    name_subject,
)
from friday.memory.settings import MemorySettings
from friday.memory.store import MemoryStore
from friday.memory.types import DocumentInfo, Memory, SearchHit

_store: MemoryStore | None = None
_settings: MemorySettings | None = None


def get_memory_settings() -> MemorySettings:
    global _settings
    if _settings is None:
        _settings = MemorySettings.from_env()
    return _settings


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore(get_memory_settings().db_path)
    return _store


def set_memory_store(store: MemoryStore | None) -> None:
    global _store
    _store = store


def guess_kind(content: str) -> str:
    lowered = content.lower()
    if "prefer" in lowered or "favourite" in lowered or "favorite" in lowered:
        return "preference"
    return "fact"


def format_memory_list(memories: list[Memory]) -> str:
    if not memories:
        return "I don't have any memories yet. Say remember that, then the fact."
    lines = [f"Memory {item.id}: {item.content}" for item in memories[:12]]
    spoken = "Here's what I remember. " + " ".join(lines)
    if len(memories) > 12:
        spoken += f" And {len(memories) - 12} more in Settings."
    return spoken


def format_search_hits(hits: list[SearchHit], query: str = "") -> str:
    subject = name_subject(query)
    if subject is not None:
        if not hits:
            return missing_name_reply(subject)
        for hit in hits:
            name = name_from_hit(hit.text, subject)
            if name:
                return found_name_reply(subject, name)
    if not hits:
        return (
            "I didn't find that in your notes. "
            "Say remember that, then the fact."
        )
    parts: list[str] = []
    for hit in hits[:5]:
        snippet = hit.text.strip()
        if len(snippet) > 220:
            snippet = snippet[:217] + "..."
        if hit.source == "memory":
            parts.append(snippet)
        else:
            parts.append(f"From {hit.title}: {snippet}")
    return "From your notes: " + " ".join(parts)


def format_grounded_prompt(query: str, hits: list[SearchHit]) -> str:
    lines = [
        "Use the following personal notes if they help. Cite file names when you use a document.",
        "",
        "Notes:",
    ]
    for hit in hits:
        label = "memory" if hit.source == "memory" else hit.title
        snippet = hit.text.strip()
        if len(snippet) > 400:
            snippet = snippet[:397] + "..."
        lines.append(f"- ({label}) {snippet}")
    lines.extend(["", f"Question: {query}"])
    return "\n".join(lines)


def grounded_fallback_reply(hits: list[SearchHit], query: str = "") -> str:
    return format_search_hits(hits, query)


CHAT_UNAVAILABLE = "Sorry, I could not reach the chatbot right now."
CHAT_OFFLINE_HELP = (
    "General chat is offline. I can still search your files, take notes, "
    "set reminders, and remember facts."
)


def is_chat_unavailable(reply: str) -> bool:
    text = (reply or "").strip().lower()
    if not text:
        return True
    return (
        text == CHAT_UNAVAILABLE.lower()
        or "could not reach the chatbot" in text
        or "could not reach ollama" in text
        or "chatbot authentication" in text
    )
