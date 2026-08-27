"""Say the assistant's name the way users say the wake word.

English SAPI voices already say "Friday" correctly. Hindi voices otherwise
read the English spelling as the weekday or letter-by-letter. Hindi TTS
gets a two-syllable form, फ्राय डे (fry + day). The UI still shows Friday.
"""

from __future__ import annotations

import re

# फ्राय डे — fry + day. Avoid फ्राइडे, which TTS often says as "frid-ay".
_HINDI_NAME = "\u092b\u094d\u0930\u093e\u092f \u0921\u0947"

# Two syllables, long "I". Stops Latin voices saying "Frid-ay".
_LATIN_NAME = "Fry-day"

_LATIN_NAMES = {
    "es": "Fr\u00e1idei",
    "fr": "Frayd\u00e9",
    "de": "Fraidei",
    "it": "Fr\u00e0idei",
    "pt": "Fr\u00e1idei",
    "ru": "\u0424\u0440\u0430\u0439\u0434\u0435\u0439",
    "ar": "\u0641\u0631\u0627\u064a\u062f\u064a",
    "ja": "\u30d5\u30e9\u30a4\u30c7\u30fc",
    "ko": "\ud504\ub77c\uc774\ub370\uc774",
    "zh": "\u5f17\u83b1\u8fea",
}

_NAME = re.compile(r"\bfriday(?:'s)?\b", re.IGNORECASE)
_DEVANAGARI_NAMES = (
    "\u092b\u094d\u0930\u093e\u0907\u0921\u0947",  # फ्राइडे
    "\u092b\u094d\u0930\u093e\u092f\u0921\u0947",  # फ्रायडे
    "\u092b\u094d\u0930\u093e\u0908\u0921\u0947",  # फ्राईडे
    "\u092b\u094d\u0930\u093e\u092f \u0921\u0947",  # फ्राय डे
)


def silent_onecore_sapi_token(sample: str) -> bool:
    """True for OneCore tokens registered under SAPI. They do not play audio."""
    blob = (sample or "").lower()
    return "mstts_v110_" in blob or "speech_onecore" in blob


_INDIC_VOICE = (
    "hemant",
    "kalpana",
    "hindi",
    "hi-in",
    "hiin",
    "devanagari",
    "marathi",
    "bengali",
)


def voice_looks_indic(voices: list, voice_id: str | None, hi_hint: str = "") -> bool:
    """True when the selected SAPI voice is Hindi (or another Indic voice)."""
    if not voice_id:
        return False
    hint = (hi_hint or "").strip().lower()
    for voice in voices:
        if getattr(voice, "id", None) != voice_id:
            continue
        blob = f"{getattr(voice, 'name', '')} {voice_id}".lower()
        if silent_onecore_sapi_token(blob):
            return False
        if hint and hint in blob:
            return True
        return any(token in blob for token in _INDIC_VOICE)
    return False


def spoken_assistant_name(language: str, *, indic_voice: bool = False) -> str | None:
    """Spoken name for this TTS language, or ``None`` to leave English as-is."""
    lang = (language or "en").split("-", 1)[0].lower()
    if indic_voice:
        return _HINDI_NAME
    if lang == "en":
        return None
    if lang == "hi":
        return "Friday"
    return _LATIN_NAMES.get(lang, _LATIN_NAME)


def pronounce_assistant_name(
    text: str,
    language: str,
    *,
    indic_voice: bool = False,
) -> str:
    """Replace Friday / Friday's / फ्राइडे with a form the current voice can say."""
    spoken = spoken_assistant_name(language, indic_voice=indic_voice)
    target = spoken or "Friday"

    def replace(match: re.Match[str]) -> str:
        word = match.group(0)
        if word.lower().endswith("'s"):
            if target == _HINDI_NAME:
                return target + " \u0915\u0940"
            return target + "'s"
        return target

    rewritten = _NAME.sub(replace, text)
    for form in _DEVANAGARI_NAMES:
        if form == target:
            continue
        rewritten = rewritten.replace(form, target)
    return rewritten


def text_for_speech(
    text: str,
    language: str,
    *,
    indic_voice: bool = False,
) -> str:
    """Prepare a reply for the selected voice. English SAPI cannot say Devanagari."""
    from friday.language.romanize import has_devanagari, romanize_devanagari

    spoken = pronounce_assistant_name(text, language, indic_voice=indic_voice)
    if has_devanagari(spoken) and not indic_voice:
        return romanize_devanagari(spoken)
    return spoken
