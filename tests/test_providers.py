from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from friday.providers.factory import (
    get_stt_provider,
    get_tts_provider,
    get_wake_provider,
    set_stt_provider,
    set_tts_provider,
    set_wake_provider,
)
from friday.providers.fake import FakeStt, FakeTts, FakeWakeWord
from friday.providers.settings import VoiceSettings, resolve_wake_provider_name
from friday.providers.stt import FasterWhisperStt, GoogleStt, configure_command_recognizer, listen_with_retry
from friday.providers.tts import BilingualTts, SapiTts
from friday.providers.types import SttResult, wake_model_path
from friday.providers.wake import GoogleWakeWord, follow_up_after_wake


class VoiceSettingsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = VoiceSettings.from_env()
        self.assertEqual(settings.stt_provider, "google")
        self.assertEqual(settings.tts_provider, "sapi")
        self.assertEqual(settings.wake_provider, "auto")
        self.assertEqual(settings.stt_language, "en-IN")

    def test_effective_stt_language_adds_en_us_for_english_only(self) -> None:
        settings = VoiceSettings(stt_language="en-IN")
        self.assertTrue(settings.english_only())
        effective = settings.effective_stt_language()
        self.assertIn("en-IN", effective)
        self.assertIn("en-US", effective)

    def test_env_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FRIDAY_STT_PROVIDER": "faster_whisper",
                "FRIDAY_TTS_PROVIDER": "sapi",
                "FRIDAY_WAKE_PROVIDER": "google",
            },
            clear=True,
        ):
            settings = VoiceSettings.from_env()
        self.assertEqual(settings.stt_provider, "faster_whisper")
        self.assertEqual(settings.wake_provider, "google")


class WakeResolutionTests(unittest.TestCase):
    def test_auto_without_model_uses_google(self) -> None:
        settings = VoiceSettings(wake_provider="auto")
        with patch.object(Path, "is_file", return_value=False):
            self.assertEqual(resolve_wake_provider_name(settings), "google")

    def test_auto_with_model_uses_openwakeword(self) -> None:
        settings = VoiceSettings(wake_provider="auto")
        with patch.object(Path, "is_file", return_value=True):
            self.assertEqual(resolve_wake_provider_name(settings), "openwakeword")

    def test_requested_openwakeword_without_model_falls_back(self) -> None:
        settings = VoiceSettings(wake_provider="openwakeword")
        with patch.object(Path, "is_file", return_value=False):
            self.assertEqual(resolve_wake_provider_name(settings), "google")

    def test_model_path_is_models_friday_onnx(self) -> None:
        self.assertEqual(wake_model_path().name, "friday.onnx")
        self.assertEqual(wake_model_path().parent.name, "models")


class FactoryTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_stt_provider(None)
        set_tts_provider(None)
        set_wake_provider(None)

    def test_default_providers_are_google_and_sapi(self) -> None:
        with patch.dict(os.environ, {"FRIDAY_STT_PROVIDER": "google"}, clear=False):
            set_stt_provider(None)
            set_tts_provider(None)
            self.assertIsInstance(get_stt_provider(VoiceSettings(stt_provider="google")), GoogleStt)
            self.assertIsInstance(get_tts_provider(VoiceSettings(tts_provider="sapi")), SapiTts)
            set_tts_provider(None)
            self.assertIsInstance(get_tts_provider(VoiceSettings(tts_provider="auto")), BilingualTts)

    def test_faster_whisper_selected_by_name(self) -> None:
        set_stt_provider(None)
        provider = get_stt_provider(VoiceSettings(stt_provider="faster_whisper"))
        self.assertIsInstance(provider, FasterWhisperStt)

    def test_wake_without_model_is_google(self) -> None:
        set_wake_provider(None)
        with patch.object(Path, "is_file", return_value=False):
            provider = get_wake_provider(VoiceSettings(wake_provider="auto"))
        self.assertIsInstance(provider, GoogleWakeWord)

    def test_inject_fakes(self) -> None:
        stt = FakeStt(replies=["Open Chrome"])
        tts = FakeTts()
        set_stt_provider(stt)
        set_tts_provider(tts)
        result = get_stt_provider().listen()
        self.assertEqual(result, SttResult(text="Open Chrome", status="ok"))
        get_tts_provider().speak("hello")
        self.assertEqual(tts.spoken, ["hello"])


class FakeProviderTests(unittest.TestCase):
    def test_fake_stt_timeout_when_empty(self) -> None:
        self.assertEqual(FakeStt().listen().status, "timeout")

    def test_fake_wake(self) -> None:
        wake = FakeWakeWord(heard=True)
        self.assertTrue(wake.wait())
        self.assertEqual(wake.waits, 1)


class ShortCommandListenTests(unittest.TestCase):
    def test_command_recognizer_hears_short_words(self) -> None:
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        configure_command_recognizer(recognizer, source=None, adjust_noise=False)
        self.assertLessEqual(recognizer.phrase_threshold, 0.15)
        self.assertGreaterEqual(recognizer.pause_threshold, 1.0)

    def test_full_command_pause_is_longer_than_confirm(self) -> None:
        import speech_recognition as sr

        command = sr.Recognizer()
        configure_command_recognizer(
            command, source=None, adjust_noise=False, for_confirm=False
        )
        confirm = sr.Recognizer()
        configure_command_recognizer(
            confirm, source=None, adjust_noise=False, for_confirm=True
        )
        self.assertGreater(command.pause_threshold, confirm.pause_threshold)
        self.assertGreaterEqual(command.pause_threshold, 0.6)
        self.assertLessEqual(confirm.pause_threshold, 0.5)

    def test_follow_up_after_wake(self) -> None:
        self.assertEqual(follow_up_after_wake("friday"), "")
        self.assertEqual(follow_up_after_wake("Friday yes"), "yes")
        self.assertEqual(follow_up_after_wake("friday sure"), "sure")
        self.assertEqual(follow_up_after_wake("friday, yes send it"), "yes send it")
        self.assertEqual(follow_up_after_wake("फ्राइडे हाँ"), "हाँ")
        self.assertEqual(follow_up_after_wake("फ्राइडे क्रोम खोलो"), "क्रोम खोलो")

    def test_listen_retries_unknown(self) -> None:
        class SequenceStt:
            name = "sequence"

            def __init__(self) -> None:
                self.calls = 0

            def listen(self, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return SttResult(status="unknown")
                return SttResult(text="yes", status="ok")

        provider = SequenceStt()
        result = listen_with_retry(
            provider,
            language="en-in",
            timeout=8.0,
            phrase_time_limit=4.0,
            adjust_noise=True,
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.text, "yes")
        self.assertEqual(provider.calls, 2)

    def test_listen_retry_keeps_long_phrase_limit(self) -> None:
        class SequenceStt:
            name = "sequence"

            def __init__(self) -> None:
                self.calls = 0
                self.limits: list[float] = []
                self.languages: list[str] = []

            def listen(self, **kwargs):
                self.calls += 1
                self.limits.append(kwargs.get("phrase_time_limit"))
                self.languages.append(kwargs.get("language"))
                if self.calls == 1:
                    return SttResult(status="unknown")
                return SttResult(text="list of windows", status="ok")

        provider = SequenceStt()
        result = listen_with_retry(
            provider,
            language="en-in",
            timeout=20.0,
            phrase_time_limit=12.0,
            adjust_noise=True,
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(provider.limits, [12.0, 12.0])
        self.assertEqual(provider.languages[1], "en-US")

    def test_bilingual_unknown_retries_us_english(self) -> None:
        class SequenceStt:
            name = "sequence"

            def __init__(self) -> None:
                self.languages: list[str] = []

            def listen(self, **kwargs):
                self.languages.append(kwargs.get("language"))
                if len(self.languages) == 1:
                    return SttResult(status="unknown")
                return SttResult(text="open chrome", status="ok")

        provider = SequenceStt()
        result = listen_with_retry(
            provider,
            language="hi-IN,en-IN",
            timeout=20.0,
            phrase_time_limit=12.0,
            adjust_noise=True,
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(provider.languages[1], "en-US")


if __name__ == "__main__":
    unittest.main()
