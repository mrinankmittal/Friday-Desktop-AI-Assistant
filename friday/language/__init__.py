"""Hindi + English helpers for listening, speaking, and command routing."""

from friday.language.pronounce import (
    pronounce_assistant_name,
    spoken_assistant_name,
    text_for_speech,
    voice_looks_indic,
)
from friday.language.romanize import romanize_devanagari
from friday.language.bilingual import (
    detect_language,
    fallback_stt_language,
    is_wake_transcript,
    localize_reply,
    normalize_command,
    parse_stt_languages,
    find_indic_voice_id,
    pick_transcript,
    pick_tts_voice_id,
    reset_user_language,
    set_user_language,
    speak_language_for,
    user_language,
    whisper_language_code,
)

__all__ = [
    "detect_language",
    "fallback_stt_language",
    "is_wake_transcript",
    "localize_reply",
    "normalize_command",
    "pronounce_assistant_name",
    "parse_stt_languages",
    "romanize_devanagari",
    "spoken_assistant_name",
    "text_for_speech",
    "voice_looks_indic",
    "find_indic_voice_id",
    "pick_transcript",
    "pick_tts_voice_id",
    "reset_user_language",
    "set_user_language",
    "speak_language_for",
    "user_language",
    "whisper_language_code",
]
