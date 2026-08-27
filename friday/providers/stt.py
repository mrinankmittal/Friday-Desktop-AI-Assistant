from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import speech_recognition as sr

from friday.language.bilingual import (
    fallback_stt_language,
    parse_stt_languages,
    whisper_language_code,
)
from friday.language.stt_fix import fix_transcript, pick_best_transcript
from friday.providers.types import SttProvider, SttResult

logger = logging.getLogger("friday.providers.stt")

# Short words like "yes" / "sure" are below SpeechRecognition's 0.3s default
# phrase_threshold, so they were ignored as clicks. Keep these sensitive.
_MAX_ENERGY = 1200
_MIN_ENERGY = 280
_CONFIRM_PHRASE_LIMIT = 4.5

# Google's endpoint returns no result at all for a bare interjection -- "yes",
# "sure", "no", "ok" -- while content words of the same length ("stop",
# "cancel", "hello") transcribe fine. Sending the same clip twice does come
# back with text, so short clips get one retry as a doubled clip and the
# duplicated transcript is collapsed to the single word that was spoken.
_SHORT_CLIP_SEC = 2.0
_REPEAT_GAP_SEC = 0.4


def configure_command_recognizer(
    recognizer: sr.Recognizer,
    source,
    *,
    adjust_noise: bool,
    for_confirm: bool = False,
    pause_threshold: float | None = None,
) -> sr.Recognizer:
    recognizer.dynamic_energy_threshold = True
    recognizer.dynamic_energy_ratio = 1.08
    # Confirm replies are short. Full commands need a longer pause so fast
    # speech with brief gaps is not cut off halfway.
    recognizer.pause_threshold = (
        0.45 if for_confirm else (pause_threshold if pause_threshold is not None else 1.15)
    )
    recognizer.phrase_threshold = 0.08
    recognizer.non_speaking_duration = 0.2 if for_confirm else 0.55
    if adjust_noise:
        recognizer.adjust_for_ambient_noise(
            source,
            duration=0.65 if not for_confirm else 0.25,
        )
        if recognizer.energy_threshold > _MAX_ENERGY:
            recognizer.energy_threshold = _MAX_ENERGY
        if recognizer.energy_threshold < _MIN_ENERGY:
            recognizer.energy_threshold = _MIN_ENERGY
    return recognizer


def clip_seconds(audio: sr.AudioData) -> float:
    frame = audio.sample_rate * audio.sample_width
    if not frame:
        return 0.0
    return len(audio.frame_data) / float(frame)


def doubled_clip(audio: sr.AudioData) -> sr.AudioData:
    gap = b"\x00" * (int(audio.sample_rate * _REPEAT_GAP_SEC) * audio.sample_width)
    return sr.AudioData(
        audio.frame_data + gap + audio.frame_data,
        audio.sample_rate,
        audio.sample_width,
    )


def collapse_repeat(text: str) -> str:
    """Undo a doubled clip: "yes yes" came from one spoken "yes"."""
    words = text.split()
    if not words:
        return text
    lowered = [word.lower() for word in words]
    if len(set(lowered)) == 1:
        return words[0]
    half, remainder = divmod(len(words), 2)
    if not remainder and lowered[:half] == lowered[half:]:
        return " ".join(words[:half])
    return text


def recognize_google_text(
    recognizer: sr.Recognizer,
    audio: sr.AudioData,
    *,
    language: str,
) -> str:
    """Transcribe, retrying a short clip doubled so interjections survive.

    Raises the same exceptions as ``Recognizer.recognize_google``.
    """
    try:
        return _google_transcript(recognizer, audio, language=language)
    except sr.UnknownValueError:
        if clip_seconds(audio) > _SHORT_CLIP_SEC:
            raise
    text = _google_transcript(
        recognizer,
        doubled_clip(audio),
        language=language,
    )
    return collapse_repeat(text)


def _google_transcript(
    recognizer: sr.Recognizer,
    audio: sr.AudioData,
    *,
    language: str,
) -> str:
    try:
        raw = recognizer.recognize_google(  # type: ignore[attr-defined]
            audio,
            language=language,
            show_all=True,
        )
    except TypeError:
        raw = recognizer.recognize_google(audio, language=language)  # type: ignore[attr-defined]
    if isinstance(raw, str):
        return fix_transcript(raw.strip())
    if isinstance(raw, dict):
        alternatives = [
            str(item.get("transcript") or "").strip()
            for item in raw.get("alternative") or []
            if str(item.get("transcript") or "").strip()
        ]
        if alternatives:
            return pick_best_transcript(alternatives)
    raise sr.UnknownValueError()


def recognize_google_best(
    recognizer: sr.Recognizer,
    audio: sr.AudioData,
    *,
    language: str,
) -> str:
    """Transcribe one clip, trying each language in a ``hi-IN,en-IN`` list."""
    langs = parse_stt_languages(language)
    if len(langs) == 1:
        return recognize_google_text(recognizer, audio, language=langs[0])

    texts: list[str] = []
    last_request: sr.RequestError | None = None

    def one_language(lang: str) -> str:
        return recognize_google_text(recognizer, audio, language=lang).strip()

    with ThreadPoolExecutor(max_workers=min(3, len(langs))) as pool:
        futures = [pool.submit(one_language, lang) for lang in langs[:3]]
        for future in futures:
            try:
                heard = future.result()
            except sr.UnknownValueError:
                continue
            except sr.RequestError as error:
                last_request = error
                continue
            if heard:
                texts.append(heard)
    if texts:
        if len(texts) == 1:
            return texts[0]
        return pick_best_transcript(texts)
    if last_request is not None:
        raise last_request
    raise sr.UnknownValueError()


def listen_with_retry(
    provider: SttProvider,
    *,
    language: str,
    timeout: float,
    phrase_time_limit: float,
    adjust_noise: bool,
    retry: bool = True,
    pause_threshold: float | None = None,
) -> SttResult:
    """Listen once, then retry if Google returns unknown or timeout.

    Do not shrink ``phrase_time_limit`` on retry: that cut off longer
    spoken commands. Confirm replies already use a short limit.
    """
    listen_kw: dict[str, object] = {
        "language": language,
        "timeout": timeout,
        "phrase_time_limit": phrase_time_limit,
        "adjust_noise": adjust_noise,
    }
    if pause_threshold is not None:
        listen_kw["pause_threshold"] = pause_threshold
    result = provider.listen(**listen_kw)
    if not retry or result.status not in {"unknown", "timeout"}:
        return result
    retry_kw = dict(listen_kw)
    retry_kw["language"] = _fallback_language(language, result.status)
    retry_kw["adjust_noise"] = False
    if pause_threshold is not None and phrase_time_limit > _CONFIRM_PHRASE_LIMIT:
        retry_kw["pause_threshold"] = pause_threshold + 0.2
    if phrase_time_limit <= _CONFIRM_PHRASE_LIMIT:
        retry_kw["timeout"] = min(timeout, 6.0)
    retry_result = provider.listen(**retry_kw)
    if retry_result.status == "ok" and retry_result.text.strip():
        return retry_result
    # Last resort: longer capture window for fast speakers cut off early.
    if phrase_time_limit > _CONFIRM_PHRASE_LIMIT:
        final_kw = dict(retry_kw)
        final_kw["phrase_time_limit"] = phrase_time_limit + 4.0
        if pause_threshold is not None:
            final_kw["pause_threshold"] = pause_threshold + 0.35
        final_kw["timeout"] = max(timeout, phrase_time_limit + 6.0)
        return provider.listen(**final_kw)
    return retry_result


def _fallback_language(language: str, status: str) -> str:
    if status != "unknown":
        return language
    return fallback_stt_language(language)


class GoogleStt:
    """SpeechRecognition + Google Web Speech. Same capture settings as Friday 1.0."""

    name = "google"

    def listen(
        self,
        *,
        timeout: float = 25.0,
        phrase_time_limit: float = 16.0,
        language: str = "hi-IN,en-IN",
        adjust_noise: bool = True,
        pause_threshold: float | None = None,
    ) -> SttResult:
        recognizer = sr.Recognizer()
        try:
            with sr.Microphone() as source:
                configure_command_recognizer(
                    recognizer,
                    source,
                    adjust_noise=adjust_noise,
                    for_confirm=phrase_time_limit <= _CONFIRM_PHRASE_LIMIT,
                    pause_threshold=pause_threshold,
                )
                audio = recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
        except sr.WaitTimeoutError:
            return SttResult(status="timeout")
        except Exception as error:
            logger.exception("Microphone capture failed")
            return SttResult(status="error", error=str(error))

        print("Recognizing...")
        try:
            query = recognize_google_best(recognizer, audio, language=language).strip()
        except sr.UnknownValueError:
            return SttResult(status="unknown")
        except sr.RequestError as error:
            return SttResult(status="error", error=str(error))

        if not query:
            return SttResult(status="unknown")
        return SttResult(text=fix_transcript(query), status="ok")


class FasterWhisperStt:
    """Local faster-whisper STT. Optional; selected with FRIDAY_STT_PROVIDER=faster_whisper."""

    name = "faster_whisper"

    def __init__(self, model_size: str = "base") -> None:
        self.model_size = model_size
        self._model = None

    def listen(
        self,
        *,
        timeout: float = 20.0,
        phrase_time_limit: float = 10.0,
        language: str = "en-in",
        adjust_noise: bool = True,
        pause_threshold: float | None = None,
    ) -> SttResult:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            logger.warning("faster-whisper is not installed; install it to use this STT provider")
            return GoogleStt().listen(
                timeout=timeout,
                phrase_time_limit=phrase_time_limit,
                language=language,
                adjust_noise=adjust_noise,
                pause_threshold=pause_threshold,
            )

        recognizer = sr.Recognizer()
        try:
            with sr.Microphone() as source:
                configure_command_recognizer(
                    recognizer,
                    source,
                    adjust_noise=adjust_noise,
                    for_confirm=phrase_time_limit <= _CONFIRM_PHRASE_LIMIT,
                    pause_threshold=pause_threshold,
                )
                audio = recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
        except sr.WaitTimeoutError:
            return SttResult(status="timeout")
        except Exception as error:
            return SttResult(status="error", error=str(error))

        print("Recognizing...")
        wav_path: Path | None = None
        try:
            if self._model is None:
                self._model = WhisperModel(self.model_size, device="cpu")
            wav_path = _write_temp_wav(audio)
            transcribe_kw: dict[str, str] = {}
            whisper_language = whisper_language_code(language)
            if whisper_language:
                transcribe_kw["language"] = whisper_language
            segments, _info = self._model.transcribe(str(wav_path), **transcribe_kw)
            text = " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as error:
            logger.exception("faster-whisper transcription failed")
            return SttResult(status="error", error=str(error))
        finally:
            if wav_path is not None:
                wav_path.unlink(missing_ok=True)

        if not text:
            return SttResult(status="unknown")
        return SttResult(text=fix_transcript(text), status="ok")


def _write_temp_wav(audio: sr.AudioData) -> Path:
    import tempfile

    handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    handle.write(audio.get_wav_data())
    handle.close()
    return Path(handle.name)
