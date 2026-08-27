from __future__ import annotations

import hashlib
import math
import re

TOKEN = re.compile(r"[a-z0-9]+")
EMBED_DIM = 256


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def embed_text(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Stable hashed bag-of-words vector. No extra packages, no network."""
    vector = [0.0] * dim
    tokens = tokenize(text)
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.md5(token.encode("utf-8")).hexdigest()
        index = int(digest, 16) % dim
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return float(sum(a * b for a, b in zip(left, right, strict=False)))
