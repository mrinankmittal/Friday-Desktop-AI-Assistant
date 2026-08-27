"""Guards for one-word replies like "yes" and "sure".

Google's Web Speech endpoint returns no result at all for a bare interjection,
even from a clean one-second clip, while content words of the same length
("stop", "cancel", "hello") transcribe fine. That silently swallowed every
confirmation, so short clips are retried as a doubled clip and the duplicated
transcript is collapsed back to the single spoken word.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import speech_recognition as sr

from friday.integrations.confirm import (
    is_confirm_no,
    is_confirm_yes,
    is_short_voice_reply,
)
from friday.integrations.pending import PendingSend, clear_pending, set_pending
from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName
from friday.providers.stt import (
    GoogleStt,
    clip_seconds,
    collapse_repeat,
    doubled_clip,
    recognize_google_text,
)
from friday.providers.types import SttResult

RATE = 16000
WIDTH = 2

INTERJECTIONS = ["yes", "yeah", "yep", "sure", "ok", "okay"]
REFUSALS = ["no", "nope", "cancel"]


def clip(seconds: float) -> sr.AudioData:
    return sr.AudioData(b"\x01\x00" * int(RATE * seconds), RATE, WIDTH)


class FakeRecognizer:
    """Mimics Google: unknown for the short clip, text for the doubled one."""

    def __init__(self, *, heard: str, threshold: float = 1.5) -> None:
        self.heard = heard
        self.threshold = threshold
        self.calls: list[float] = []

    def recognize_google(self, audio: sr.AudioData, language: str = "en-in") -> str:
        length = clip_seconds(audio)
        self.calls.append(length)
        if length < self.threshold:
            raise sr.UnknownValueError()
        return f"{self.heard} {self.heard}"


class ClipShapeTests(unittest.TestCase):
    def test_clip_seconds_reads_the_duration(self) -> None:
        self.assertAlmostEqual(clip_seconds(clip(1.0)), 1.0, places=3)
        self.assertAlmostEqual(clip_seconds(clip(0.25)), 0.25, places=3)

    def test_an_empty_clip_is_zero_seconds(self) -> None:
        self.assertEqual(clip_seconds(sr.AudioData(b"", RATE, WIDTH)), 0.0)

    def test_doubling_keeps_the_audio_format(self) -> None:
        doubled = doubled_clip(clip(1.0))
        self.assertEqual(doubled.sample_rate, RATE)
        self.assertEqual(doubled.sample_width, WIDTH)

    def test_doubling_repeats_the_clip_with_a_gap(self) -> None:
        doubled = doubled_clip(clip(1.0))
        self.assertAlmostEqual(clip_seconds(doubled), 2.4, places=2)

    def test_the_spoken_audio_is_present_twice(self) -> None:
        source = clip(0.5)
        doubled = doubled_clip(source)
        self.assertEqual(doubled.frame_data.count(source.frame_data), 2)


class CollapseTests(unittest.TestCase):
    def test_a_doubled_word_becomes_one_word(self) -> None:
        for word in INTERJECTIONS + REFUSALS:
            with self.subTest(word=word):
                self.assertEqual(collapse_repeat(f"{word} {word}"), word)

    def test_casing_from_google_does_not_block_collapsing(self) -> None:
        self.assertEqual(collapse_repeat("Nope nope"), "Nope")

    def test_a_doubled_phrase_becomes_one_phrase(self) -> None:
        self.assertEqual(collapse_repeat("send it send it"), "send it")
        self.assertEqual(collapse_repeat("go ahead go ahead"), "go ahead")

    def test_a_tripled_word_still_collapses(self) -> None:
        self.assertEqual(collapse_repeat("yes yes yes"), "yes")

    def test_a_single_word_is_left_alone(self) -> None:
        self.assertEqual(collapse_repeat("yes"), "yes")

    def test_an_ordinary_command_is_never_rewritten(self) -> None:
        for text in ["open notepad", "what is the time", "send it now", ""]:
            with self.subTest(text=text):
                self.assertEqual(collapse_repeat(text), text)

    def test_a_repeated_word_inside_a_sentence_is_kept(self) -> None:
        self.assertEqual(collapse_repeat("that is very very good"), "that is very very good")


class ShortClipRecognitionTests(unittest.TestCase):
    def test_a_bare_interjection_is_recovered(self) -> None:
        for word in INTERJECTIONS + REFUSALS:
            with self.subTest(word=word):
                recognizer = FakeRecognizer(heard=word)
                heard = recognize_google_text(recognizer, clip(1.0), language="en-in")
                self.assertEqual(heard, word)

    def test_recovery_costs_exactly_one_extra_request(self) -> None:
        recognizer = FakeRecognizer(heard="yes")
        recognize_google_text(recognizer, clip(1.0), language="en-in")
        self.assertEqual(len(recognizer.calls), 2)

    def test_the_retry_sends_the_doubled_clip(self) -> None:
        recognizer = FakeRecognizer(heard="yes")
        recognize_google_text(recognizer, clip(1.0), language="en-in")
        first, second = recognizer.calls
        self.assertAlmostEqual(second, first * 2 + 0.4, places=2)

    def test_a_clip_google_already_understood_is_not_retried(self) -> None:
        recognizer = FakeRecognizer(heard="stop", threshold=0.0)
        heard = recognize_google_text(recognizer, clip(1.0), language="en-in")
        self.assertEqual(len(recognizer.calls), 1)
        self.assertEqual(heard, "stop stop")

    def test_a_long_clip_is_not_retried(self) -> None:
        recognizer = FakeRecognizer(heard="anything", threshold=99.0)
        with self.assertRaises(sr.UnknownValueError):
            recognize_google_text(recognizer, clip(4.0), language="en-in")
        self.assertEqual(len(recognizer.calls), 1)

    def test_a_short_clip_google_never_hears_still_reports_unknown(self) -> None:
        recognizer = FakeRecognizer(heard="anything", threshold=99.0)
        with self.assertRaises(sr.UnknownValueError):
            recognize_google_text(recognizer, clip(1.0), language="en-in")
        self.assertEqual(len(recognizer.calls), 2)

    def test_a_service_error_is_not_swallowed(self) -> None:
        class Broken:
            def recognize_google(self, audio, language="en-in"):
                raise sr.RequestError("no network")

        with self.assertRaises(sr.RequestError):
            recognize_google_text(Broken(), clip(1.0), language="en-in")


class GoogleSttResultTests(unittest.TestCase):
    """The provider must turn the recovered text into a usable result."""

    def _listen(self, outcome) -> SttResult:
        with (
            patch("speech_recognition.Microphone"),
            patch("speech_recognition.Recognizer.listen", return_value=clip(1.0)),
            patch("friday.providers.stt.recognize_google_text", side_effect=outcome),
        ):
            return GoogleStt().listen(adjust_noise=False, phrase_time_limit=4.0)

    def test_a_recovered_yes_reaches_the_caller(self) -> None:
        result = self._listen(lambda *a, **k: "yes")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.text, "yes")

    def test_an_unrecoverable_clip_is_unknown(self) -> None:
        result = self._listen(sr.UnknownValueError())
        self.assertEqual(result.status, "unknown")

    def test_a_blank_transcript_is_unknown_not_an_empty_command(self) -> None:
        result = self._listen(lambda *a, **k: "   ")
        self.assertEqual(result.status, "unknown")


class ConfirmRoutingTests(unittest.TestCase):
    """Once heard, a one-word reply must act on the waiting send."""

    def setUp(self) -> None:
        self.addCleanup(clear_pending)
        clear_pending()

    def _pending(self) -> None:
        set_pending(
            PendingSend(kind="email", to="someone@example.com", body="hi"),
            prompt="Say send it.",
        )

    def test_every_interjection_confirms_a_waiting_send(self) -> None:
        for word in INTERJECTIONS:
            with self.subTest(word=word):
                self._pending()
                intent = classify(word)
                self.assertIs(intent.name, IntentName.INTEGRATION)
                self.assertEqual(intent.extra.get("action"), "confirm_pending")

    def test_every_refusal_cancels_a_waiting_send(self) -> None:
        for word in REFUSALS:
            with self.subTest(word=word):
                self._pending()
                intent = classify(word)
                self.assertEqual(intent.extra.get("action"), "cancel_pending")

    def test_a_doubled_transcript_that_slipped_through_still_cancels(self) -> None:
        for text in ["no no", "nope nope", "no thanks"]:
            with self.subTest(text=text):
                self._pending()
                intent = classify(text)
                self.assertEqual(intent.extra.get("action"), "cancel_pending")

    def test_a_doubled_transcript_that_slipped_through_still_confirms(self) -> None:
        for text in ["yes yes", "sure sure", "ok ok"]:
            with self.subTest(text=text):
                self._pending()
                intent = classify(text)
                self.assertEqual(intent.extra.get("action"), "confirm_pending")

    def test_these_words_are_treated_as_immediate_replies(self) -> None:
        for word in INTERJECTIONS + REFUSALS:
            with self.subTest(word=word):
                self.assertTrue(is_short_voice_reply(word))

    def test_yes_and_no_stay_on_opposite_sides(self) -> None:
        for word in INTERJECTIONS:
            with self.subTest(word=word):
                self.assertTrue(is_confirm_yes(word))
                self.assertFalse(is_confirm_no(word))
        for word in REFUSALS:
            with self.subTest(word=word):
                self.assertTrue(is_confirm_no(word))
                self.assertFalse(is_confirm_yes(word))

    def test_nothing_is_stolen_when_no_send_is_waiting(self) -> None:
        for word in INTERJECTIONS + ["no"]:
            with self.subTest(word=word):
                self.assertIsNot(classify(word).name, IntentName.INTEGRATION)


if __name__ == "__main__":
    unittest.main()
