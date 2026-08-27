from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import pyttsx3

from friday.language.bilingual import (
    find_indic_voice_id,
    has_devanagari,
    pick_tts_voice_id,
    speak_language_for,
)
from friday.language.pronounce import text_for_speech, voice_looks_indic
from friday.providers.settings import VoiceSettings

SpeakHook = Callable[[], None]
logger = logging.getLogger("friday.providers.tts")

DEFAULT_NEURAL_HI = "hi-IN-SwaraNeural"
_NEURAL_RATE = "-8%"
_HINDI_NEURAL_VOICES = (DEFAULT_NEURAL_HI, "hi-IN-MadhurNeural")
_EDGE_COOLDOWN_SEC = 90.0
_indic_available = False
_edge_skip_until = 0.0
_sapi_indic_cached: bool | None = None
_winrt_hi_cached: bool | None = None
_sapi_voices: list | None = None


def indic_voice_available() -> bool:
    """True when Friday can speak real Hindi (Windows Hindi voice or neural)."""
    return (
        _indic_available
        or winrt_hindi_available()
        or sapi_indic_available()
        or neural_hindi_available()
    )


def can_speak_hindi() -> bool:
    return indic_voice_available()


def neural_hindi_available() -> bool:
    return _module_available("edge_tts") or _module_available("gtts")


def _module_available(name: str) -> bool:
    try:
        __import__(name)
    except ImportError:
        return False
    return True


def reset_hindi_tts_cooldown() -> None:
    """Tests (and a recovered network) can force Edge TTS to be tried again."""
    global _edge_skip_until
    _edge_skip_until = 0.0


def reset_sapi_indic_cache() -> None:
    """Forget whether a Hindi Windows voice was found (tests / after install)."""
    global _sapi_indic_cached, _sapi_voices, _winrt_hi_cached
    _sapi_indic_cached = None
    _sapi_voices = None
    _winrt_hi_cached = None


def _list_sapi_voices() -> list:
    """Voice list once. The speak engine itself is recreated every utterance."""
    global _sapi_voices
    if _sapi_voices is not None:
        return _sapi_voices
    engine = pyttsx3.init("sapi5")
    _sapi_voices = list(engine.getProperty("voices") or [])
    try:
        engine.stop()
    except Exception:
        pass
    return _sapi_voices


def warmup_sapi() -> None:
    """Probe Windows voices on the voice thread before the first command."""
    try:
        _list_sapi_voices()
        sapi_indic_available()
        if winrt_hindi_available():
            logger.info("Windows Hindi voice ready (Kalpana/Hemant)")
        else:
            logger.info("Windows voices ready")
    except Exception:
        logger.exception("Windows voice warmup failed")


def winrt_hindi_available() -> bool:
    """True when Windows OneCore has a Hindi voice WinRT can actually play."""
    global _winrt_hi_cached
    if _winrt_hi_cached is not None:
        return _winrt_hi_cached
    try:
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer

        from friday.providers.winrt_speak import pick_hindi_voice

        found = pick_hindi_voice(list(SpeechSynthesizer.all_voices)) is not None
    except Exception:
        found = False
    _winrt_hi_cached = found
    return found


def sapi_indic_available() -> bool:
    """True when SAPI has Hemant, Kalpana, or another Hindi voice."""
    global _sapi_indic_cached, _indic_available
    if _sapi_indic_cached is not None:
        return _sapi_indic_cached
    settings = VoiceSettings.from_env()
    try:
        voices = _list_sapi_voices()
    except Exception:
        _sapi_indic_cached = False
        return False
    found = find_indic_voice_id(voices, hi_hint=settings.tts_voice_hi) is not None
    _sapi_indic_cached = found
    if found:
        _indic_available = True
    return found


def _wants_hindi(text: str, language: str | None) -> bool:
    lang = (language or speak_language_for(text) or "en").split("-", 1)[0].lower()
    return lang == "hi" or has_devanagari(text)


class BilingualTts:
    """Windows Hindi voice when installed; else Edge/Google Hindi; SAPI English."""

    name = "auto"

    def __init__(self, english=None) -> None:
        self._english = english or SapiTts()

    def speak(
        self,
        text: str,
        before_play: SpeakHook | None = None,
        *,
        language: str | None = None,
    ) -> None:
        message = str(text).strip()
        if not message:
            return
        lang = (language or speak_language_for(message) or "en").split("-", 1)[0]
        if _wants_hindi(message, lang):
            if winrt_hindi_available():
                try:
                    self._speak_winrt(message, before_play)
                    return
                except Exception:
                    logger.exception("Windows Hindi TTS failed; trying other voices")
            if sapi_indic_available():
                self._english.speak(message, before_play, language="hi")
                return
            if neural_hindi_available():
                try:
                    self._speak_hindi(message, before_play)
                    return
                except Exception:
                    logger.exception("Hindi TTS failed; falling back to SAPI")
        self._english.speak(message, before_play, language=lang)

    def _speak_winrt(self, message: str, before_play: SpeakHook | None) -> None:
        global _indic_available
        spoken = text_for_speech(message, "hi", indic_voice=True)
        path = Path(tempfile.gettempdir()) / "friday_hi.wav"
        synthesize_winrt(spoken, path)
        if before_play is not None:
            before_play()
        play_wav(path)
        _indic_available = True
        _unlink_quiet(path)

    def _speak_hindi(self, message: str, before_play: SpeakHook | None) -> None:
        global _indic_available
        settings = VoiceSettings.from_env()
        voice = settings.tts_neural_hi or DEFAULT_NEURAL_HI
        spoken = text_for_speech(message, "hi", indic_voice=True)
        path = Path(tempfile.gettempdir()) / "friday_hi.mp3"
        synthesize_neural(spoken, path, voice=voice, rate=_NEURAL_RATE)
        if before_play is not None:
            before_play()
        play_mp3(path)
        _indic_available = True
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def synthesize_neural(
    text: str,
    dest: Path,
    *,
    voice: str = DEFAULT_NEURAL_HI,
    rate: str = _NEURAL_RATE,
) -> None:
    """Hindi audio: Edge neural first, Google Hindi if Edge is down."""
    global _edge_skip_until
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    now = time.monotonic()
    if now >= _edge_skip_until:
        voices: list[str] = []
        for candidate in (voice, *_HINDI_NEURAL_VOICES):
            if candidate and candidate not in voices:
                voices.append(candidate)
        for index, candidate in enumerate(voices):
            tries = 2 if index == 0 else 1
            for attempt in range(tries):
                try:
                    _synthesize_edge(text, dest, voice=candidate, rate=rate)
                    _edge_skip_until = 0.0
                    return
                except Exception as exc:
                    errors.append(f"{candidate}: {exc}")
                    _unlink_quiet(dest)
                    if attempt + 1 < tries:
                        time.sleep(0.4)
        _edge_skip_until = time.monotonic() + _EDGE_COOLDOWN_SEC
        logger.warning("Edge Hindi TTS failed; using Google Hindi TTS")
    try:
        _synthesize_gtts(text, dest, lang="hi")
        return
    except Exception as exc:
        errors.append(f"gtts: {exc}")
        _unlink_quiet(dest)
    raise RuntimeError("; ".join(errors) or "Hindi TTS produced no audio")


def _synthesize_edge(text: str, dest: Path, *, voice: str, rate: str) -> None:
    _run_tts_module(
        "friday.providers.edge_speak",
        [voice, str(dest), rate],
        text,
        timeout=22,
        dest=dest,
        label="edge-tts",
    )


def _synthesize_gtts(text: str, dest: Path, *, lang: str = "hi") -> None:
    _run_tts_module(
        "friday.providers.gtts_speak",
        [str(dest), lang],
        text,
        timeout=30,
        dest=dest,
        label="gTTS",
    )


def synthesize_winrt(text: str, dest: Path) -> None:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run_tts_module(
        "friday.providers.winrt_speak",
        [str(dest)],
        text,
        timeout=20,
        dest=dest,
        label="WinRT Hindi",
    )


def play_wav(path: Path) -> None:
    """Play a WAV from Windows OneCore TTS."""
    if sys.platform != "win32":
        raise RuntimeError("wav playback is only wired for Windows")
    import winsound

    winsound.PlaySound(str(path.resolve()), winsound.SND_FILENAME)


def _run_tts_module(
    module: str,
    args: list[str],
    text: str,
    *,
    timeout: int,
    dest: Path,
    label: str,
) -> None:
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [sys.executable, "-m", module, *args],
        input=text.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        check=False,
        creationflags=creationflags,
    )
    if result.returncode != 0 or not dest.is_file() or dest.stat().st_size < 32:
        detail = (result.stderr or result.stdout or b"").decode("utf-8", errors="replace")
        raise RuntimeError(detail.strip() or f"{label} produced no audio")


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def play_mp3(path: Path) -> None:
    """Play an mp3 and wait. Uses Windows MCI so we do not need extra players."""
    resolved = str(path.resolve())
    if sys.platform != "win32":
        raise RuntimeError("mp3 playback is only wired for Windows")
    import ctypes

    winmm = ctypes.windll.winmm
    alias = "friday_tts"
    commands = (
        f'open "{resolved}" type mpegvideo alias {alias}',
        f"play {alias} wait",
        f"close {alias}",
    )
    for command in commands:
        err = winmm.mciSendStringW(command, None, 0, None)
        if err:
            raise RuntimeError(f"MCI failed ({err}) on {command}")


class SapiTts:
    """Windows SAPI5 via pyttsx3. Fresh engine per utterance so replies keep playing."""

    name = "sapi"

    def speak(
        self,
        text: str,
        before_play: SpeakHook | None = None,
        *,
        language: str | None = None,
    ) -> None:
        global _indic_available
        message = str(text).strip()
        if not message:
            return

        # Reusing one pyttsx3 engine often speaks once, then stays silent.
        speech_engine = pyttsx3.init("sapi5")
        voices = _list_sapi_voices() or list(speech_engine.getProperty("voices") or [])
        settings = VoiceSettings.from_env()
        lang = (language or speak_language_for(message) or "en").split("-", 1)[0]
        voice_id = None
        if voices:
            voice_id = pick_tts_voice_id(
                voices,
                lang,
                hi_hint=settings.tts_voice_hi,
                en_hint=settings.tts_voice_en,
            )
            if voice_id:
                speech_engine.setProperty("voice", voice_id)
        indic_voice = voice_looks_indic(voices, voice_id, settings.tts_voice_hi)
        if indic_voice:
            _indic_available = True
        speech_engine.setProperty("rate", 150 if indic_voice else 160)
        if lang == "hi" and voices and not indic_voice:
            logger.info(
                "No Hindi SAPI voice installed; speaking Hindi as Hinglish "
                "with the English voice"
            )
        spoken = text_for_speech(message, lang, indic_voice=indic_voice)
        try:
            speech_engine.say(spoken)
            if before_play is not None:
                before_play()
            speech_engine.runAndWait()
        except Exception:
            logger.exception("SAPI failed on %r; retrying English-safe text", spoken[:80])
            try:
                fallback = text_for_speech(message, "en", indic_voice=False)
                speech_engine.say(fallback or "Okay")
                speech_engine.runAndWait()
            except Exception:
                logger.exception("SAPI fallback also failed")
        try:
            speech_engine.stop()
        except Exception:
            pass
