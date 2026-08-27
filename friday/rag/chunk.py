from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def chunk_text(text: str, size: int = 400, overlap: int = 80) -> list[str]:
    cleaned = _WHITESPACE.sub(" ", text).strip()
    if not cleaned:
        return []
    if len(cleaned) <= size:
        return [cleaned]
    if overlap >= size:
        overlap = max(size // 5, 1)

    chunks: list[str] = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(start + size, length)
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start = end - overlap
    return chunks
