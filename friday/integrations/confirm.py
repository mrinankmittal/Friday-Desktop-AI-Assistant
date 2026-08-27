"""Voice yes/no for high-risk integration sends."""

from __future__ import annotations

import re

_YES_RE = re.compile(
    r"\b("
    r"yes|yeah|yep|yup|yess|yas|ye|"
    r"ok(?:ay)?|sure|confirm(?:ed)?|"
    r"send(?:\s+it)?|do\s+it|go\s+ahead|"
    r"haan?|han|ji|हाँ|हां|जी"
    r")\b",
    re.IGNORECASE,
)
_YES_EXACT = frozenset(
    {
        "y",
        "ya",
        "ha",
        "हाँ",
        "हां",
        "जी",
        "guess",
        "ye",
        "yess",
        "please",
    }
)
_HARD_NO_RE = re.compile(
    r"\b(don't|dont|do not|cancel|never mind|nevermind|abort|stop)\b",
    re.IGNORECASE,
)
_NO_RE = re.compile(r"\b(no|nope|nah|नहीं|नही|ना)\b", re.IGNORECASE)
_NO_EXACT = frozenset({"n", "नहीं", "नही", "ना"})
_SHORT_REPLIES = frozenset(
    {
        "y",
        "ya",
        "ye",
        "yes",
        "yeah",
        "yep",
        "yup",
        "yess",
        "yas",
        "ok",
        "okay",
        "sure",
        "haan",
        "han",
        "ha",
        "ji",
        "हाँ",
        "हां",
        "जी",
        "नहीं",
        "नही",
        "ना",
        "confirm",
        "confirmed",
        "please",
        "do it",
        "go ahead",
        "send it",
        "send it now",
        "yes send it",
        "yeah send it",
        "sure send it",
        "send",
        "send now",
        "yes sure",
        "sure yes",
        "ok sure",
        "okay sure",
        "n",
        "no",
        "nope",
        "nah",
        "cancel",
        "cancel it",
        "never mind",
        "nevermind",
    }
)


def normalize_voice_text(text: str) -> str:
    cleaned = re.sub(r"[,.!?]+", " ", str(text).strip().lower())
    cleaned = " ".join(cleaned.split())
    while True:
        stripped = re.sub(r"^(?:please|friday|can you)\s+", "", cleaned)
        if stripped == cleaned:
            return cleaned
        cleaned = stripped


def is_short_voice_reply(text: str) -> bool:
    """True for short yes/sure/no replies that must run immediately as commands."""
    return normalize_voice_text(text) in _SHORT_REPLIES


def is_confirm_yes(text: str) -> bool:
    cleaned = " ".join(text.strip().lower().split())
    if not cleaned or is_confirm_no(cleaned):
        return False
    if _YES_RE.search(cleaned) and _NO_RE.search(cleaned):
        return False
    if cleaned in _YES_EXACT:
        return True
    return bool(_YES_RE.search(cleaned))


def is_confirm_no(text: str) -> bool:
    cleaned = " ".join(text.strip().lower().split())
    if not cleaned:
        return False
    if cleaned in _NO_EXACT:
        return True
    if _HARD_NO_RE.search(cleaned):
        return True
    if _YES_RE.search(cleaned) and _NO_RE.search(cleaned):
        return False
    return bool(_NO_RE.search(cleaned))
