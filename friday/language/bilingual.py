"""Hindi + English listening, speaking, and command phrasing.

Google STT takes one language code per call, and the English command router
only matches ASCII phrases. This module turns mixed Hindi / Hinglish speech
into those English command shapes without changing English utterances.
"""

from __future__ import annotations

import re

from friday.language.pronounce import silent_onecore_sapi_token

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_WAKE_HI = re.compile(r"फ्राइडे|फ्रायडे")
_ENGLISH_COMMAND = re.compile(
    r"\b("
    r"open|close|play|pause|next|previous|weather|forecast|news|headlines|"
    r"screenshot|write|type|send|call|search|google|chrome|notepad|spotify|"
    r"whatsapp|youtube|exit|stop|copy|paste"
    r")\b",
    re.IGNORECASE,
)
_HINGLISH = re.compile(
    r"\b("
    r"kholo|khol|batao|bata|chalao|chala|likho|likh|"
    r"mausam|gaana|gana|khabar|khabrein|samachar|"
    r"bhejo|karo|ruk|sunna|kya|kaise|haal|theek|namaste"
    r")\b",
    re.IGNORECASE,
)
# Real Hindi — not English words written in देवनागरी ("हाउ आर यू").
_NATURAL_HINDI = re.compile(
    r"(क्या|कैसे|क्यों|कहाँ|कब|कौन|हाल|हूँ|हूं|हैं|है|हो|था|थे|"
    r"कर|रही|रहा|रहे|खोलो|बताओ|चलाओ|लिखो|मौसम|गाना|समाचार|खबर|"
    r"और|तुम|तुम्हारे|मैं|आप|हम|ठीक|धन्यवाद|नमस्ते|राम|"
    r"कृपया|बंद|रुक|सुन|मदद|चाहिए|सकता|सकती|आज|कल|"
    r"यहाँ|वहाँ|यह|वह|नहीं|हाँ|जी|अच्छा|बहुत)"
)
_FILE_WRITE = re.compile(r"\bto file\b", re.IGNORECASE)
_LEADING_POLITE = re.compile(
    r"^(?:कृपया|please|friday|can you|i want you to|i want to)\s+",
    re.IGNORECASE,
)

# Longest match first.
_APP_ALIASES: tuple[tuple[str, str], ...] = (
    ("गूगल क्रोम", "chrome"),
    ("google chrome", "chrome"),
    ("नोट पैड", "notepad"),
    ("note pad", "notepad"),
    ("whats app", "whatsapp"),
    ("व्हाट्स ऐप", "whatsapp"),
    ("व्हाट्सएप", "whatsapp"),
    ("वॉट्सएप", "whatsapp"),
    ("नोटपैड", "notepad"),
    ("स्पॉटिफाई", "spotify"),
    ("स्पोटिफाई", "spotify"),
    ("पावरपॉइंट", "powerpoint"),
    ("यूट्यूब", "youtube"),
    ("क्रोम", "chrome"),
    ("वर्ड", "word"),
    ("एक्सेल", "excel"),
    ("टेलीग्राम", "telegram"),
    ("डिस्कॉर्ड", "discord"),
)

_CITY_ALIASES: tuple[tuple[str, str], ...] = (
    ("नई दिल्ली", "delhi"),
    ("new delhi", "delhi"),
    ("बेंगलुरु", "bengaluru"),
    ("बैंगलोर", "bangalore"),
    ("हैदराबाद", "hyderabad"),
    ("चेन्नई", "chennai"),
    ("कोलकाता", "kolkata"),
    ("अहमदाबाद", "ahmedabad"),
    ("लखनऊ", "lucknow"),
    ("दिल्ली", "delhi"),
    ("मुंबई", "mumbai"),
    ("पुणे", "pune"),
    ("जयपुर", "jaipur"),
    ("नोएडा", "noida"),
    ("गुड़गांव", "gurugram"),
    ("गुरुग्राम", "gurugram"),
    ("गोवा", "goa"),
)

_NEWS_ALIASES: tuple[tuple[str, str], ...] = (
    ("मनोरंजन", "entertainment"),
    ("व्यापार", "business"),
    ("तकनीक", "tech"),
    ("स्वास्थ्य", "health"),
    ("विज्ञान", "science"),
    ("दुनिया", "world"),
    ("भारत", "india"),
    ("खेल", "sports"),
)

_HI_REPLIES = {
    "sorry, i missed that. please say the command again.": "सुना नहीं, एक बार और बोलोगे?",
    "stopping voice control": "ठीक है, रुक रही हूँ।",
}
_OPENING = re.compile(r"^opening (.+?)(?:\.)?$")

_user_language = "en"


def parse_stt_languages(raw: str) -> list[str]:
    """Split ``hi-IN,en-IN`` (or semicolon / pipe) into Google language codes."""
    parts: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[,;|]+", raw or ""):
        lang = part.strip()
        if not lang:
            continue
        key = lang.lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append(lang)
    return parts or ["en-in"]


def whisper_language_code(raw: str) -> str | None:
    """Whisper language, or ``None`` to auto-detect mixed Hindi and English."""
    langs = parse_stt_languages(raw)
    codes = {lang.split("-", 1)[0].lower() for lang in langs}
    if not codes or "auto" in codes or "multi" in codes or len(codes) > 1:
        return None
    return next(iter(codes))


def fallback_stt_language(language: str) -> str:
    """Second-pass language when Google returns unknown."""
    langs = parse_stt_languages(language)
    if len(langs) > 1:
        return "en-US"
    first = langs[0].lower()
    if first.startswith("en-in"):
        return "en-US"
    if first.startswith("en-us"):
        return "en-IN"
    if first.startswith("hi"):
        return "en-IN"
    return language


def score_transcript(text: str) -> int:
    sample = (text or "").strip()
    if not sample:
        return -1
    score = min(len(sample), 60)
    if _DEVANAGARI.search(sample):
        score += 25
    if _ENGLISH_COMMAND.search(sample):
        score += 30
    if _HINGLISH.search(sample):
        score += 30
    if any(marker in sample for marker in ("खोलो", "बताओ", "चलाओ", "लिखो", "मौसम")):
        score += 25
    return score


def pick_transcript(candidates: list[str]) -> str:
    """Choose the best of several language-specific transcripts of one clip.

    English spoken into the Hindi recognizer comes back as देवनागरी spellings
    of English ("हाउ आर यू डूइंग", "फ्राइडे कैन यू हियर मी"). Prefer the
    Latin English transcript then. Real Hindi still wins over Hinglish Latin.
    """
    ranked = [item.strip() for item in candidates if str(item).strip()]
    if not ranked:
        return ""
    if len(ranked) == 1:
        return ranked[0]

    latin = [item for item in ranked if item and not has_devanagari(item)]
    hindi = [item for item in ranked if is_natural_hindi(item)]
    if hindi:
        return max(hindi, key=score_transcript)
    if latin:
        return max(latin, key=score_transcript)
    return max(ranked, key=score_transcript)


def has_devanagari(text: str) -> bool:
    return bool(_DEVANAGARI.search(text or ""))


def is_natural_hindi(text: str) -> bool:
    """True for real Hindi, not English words written in देवनागरी.

    The wake name फ्राइडे alone must not mark an English utterance as Hindi.
    """
    sample = str(text or "")
    if not has_devanagari(sample):
        return False
    without_wake = _WAKE_HI.sub(" ", sample)
    return bool(_NATURAL_HINDI.search(without_wake))


def is_phonetic_english_devanagari(text: str) -> bool:
    """English spoken into the Hindi recognizer, e.g. हाउ आर यू / कैन यू हियर मी."""
    sample = str(text or "")
    return bool(has_devanagari(sample) and not is_natural_hindi(sample))


def detect_language(text: str) -> str:
    """Language of this turn only. English and Hindi stay independent."""
    sample = str(text or "")
    if is_phonetic_english_devanagari(sample):
        return "en"
    if is_natural_hindi(sample) or _HINGLISH.search(sample):
        return "hi"
    return "en"


def set_user_language(language: str) -> None:
    global _user_language
    _user_language = "hi" if str(language).lower().startswith("hi") else "en"


def user_language() -> str:
    return _user_language


def reset_user_language() -> None:
    global _user_language
    _user_language = "en"


def speak_language_for(text: str) -> str:
    """Speak this reply in its own language; fall back to this turn's language."""
    if is_natural_hindi(text):
        return "hi"
    if is_phonetic_english_devanagari(text):
        return "en"
    if has_devanagari(text):
        return "hi"
    return user_language()


def localize_reply(text: str, language: str | None = None) -> str:
    lang = (language or user_language() or "en").split("-", 1)[0].lower()
    if lang != "hi":
        return text
    key = " ".join(str(text).strip().lower().split())
    mapped = _HI_REPLIES.get(key)
    if mapped:
        return mapped
    opened = _OPENING.match(key)
    if opened:
        return f"{opened.group(1).strip()} खोल रही हूँ।"
    return text


def is_wake_transcript(transcript: str) -> bool:
    sample = str(transcript or "")
    return bool(re.search(r"\bfriday\b", sample, re.I) or _WAKE_HI.search(sample))


def pick_tts_voice_id(
    voices: list,
    language: str,
    *,
    hi_hint: str = "",
    en_hint: str = "",
) -> str | None:
    """Pick a SAPI voice. English keeps the old index-1 default unless hinted."""
    if not voices:
        return None
    lang = (language or "en").split("-", 1)[0].lower()

    def blob(voice: object) -> str:
        return f"{getattr(voice, 'name', '')} {getattr(voice, 'id', '')}".lower()

    def first_matching(hints: tuple[str, ...]) -> str | None:
        for hint in hints:
            needle = (hint or "").strip().lower()
            if not needle:
                continue
            for voice in voices:
                if needle in blob(voice):
                    return voice.id
        return None

    if lang == "hi":
        found = find_indic_voice_id(voices, hi_hint=hi_hint)
        if found:
            return found
    found = first_matching((en_hint, "zira"))
    if found:
        return found
    return voices[1].id if len(voices) > 1 else voices[0].id


def find_indic_voice_id(voices: list, *, hi_hint: str = "") -> str | None:
    """Classic SAPI Hindi voice, or None.

    OneCore voices (Kalpana/Hemant copied into SAPI) show up in the list but
    stay silent through pyttsx3, so they are not treated as usable here.
    """
    if not voices:
        return None

    def blob(voice: object) -> str:
        return f"{getattr(voice, 'name', '')} {getattr(voice, 'id', '')}".lower()

    hints = (hi_hint, "kalpana", "hemant", "hindi", "hi-in", "hiin")
    for hint in hints:
        needle = (hint or "").strip().lower()
        if not needle:
            continue
        for voice in voices:
            sample = blob(voice)
            if silent_onecore_sapi_token(sample):
                continue
            if needle in sample and "english" not in sample:
                return voice.id
    return None


def normalize_command(query: str) -> str:
    """Map Hindi / Hinglish command phrases onto the English router."""
    text = " ".join(str(query).strip().split())
    if not text or _FILE_WRITE.search(text):
        return text

    lowered = text.lower()
    if re.fullmatch(r"(हाँ|हां|जी|जी हाँ|जी हां|haan|han)", lowered):
        return "yes"
    if re.fullmatch(r"(नहीं|नही|ना)", text) or lowered in {"nahi", "nahin"}:
        return "no"

    if has_devanagari(text) or _HINGLISH.search(text):
        while True:
            stripped = _LEADING_POLITE.sub("", text)
            if stripped == text:
                break
            text = stripped.strip()

    text = _replace_pairs(text, _APP_ALIASES)
    text = _apply_templates(text)
    if re.search(r"\bweather\b", text, re.I):
        text = _replace_pairs(text, _CITY_ALIASES)
    if re.search(r"\b(news|headlines)\b", text, re.I):
        text = _replace_pairs(text, _NEWS_ALIASES)
    return " ".join(text.split())


def _replace_pairs(text: str, pairs: tuple[tuple[str, str], ...]) -> str:
    for source, dest in pairs:
        text = re.sub(re.escape(source), dest, text, flags=re.IGNORECASE)
    return text


def _apply_templates(text: str) -> str:
    replacements: tuple[tuple[str, str], ...] = (
        (
            r"^(.+?)\s+(?:youtube|यूट्यूब)\s+(?:par|pe|on|पर)\s+"
            r"(?:chalao|chala\s+do|play|चलाओ)\s*$",
            r"play \1 on youtube",
        ),
        (
            r"^(?:youtube|यूट्यूब)\s+(?:par|pe|on|पर)\s+(.+?)\s+"
            r"(?:chalao|chala\s+do|play|चलाओ)\s*$",
            r"play \1 on youtube",
        ),
        (
            r"^(?:google|गूगल)\s+(?:par|pe|on|पर)\s+"
            r"(?:search|serch|सर्च)\s+(?:karo|kar\s+do|करो)\s+(.+)$",
            r"search the web for \1",
        ),
        (
            r"^(.+?)\s+(?:ko\s+|को\s+)?(?:google|गूगल)\s+(?:par|pe|on|पर)\s+"
            r"(?:search|सर्च)\s+(?:karo|करो)\s*$",
            r"search the web for \1",
        ),
        (
            r"^(?:आज\s+(?:का\s+|की\s+)?)?मौसम(?:\s+कैसा\s+है)?(?:\s+बताओ)?"
            r"\s+(.+?)\s+में\s*$",
            r"weather in \1",
        ),
        (
            r"^(?:आज\s+(?:का\s+|की\s+)?)?मौसम(?:\s+कैसा\s+है)?(?:\s+बताओ)?\s*$",
            "what's the weather",
        ),
        (
            r"^(.+?)\s+(?:में|का|के)\s+मौसम(?:\s+(?:कैसा\s+है|बताओ))?\s*$",
            r"weather in \1",
        ),
        (
            r"^(?:aaj\s+ka\s+)?mausam(?:\s+kaisa\s+hai)?(?:\s+batao)?"
            r"\s+(.+?)\s+(?:mein|me|in)\s*$",
            r"weather in \1",
        ),
        (
            r"^(?:aaj\s+ka\s+)?mausam(?:\s+kaisa\s+hai)?(?:\s+batao)?\s*$",
            "what's the weather",
        ),
        (
            r"^(.+?)\s+(?:mein|me|ka)\s+mausam(?:\s+(?:kaisa\s+hai|batao))?\s*$",
            r"weather in \1",
        ),
        (
            r"^(?:आज\s+की\s+)?(?:खबरें|खबर|समाचार|न्यूज़|न्यूज)(?:\s+बताओ)?\s*$",
            "what's the news",
        ),
        (
            r"^(?:khabrein|khabar|samachar|news\s+batao)\s*$",
            "what's the news",
        ),
        (
            r"^(?:खेल|sports?)\s+(?:की\s+)?(?:खबरें|समाचार|news)\s*$",
            "sports news",
        ),
        (
            r"^(.+?)\s+(?:की\s+)?(?:खबरें|समाचार)(?:\s+बताओ)?\s*$",
            r"news about \1",
        ),
        (
            r"^(?:गाना|गाने|म्यूजिक|संगीत)\s+चलाओ\s*$",
            "play music",
        ),
        (
            r"^(?:gaana|gana|music|song)\s+chalao(?:\s+do)?\s*$",
            "play music",
        ),
        (
            r"^(?:गाना\s+)?(?:रोको|रुकवाओ|पॉज़|पॉज)\s*$",
            "pause",
        ),
        (
            r"^(?:pause\s+karo|gana\s+rok\s+do|gaana\s+rok\s+do)\s*$",
            "pause",
        ),
        (
            r"^अगला\s+गाना\s*$",
            "next",
        ),
        (
            r"^agla\s+(?:gaana|gana|song)\s*$",
            "next",
        ),
        (
            r"^पिछला\s+गाना\s*$",
            "previous",
        ),
        (
            r"^pichla\s+(?:gaana|gana|song)\s*$",
            "previous",
        ),
        (
            r"^(?:स्क्रीनशॉट|स्क्रीन\s+शॉट)\s+(?:दिखाओ|खोलो)\s*$",
            "show me the screenshot",
        ),
        (
            r"^(?:स्क्रीनशॉट|स्क्रीन\s+शॉट)\s+(?:लो|ले\s+लो|ले)\s*$",
            "take a screenshot",
        ),
        (
            r"^screenshot\s+(?:lo|le\s+lo|le\s+do|le)\s*$",
            "take a screenshot",
        ),
        (
            r"^(?:रुक\s+जाओ|सुनना\s+बंद\s+करो|बंद\s+हो\s+जाओ|एग्जिट)\s*$",
            "stop listening",
        ),
        (
            r"^(?:ruk\s+jao|sunna\s+band\s+karo|band\s+ho\s+jao|exit\s+karo)\s*$",
            "stop listening",
        ),
        (
            r"^(.+?)\s+(?:खोलो|kholo)\s+(?:और|aur|and)\s+(?:लिखो|likho)\s+(.+)$",
            r"open \1 and write \2",
        ),
        (
            r"^(?:खोलो|kholo)\s+(.+?)\s+(?:और|aur|and)\s+(?:लिखो|likho)\s+(.+)$",
            r"open \1 and write \2",
        ),
        (
            r"^(.+?)\s+(?:खोलो|kholo)\s+(?:और|aur|and)\s+(.+?)\s+(?:लिखो|likho)\s*$",
            r"open \1 and write \2",
        ),
        (
            r"^(.+?)\s+(?:में|mein|me)\s+(?:लिखो|लिख\s+दो|likho|likh\s+do)\s+(.+)$",
            r"write \2 in \1",
        ),
        (
            r"^(?:लिखो|likho)\s+(.+?)\s+(?:में|in|mein|me)\s+(.+)$",
            r"write \1 in \2",
        ),
        (
            r"^(?:लिखो|likho)\s+(.+)$",
            r"write \1",
        ),
        (
            r"^(.+?)\s+को\s+(?:वीडियो\s+कॉल|वीडियो कॉल)\s+करो\s*$",
            r"video call \1",
        ),
        (
            r"^(.+?)\s+ko\s+video\s+call\s+karo\s*$",
            r"video call \1",
        ),
        (
            r"^(.+?)\s+को\s+(?:मैसेज|मेसेज|संदेश)\s+(?:भेजो|करो)\s*(.*)$",
            r"send message to \1 \2",
        ),
        (
            r"^(.+?)\s+ko\s+(?:message|msg|text)\s+(?:bhejo|karo|bhej\s+do)\s*(.*)$",
            r"send message to \1 \2",
        ),
        (
            r"^(.+?)\s+को\s+(?:कॉल|काल)\s+करो\s*$",
            r"call \1",
        ),
        (
            r"^(.+?)\s+ko\s+call\s+karo\s*$",
            r"call \1",
        ),
        (
            r"^(.+?)\s+(?:को\s+)?(?:खोलो|खोल\s+दो|खोलिए|खोल\s+देना)\s*$",
            r"open \1",
        ),
        (
            r"^(?:खोलो|खोल\s+दो|खोलिए)\s+(.+)$",
            r"open \1",
        ),
        (
            r"^(.+?)\s+kholo(?:\s+do)?\s*$",
            r"open \1",
        ),
        (
            r"^kholo(?:\s+do)?\s+(.+)$",
            r"open \1",
        ),
    )
    for pattern, repl in replacements:
        updated = re.sub(pattern, repl, text, flags=re.IGNORECASE)
        if updated != text:
            text = " ".join(updated.split())
            text = re.sub(r"\s+in\s+$", "", text)
            text = re.sub(r"^what's the weather in\s*$", "what's the weather", text, flags=re.I)
            break
    return text
