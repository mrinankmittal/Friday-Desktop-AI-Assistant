from __future__ import annotations

import base64
import re
from urllib.parse import parse_qs, unquote, urlparse

_SCHEME = re.compile(r"^https?://", re.IGNORECASE)
_HOST_LIKE = re.compile(
    r"^(?:www\.)?[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z]{2,})+(?:[/:?#].*)?$",
    re.IGNORECASE,
)
_BLOCKED_SCHEMES = frozenset({"javascript", "data", "file", "vbscript", "about"})


def looks_like_url(text: str) -> bool:
    cleaned = _strip_wrapping(text)
    if not cleaned or " " in cleaned:
        return False
    if _SCHEME.match(cleaned):
        return True
    return bool(_HOST_LIKE.match(cleaned))


def normalize_url(raw: str) -> str | None:
    """Return an http(s) URL, or None if the value is not a safe web address."""
    cleaned = _strip_wrapping(raw)
    if not cleaned:
        return None

    if not _SCHEME.match(cleaned):
        if not _HOST_LIKE.match(cleaned):
            return None
        cleaned = "https://" + cleaned

    parsed = urlparse(cleaned)
    scheme = (parsed.scheme or "").lower()
    if scheme in _BLOCKED_SCHEMES:
        return None
    if scheme not in {"http", "https"}:
        return None
    if not parsed.netloc or parsed.netloc in {".", ".."}:
        return None
    return cleaned


def unwrap_redirect(href: str) -> str:
    """Follow DuckDuckGo ``uddg=`` and Bing ``/ck/`` wrappers to the destination URL."""
    if not href:
        return ""
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    wrapped = query.get("uddg") or query.get("udg")
    if wrapped:
        return unquote(wrapped[0])
    host = (parsed.netloc or "").lower()
    if "bing.com" in host and parsed.path.startswith("/ck/"):
        encoded = (query.get("u") or [""])[0]
        decoded = _decode_bing_u(encoded)
        if decoded:
            return decoded
    return href


def _decode_bing_u(value: str) -> str:
    raw = value.strip()
    if raw.startswith("a1"):
        raw = raw[2:]
    if not raw:
        return ""
    padded = raw + "=" * (-len(raw) % 4)
    try:
        decoded = base64.b64decode(padded).decode("utf-8")
    except Exception:
        return ""
    return decoded if decoded.lower().startswith("http") else ""


def _strip_wrapping(text: str) -> str:
    cleaned = text.strip().strip("\"'").rstrip(".,)!?")
    return cleaned.strip()
