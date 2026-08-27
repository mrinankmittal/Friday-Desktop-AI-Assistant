from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from friday.providers.types import project_root, wake_model_path

logger = logging.getLogger("friday.providers")

@dataclass(frozen=True)
class LlmSettings:
    provider: str = "ollama"
    model: str = "gemma3:4b"
    host: str = "http://127.0.0.1:11434"

    @classmethod
    def from_env(cls) -> LlmSettings:
        provider = (
            os.environ.get("FRIDAY_LLM_PROVIDER", "ollama").strip().lower() or "ollama"
        )
        model = os.environ.get("FRIDAY_LLM_MODEL", "gemma3:4b").strip() or "gemma3:4b"
        host = (
            os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
            or "http://127.0.0.1:11434"
        )
        return cls(provider=provider, model=model, host=host)


def _load_dotenv() -> None:
    env_path = project_root() / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


@dataclass(frozen=True)
class VoiceSettings:
    stt_provider: str = "google"
    tts_provider: str = "sapi"
    wake_provider: str = "auto"
    stt_language: str = "en-IN"
    wake_language: str = "en-IN"
    wake_threshold: float = 0.5
    tts_voice_en: str = ""
    tts_voice_hi: str = ""
    tts_neural_hi: str = "hi-IN-SwaraNeural"
    stt_pause_threshold: float = 1.15
    stt_phrase_limit: float = 20.0
    stt_listen_timeout: float = 30.0
    stt_attempts: int = 4

    @classmethod
    def from_env(cls) -> VoiceSettings:
        return cls(
            stt_provider=os.environ.get("FRIDAY_STT_PROVIDER", "google").strip().lower()
            or "google",
            tts_provider=os.environ.get("FRIDAY_TTS_PROVIDER", "sapi").strip().lower()
            or "sapi",
            wake_provider=os.environ.get("FRIDAY_WAKE_PROVIDER", "auto").strip().lower()
            or "auto",
            stt_language=os.environ.get("FRIDAY_STT_LANGUAGE", "en-IN").strip()
            or "en-IN",
            wake_language=os.environ.get("FRIDAY_WAKE_LANGUAGE", "en-IN").strip()
            or "en-IN",
            wake_threshold=float(os.environ.get("FRIDAY_WAKE_THRESHOLD", "0.5") or 0.5),
            tts_voice_en=os.environ.get("FRIDAY_TTS_VOICE_EN", "").strip(),
            tts_voice_hi=os.environ.get("FRIDAY_TTS_VOICE_HI", "").strip(),
            tts_neural_hi=os.environ.get("FRIDAY_TTS_NEURAL_HI", "hi-IN-SwaraNeural").strip()
            or "hi-IN-SwaraNeural",
            stt_pause_threshold=float(
                os.environ.get("FRIDAY_STT_PAUSE_THRESHOLD", "1.15") or 1.15
            ),
            stt_phrase_limit=float(
                os.environ.get("FRIDAY_STT_PHRASE_LIMIT", "20") or 20
            ),
            stt_listen_timeout=float(
                os.environ.get("FRIDAY_STT_LISTEN_TIMEOUT", "30") or 30
            ),
            stt_attempts=max(
                1,
                int(os.environ.get("FRIDAY_STT_ATTEMPTS", "4") or 4),
            ),
        )

    def english_only(self) -> bool:
        """True when listening languages do not include Hindi."""
        from friday.language.bilingual import parse_stt_languages

        return not any(
            lang.lower().startswith("hi") for lang in parse_stt_languages(self.stt_language)
        )

    def effective_stt_language(self) -> str:
        """Languages sent to Google STT.

        English-only installs get a second en-US pass — Indian accents often
        transcribe better on one code than the other.
        """
        from friday.language.bilingual import parse_stt_languages

        langs = parse_stt_languages(self.stt_language)
        if self.english_only():
            expanded: list[str] = []
            seen: set[str] = set()
            for lang in langs + ["en-IN", "en-US"]:
                key = lang.lower()
                if key not in seen:
                    seen.add(key)
                    expanded.append(lang)
            return ",".join(expanded)
        return self.stt_language


def resolve_wake_provider_name(settings: VoiceSettings | None = None) -> str:
    """Google stays the hotword engine until ``models/friday.onnx`` exists."""
    config = settings or VoiceSettings.from_env()
    requested = config.wake_provider
    model = wake_model_path()
    if requested in {"openwakeword", "open_wake_word", "oww"}:
        return "openwakeword" if model.is_file() else "google"
    if requested == "auto":
        return "openwakeword" if model.is_file() else "google"
    return "google"
