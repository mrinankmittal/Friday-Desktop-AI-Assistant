"""Post-STT cleanup so spoken commands survive common mishearings.

Google Web Speech often truncates long utterances, swaps homophones
(weather/whether, whatsapp/what's app), or leaves the wake name in the
transcript. This module fixes those patterns and picks the best
alternative when the recognizer returns several.
"""

from __future__ import annotations

import re

from friday.language.bilingual import normalize_command

# Strip wake name and polite lead-ins once STT has already fired.
_LEADING_WAKE = re.compile(
    r"^(?:"
    r"(?:hey|ok|okay|hi|hello|please|can you|could you|would you|"
    r"i want you to|i want to|i would like you to|i would like to)\s+)*"
    r"(?:friday|for day|fried egg|friday'?s?)\s+",
    re.IGNORECASE,
)
_TRAILING_WAKE = re.compile(r"\s+(?:friday|for day)\s*$", re.IGNORECASE)

# Keep in sync with friday.files.create — inlined here to avoid importing
# friday.files (that package pulls memory → providers → stt → stt_fix).
_CPP_SPOKEN = re.compile(
    r"(?:(?<=\s)|^)(?:c\s*\+\s*\+|c\s+plus\s+plus|see\s+plus\s+plus)(?=\s|$)",
    re.IGNORECASE,
)

# Whole-phrase fixes before word-level passes.
_PHRASE_FIXES: tuple[tuple[str, str], ...] = (
    (r"\bwhat'?s app\b", "whatsapp"),
    (r"\bwhat app\b", "whatsapp"),
    (r"\bwhats app\b", "whatsapp"),
    (r"\byou tube\b", "youtube"),
    (r"\bu tube\b", "youtube"),
    (r"\bscreen shot\b", "screenshot"),
    (r"\bscreen short\b", "screenshot"),
    (r"\bnote pad\b", "notepad"),
    (r"\btask mgr\b", "task manager"),
    (r"\btax manager\b", "task manager"),
    (r"\bopen up\b", "open"),
    (r"\bgo to\b", "go to"),  # anchor — kept for spacing normalization
    (r"\blist the windows\b", "list of windows"),
    (r"\blist windows\b", "list of windows"),
    (r"\blist processes\b", "list of processes"),
    (r"\btake screenshot\b", "take a screenshot"),
    (r"\btake the screenshot\b", "take a screenshot"),
    (r"\bsend a message\b", "send message"),
    (r"\bcent message\b", "send message"),
    (r"\bwhat is my ip\b", "what's my ip"),
    (r"\bwhat is the weather\b", "what's the weather"),
    (r"\bwhat is the news\b", "what's the news"),
    (r"\bone calendar\b", "one calendar"),
    (r"\bcalender\b", "calendar"),
    (r"\bsearch the web\b", "search the web for"),
)

# Replace only when the next token suggests a command, not chat.
_WEATHER_CONTEXT = re.compile(
    r"\bwhether\b(?=\s+(?:in|today|tomorrow|now|like|is|for)\b)",
    re.IGNORECASE,
)

_COMMAND_HINTS = re.compile(
    r"\b("
    r"open|close|play|pause|next|previous|stop|search|google|send|call|"
    r"weather|news|screenshot|remember|remind|task|calendar|copy|paste|"
    r"write|read|list|explain|research|download|click|fill|compile|"
    r"whatsapp|youtube|chrome|notepad|spotify|email|message|windows|"
    r"processes|screenshot|online|info|folder|file|note|tasks"
    r")\b",
    re.IGNORECASE,
)


def fix_transcript(text: str) -> str:
    """Normalize a raw STT string before command routing."""
    cleaned = " ".join(str(text or "").strip().split())
    if not cleaned:
        return cleaned

    cleaned = _LEADING_WAKE.sub("", cleaned)
    cleaned = _TRAILING_WAKE.sub("", cleaned).strip()
    cleaned = _CPP_SPOKEN.sub("cpp", " ".join(cleaned.lower().split()))

    for pattern, replacement in _PHRASE_FIXES:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

    cleaned = _WEATHER_CONTEXT.sub("weather", cleaned)
    cleaned = normalize_command(cleaned)
    return " ".join(cleaned.split())


def score_for_command(text: str) -> int:
    """Higher means the transcript looks like a Friday command."""
    fixed = fix_transcript(text)
    if not fixed:
        return -1

    score = min(len(fixed), 80)
    hints = _COMMAND_HINTS.findall(fixed)
    score += 25 * len(hints)

    try:
        from friday.orchestrator.intents import classify_rules
        from friday.orchestrator.models import IntentName

        intent = classify_rules(fixed)
        if intent.name is not IntentName.CHAT:
            score += 120
    except Exception:
        pass
    return score


def pick_best_transcript(candidates: list[str]) -> str:
    """Choose the transcript most likely to be the intended command."""
    ranked = [str(item).strip() for item in candidates if str(item).strip()]
    if not ranked:
        return ""
    if len(ranked) == 1:
        return fix_transcript(ranked[0])
    best = max(ranked, key=score_for_command)
    return fix_transcript(best)
