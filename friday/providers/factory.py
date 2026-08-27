from __future__ import annotations

from friday.providers.settings import VoiceSettings, resolve_wake_provider_name
from friday.providers.stt import FasterWhisperStt, GoogleStt
from friday.providers.tts import BilingualTts, SapiTts
from friday.providers.types import SttProvider, TtsProvider, VisionProvider, WakeWordProvider
from friday.providers.wake import GoogleWakeWord, OpenWakeWord

_stt: SttProvider | None = None
_tts: TtsProvider | None = None
_wake: WakeWordProvider | None = None
_vision: VisionProvider | None = None


def get_stt_provider(settings: VoiceSettings | None = None) -> SttProvider:
    global _stt
    if _stt is None:
        config = settings or VoiceSettings.from_env()
        if config.stt_provider in {"faster_whisper", "whisper"}:
            _stt = FasterWhisperStt()
        else:
            _stt = GoogleStt()
    return _stt


def get_tts_provider(settings: VoiceSettings | None = None) -> TtsProvider:
    global _tts
    if _tts is None:
        config = settings or VoiceSettings.from_env()
        if config.tts_provider in {"sapi", "pyttsx3"}:
            _tts = SapiTts()
        else:
            _tts = BilingualTts()
    return _tts


def get_wake_provider(settings: VoiceSettings | None = None) -> WakeWordProvider:
    global _wake
    if _wake is None:
        config = settings or VoiceSettings.from_env()
        if resolve_wake_provider_name(config) == "openwakeword":
            _wake = OpenWakeWord(threshold=config.wake_threshold)
        else:
            _wake = GoogleWakeWord(language=config.wake_language)
    return _wake


def get_vision_provider() -> VisionProvider:
    global _vision
    if _vision is None:
        from friday.providers.vision import ScreenVision

        _vision = ScreenVision()
    return _vision


def set_stt_provider(provider: SttProvider | None) -> None:
    global _stt
    _stt = provider


def set_tts_provider(provider: TtsProvider | None) -> None:
    global _tts
    _tts = provider


def set_wake_provider(provider: WakeWordProvider | None) -> None:
    global _wake
    _wake = provider


def set_vision_provider(provider: VisionProvider | None) -> None:
    global _vision
    _vision = provider
