from __future__ import annotations

import logging
import re

import numpy as np
import speech_recognition as sr

from friday.language.bilingual import is_wake_transcript, parse_stt_languages
from friday.providers.types import WakeWordProvider, wake_model_path

logger = logging.getLogger("friday.providers.wake")


def follow_up_after_wake(transcript: str, name: str = "friday") -> str:
    """Return words spoken after the wake word, e.g. 'Friday yes' → 'yes'."""
    text = str(transcript)
    match = re.search(rf"\b{re.escape(name)}\b", text, re.I)
    if not match:
        match = re.search(r"फ्राइडे|फ्रायडे", text)
    if not match:
        return ""
    rest = text[match.end() :]
    return re.sub(r"^[\s,.:;!?-]+", "", rest).strip()


class GoogleWakeWord:
    """Google STT hotword loop. Same thresholds and phrasing as Friday 1.0."""

    name = "google"

    def __init__(self, language: str = "en-IN,hi-IN") -> None:
        self.language = language
        self.follow_up = ""

    def wait(self) -> bool:
        self.follow_up = ""
        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = True
        recognizer.dynamic_energy_ratio = 1.2
        recognizer.pause_threshold = 0.45
        recognizer.phrase_threshold = 0.15
        recognizer.non_speaking_duration = 0.3

        with sr.Microphone(sample_rate=16000) as source:
            logger.info("Calibrating the hotword microphone...")
            recognizer.adjust_for_ambient_noise(source, duration=0.6)
            logger.info(
                "Hotword listener ready; say 'Friday' (threshold %.0f)",
                recognizer.energy_threshold,
            )

            while True:
                try:
                    audio = recognizer.listen(
                        source,
                        timeout=3,
                        phrase_time_limit=4,
                    )
                except sr.WaitTimeoutError:
                    continue

                transcript = _recognize_wake(recognizer, audio, self.language)
                if transcript is None:
                    continue
                if transcript is False:
                    return False

                logger.info("Hotword transcript: %s", transcript)
                if is_wake_transcript(transcript):
                    self.follow_up = follow_up_after_wake(transcript)
                    return True


def _recognize_wake(recognizer: sr.Recognizer, audio, language: str):
    """Try each wake language on the same clip. False = service error."""
    last_error = None
    heard = False
    for lang in parse_stt_languages(language)[:3]:
        try:
            transcript = recognizer.recognize_google(  # type: ignore[attr-defined]
                audio,
                language=lang,
            )
        except sr.UnknownValueError:
            continue
        except sr.RequestError as error:
            last_error = error
            continue
        heard = True
        if is_wake_transcript(transcript):
            return transcript
    if last_error is not None and not heard:
        logger.error("Hotword speech service failed: %s", last_error)
        return False
    logger.debug("Hotword audio was not understood")
    return None


class OpenWakeWord:
    """Local openWakeWord detector. Requires ``models/friday.onnx``."""

    name = "openwakeword"

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold

    def wait(self) -> bool:
        model_path = wake_model_path()
        if not model_path.is_file():
            logger.warning(
                "openWakeWord model missing at %s; use Google hotword until it exists",
                model_path,
            )
            return GoogleWakeWord().wait()

        try:
            import pyaudio
            from openwakeword.model import Model
        except ImportError as error:
            logger.error("openWakeWord dependencies are missing: %s", error)
            return GoogleWakeWord().wait()

        logger.info("Hotword listener ready; openWakeWord model %s", model_path.name)
        oww = Model(
            wakeword_models=[str(model_path)],
            inference_framework="onnx",
        )
        audio = pyaudio.PyAudio()
        chunk = 1280
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=chunk,
        )
        try:
            while True:
                frame = np.frombuffer(
                    stream.read(chunk, exception_on_overflow=False),
                    dtype=np.int16,
                )
                prediction = oww.predict(frame)
                for score in prediction.values():
                    if float(score) >= self.threshold:
                        return True
        finally:
            stream.stop_stream()
            stream.close()
            audio.terminate()


def run_wake_loop(activation_event=None, command_queue=None) -> None:
    from friday.providers.factory import get_wake_provider

    try:
        provider = get_wake_provider()
        heard = provider.wait()
        if not heard:
            return
        follow_up = str(getattr(provider, "follow_up", "") or "").strip()
        logger.info("Hotword detected: Friday")
        if follow_up:
            logger.info("Hotword follow-up command: %s", follow_up)
        if command_queue is not None and follow_up:
            command_queue.put(follow_up)
        if activation_event is not None:
            activation_event.set()
        else:
            import pyautogui

            pyautogui.hotkey("alt", "j")
    except KeyboardInterrupt:
        logger.info("Hotword listener stopped by user")
    except Exception:
        logger.exception("Hotword listener failed")
