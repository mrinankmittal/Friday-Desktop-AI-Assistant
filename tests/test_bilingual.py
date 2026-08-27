"""Hindi + English listening, speaking, and command routing."""

from __future__ import annotations

import types
import unittest

import speech_recognition as sr

from friday.integrations.confirm import is_confirm_no, is_confirm_yes, is_short_voice_reply
from friday.integrations.pending import PendingSend, clear_pending, set_pending
from friday.language.pronounce import (
    pronounce_assistant_name,
    spoken_assistant_name,
    text_for_speech,
    voice_looks_indic,
)
from friday.language.romanize import has_devanagari, romanize_devanagari
from friday.language.bilingual import (
    detect_language,
    fallback_stt_language,
    find_indic_voice_id,
    localize_reply,
    normalize_command,
    parse_stt_languages,
    pick_transcript,
    pick_tts_voice_id,
    reset_user_language,
    set_user_language,
    speak_language_for,
    user_language,
    whisper_language_code,
)
from friday.news.headlines import speak_headlines
from friday.providers.fake import FakeTts
from friday.providers.tts import BilingualTts, reset_hindi_tts_cooldown, synthesize_neural
from friday.providers.winrt_speak import pick_hindi_voice
from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName
from friday.providers.stt import clip_seconds, recognize_google_best
from friday.weather.india import normalize_place, speak_forecast


class LanguageHelpersTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_user_language()

    def test_parses_language_lists(self) -> None:
        self.assertEqual(parse_stt_languages("hi-IN,en-IN"), ["hi-IN", "en-IN"])
        self.assertEqual(parse_stt_languages("en-in"), ["en-in"])
        self.assertEqual(parse_stt_languages(""), ["en-in"])

    def test_whisper_auto_detects_mixed_languages(self) -> None:
        self.assertIsNone(whisper_language_code("hi-IN,en-IN"))
        self.assertEqual(whisper_language_code("en-in"), "en")
        self.assertEqual(whisper_language_code("hi-IN"), "hi")

    def test_fallback_keeps_en_in_to_en_us(self) -> None:
        self.assertEqual(fallback_stt_language("en-in"), "en-US")
        self.assertEqual(fallback_stt_language("hi-IN,en-IN"), "en-US")
        self.assertEqual(fallback_stt_language("hi-IN"), "en-IN")

    def test_detects_hindi_and_hinglish(self) -> None:
        self.assertEqual(detect_language("क्रोम खोलो"), "hi")
        self.assertEqual(detect_language("chrome kholo"), "hi")
        self.assertEqual(detect_language("open chrome"), "en")
        self.assertEqual(detect_language("how are you doing"), "en")
        self.assertEqual(detect_language("हाउ आर यू डूइंग"), "en")
        self.assertEqual(detect_language("फ्राइडे कैन यू हियर मी"), "en")
        self.assertEqual(detect_language("Friday can you hear me"), "en")
        self.assertEqual(detect_language("राम राम क्या हाल है"), "hi")
        self.assertEqual(detect_language("क्या कर रही हो फ्राइडे"), "hi")
        self.assertEqual(detect_language("kya kar rahi ho Friday"), "hi")

    def test_english_and_hindi_speak_in_parallel(self) -> None:
        set_user_language("hi")
        self.assertEqual(speak_language_for("मैं ठीक हूँ।"), "hi")
        self.assertEqual(speak_language_for("Opening Chrome."), "hi")
        set_user_language("en")
        self.assertEqual(speak_language_for("I’m doing well."), "en")
        self.assertEqual(speak_language_for("मैं ठीक हूँ।"), "hi")
        self.assertEqual(speak_language_for("हाउ आर यू"), "en")

    def test_picks_english_command_over_weak_hindi(self) -> None:
        self.assertEqual(
            pick_transcript(["open chrome", "ओपन"]),
            "open chrome",
        )

    def test_spoken_english_is_not_shown_as_hindi_letters(self) -> None:
        self.assertEqual(
            pick_transcript(["how are you doing", "हाउ आर यू डूइंग"]),
            "how are you doing",
        )
        self.assertEqual(
            pick_transcript(["I want to know what you are capable", "आई वांट टू नो व्हाट यू अरे कैपेबल"]),
            "I want to know what you are capable",
        )
        self.assertEqual(
            pick_transcript(["Friday can you hear me", "फ्राइडे कैन यू हियर मी"]),
            "Friday can you hear me",
        )

    def test_spoken_hindi_keeps_hindi_letters(self) -> None:
        self.assertEqual(
            pick_transcript(["chrome kholo", "क्रोम खोलो"]),
            "क्रोम खोलो",
        )
        self.assertEqual(
            pick_transcript(["ram ram kya haal hai", "राम राम क्या हाल है"]),
            "राम राम क्या हाल है",
        )

    def test_tts_picks_hindi_voice_by_name(self) -> None:
        voices = [
            types.SimpleNamespace(id="zira", name="Microsoft Zira Desktop"),
            types.SimpleNamespace(id="hemant", name="Microsoft Hemant Desktop - Hindi"),
        ]
        self.assertEqual(pick_tts_voice_id(voices, "hi"), "hemant")

    def test_tts_prefers_kalpana_when_both_hindi_voices_exist(self) -> None:
        voices = [
            types.SimpleNamespace(id="hemant", name="Microsoft Hemant - Hindi"),
            types.SimpleNamespace(id="kalpana", name="Microsoft Kalpana - Hindi"),
        ]
        self.assertEqual(pick_tts_voice_id(voices, "hi"), "kalpana")

    def test_english_voice_stays_index_one(self) -> None:
        voices = [
            types.SimpleNamespace(id="david", name="Microsoft David"),
            types.SimpleNamespace(id="zira", name="Microsoft Zira"),
        ]
        self.assertEqual(pick_tts_voice_id(voices, "en"), "zira")

    def test_english_still_picks_zira_when_other_voices_exist(self) -> None:
        voices = [
            types.SimpleNamespace(id="david", name="Microsoft David"),
            types.SimpleNamespace(id="heera", name="Microsoft Heera Desktop - English (India)"),
            types.SimpleNamespace(id="zira", name="Microsoft Zira"),
        ]
        self.assertEqual(pick_tts_voice_id(voices, "en"), "zira")
        self.assertIsNone(find_indic_voice_id(voices))

    def test_onecore_kalpana_is_not_used_through_sapi(self) -> None:
        voices = [
            types.SimpleNamespace(
                id=r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices\Tokens\MSTTS_V110_hiIN_KalpanaM",
                name="Microsoft Kalpana - Hindi (India)",
            ),
        ]
        self.assertIsNone(find_indic_voice_id(voices))

    def test_winrt_prefers_kalpana(self) -> None:
        voices = [
            types.SimpleNamespace(display_name="Microsoft Hemant", language="hi-IN", id="hemant"),
            types.SimpleNamespace(display_name="Microsoft Kalpana", language="hi-IN", id="kalpana"),
            types.SimpleNamespace(display_name="Microsoft Zira", language="en-US", id="zira"),
        ]
        self.assertEqual(pick_hindi_voice(voices).id, "kalpana")

    def test_localize_known_replies(self) -> None:
        set_user_language("hi")
        self.assertIn("सुना नहीं", localize_reply("Sorry, I missed that. Please say the command again."))
        self.assertIn("खोल रही हूँ", localize_reply("Opening calculator"))
        self.assertEqual(speak_language_for("Opening Chrome."), "hi")
        set_user_language("en")
        self.assertEqual(speak_language_for("Opening Chrome."), "en")
        self.assertEqual(speak_language_for("मैं ठीक हूँ।"), "hi")
        self.assertEqual(localize_reply("Opening calculator", "en"), "Opening calculator")


class PronounceNameTests(unittest.TestCase):
    def test_hindi_voice_says_devanagari(self) -> None:
        self.assertEqual(spoken_assistant_name("hi", indic_voice=True), "फ्राय डे")
        self.assertEqual(
            pronounce_assistant_name("I am Friday.", "hi", indic_voice=True),
            "I am फ्राय डे.",
        )
        self.assertEqual(
            pronounce_assistant_name("मैं Friday हूँ।", "hi", indic_voice=True),
            "मैं फ्राय डे हूँ।",
        )
        self.assertEqual(
            pronounce_assistant_name("Friday's reply", "hi", indic_voice=True),
            "फ्राय डे की reply",
        )
        self.assertEqual(
            pronounce_assistant_name("मैं फ्राइडे हूँ।", "hi", indic_voice=True),
            "मैं फ्राय डे हूँ।",
        )

    def test_english_voice_keeps_friday(self) -> None:
        self.assertIsNone(spoken_assistant_name("en"))
        self.assertEqual(pronounce_assistant_name("I am Friday.", "en"), "I am Friday.")
        self.assertEqual(
            pronounce_assistant_name("I am Friday.", "hi", indic_voice=False),
            "I am Friday.",
        )

    def test_other_languages_use_phonetic_form(self) -> None:
        self.assertEqual(
            pronounce_assistant_name("Soy Friday.", "es"),
            "Soy Fráidei.",
        )
        self.assertEqual(
            pronounce_assistant_name("Je suis Friday.", "fr"),
            "Je suis Fraydé.",
        )
        self.assertEqual(
            pronounce_assistant_name("Ich bin Friday.", "de"),
            "Ich bin Fraidei.",
        )

    def test_detects_hindi_sapi_voice(self) -> None:
        voices = [
            types.SimpleNamespace(id="zira", name="Microsoft Zira Desktop"),
            types.SimpleNamespace(id="hemant", name="Microsoft Hemant Desktop - Hindi"),
        ]
        self.assertTrue(voice_looks_indic(voices, "hemant"))
        self.assertFalse(voice_looks_indic(voices, "zira"))

    def test_english_voice_romanizes_hindi_so_it_can_speak(self) -> None:
        spoken = text_for_speech(
            "फ्राइडे हूँ मैं। मैं ठीक हूँ।",
            "hi",
            indic_voice=False,
        )
        self.assertFalse(has_devanagari(spoken))
        self.assertIn("Friday", spoken)
        self.assertRegex(spoken.lower(), r"hoon|hun")

    def test_romanizes_everyday_hindi(self) -> None:
        spoken = romanize_devanagari("क्या हाल है")
        self.assertFalse(has_devanagari(spoken))
        self.assertIn("kya", spoken.lower())
        self.assertIn("hai", spoken.lower())


class NaturalHindiTtsTests(unittest.TestCase):
    def test_hindi_goes_to_the_neural_voice(self) -> None:
        from pathlib import Path
        from unittest.mock import patch

        english = FakeTts()
        tts = BilingualTts(english=english)

        def fake_synth(text, dest, **_kwargs):
            Path(dest).write_bytes(b"audio" * 16)

        with (
            patch("friday.providers.tts.winrt_hindi_available", return_value=False),
            patch("friday.providers.tts.sapi_indic_available", return_value=False),
            patch("friday.providers.tts.neural_hindi_available", return_value=True),
            patch("friday.providers.tts.synthesize_neural", side_effect=fake_synth) as syn,
            patch("friday.providers.tts.play_mp3") as play,
        ):
            tts.speak("राम राम, मैं ठीक हूँ।", language="hi")
        self.assertTrue(syn.called)
        self.assertIn("राम", syn.call_args[0][0])
        self.assertTrue(play.called)
        self.assertEqual(english.spoken, [])

    def test_english_stays_on_sapi(self) -> None:
        english = FakeTts()
        tts = BilingualTts(english=english)
        tts.speak("Opening calculator", language="en")
        self.assertEqual(english.spoken, ["Opening calculator"])

    def test_hindi_prefers_local_windows_voice(self) -> None:
        from unittest.mock import patch

        english = FakeTts()
        tts = BilingualTts(english=english)
        with (
            patch("friday.providers.tts.winrt_hindi_available", return_value=False),
            patch("friday.providers.tts.sapi_indic_available", return_value=True),
            patch("friday.providers.tts.synthesize_neural") as syn,
            patch("friday.providers.tts.play_mp3") as play,
        ):
            tts.speak("राम राम, मैं ठीक हूँ।", language="hi")
        self.assertEqual(english.spoken, ["राम राम, मैं ठीक हूँ।"])
        self.assertFalse(syn.called)
        self.assertFalse(play.called)

    def test_hindi_uses_windows_onecore_voice(self) -> None:
        from pathlib import Path
        from unittest.mock import patch

        english = FakeTts()
        tts = BilingualTts(english=english)

        def fake_winrt(text, dest, **_kwargs):
            Path(dest).write_bytes(b"RIFF" + b"audio" * 16)

        with (
            patch("friday.providers.tts.winrt_hindi_available", return_value=True),
            patch("friday.providers.tts.synthesize_winrt", side_effect=fake_winrt) as syn,
            patch("friday.providers.tts.play_wav") as play,
            patch("friday.providers.tts.synthesize_neural") as neural,
        ):
            tts.speak("मैं ठीक हूँ।", language="hi")
        self.assertTrue(syn.called)
        self.assertIn("ठीक", syn.call_args[0][0])
        self.assertTrue(play.called)
        self.assertFalse(neural.called)
        self.assertEqual(english.spoken, [])

    def test_google_hindi_is_used_when_edge_fails(self) -> None:
        from pathlib import Path
        from unittest.mock import patch
        import tempfile

        reset_hindi_tts_cooldown()

        def fake_gtts(text, dest, **_kwargs):
            Path(dest).write_bytes(b"audio" * 16)

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "hi.mp3"
            with (
                patch("friday.providers.tts._synthesize_edge", side_effect=RuntimeError("500")),
                patch("friday.providers.tts._synthesize_gtts", side_effect=fake_gtts) as gtts,
                patch("friday.providers.tts.time.sleep"),
            ):
                synthesize_neural("मैं ठीक हूँ", dest)
            self.assertTrue(gtts.called)
            self.assertTrue(dest.is_file())


class NormalizeCommandTests(unittest.TestCase):
    def test_hindi_and_hinglish_open(self) -> None:
        self.assertEqual(normalize_command("क्रोम खोलो").lower(), "open chrome")
        self.assertEqual(normalize_command("chrome kholo").lower(), "open chrome")
        self.assertEqual(normalize_command("kholo notepad").lower(), "open notepad")
        self.assertEqual(normalize_command("नोटपैड खोलो").lower(), "open notepad")

    def test_weather_and_news(self) -> None:
        self.assertEqual(normalize_command("मौसम बताओ").lower(), "what's the weather")
        self.assertEqual(normalize_command("दिल्ली में मौसम").lower(), "weather in delhi")
        self.assertEqual(normalize_command("mausam batao").lower(), "what's the weather")
        self.assertEqual(normalize_command("खबरें बताओ").lower(), "what's the news")
        self.assertEqual(normalize_command("खेल की खबरें").lower(), "sports news")

    def test_media_write_and_stop(self) -> None:
        self.assertEqual(normalize_command("गाना चलाओ").lower(), "play music")
        self.assertEqual(normalize_command("gaana chalao").lower(), "play music")
        self.assertEqual(normalize_command("स्क्रीनशॉट लो").lower(), "take a screenshot")
        self.assertEqual(normalize_command("रुक जाओ").lower(), "stop listening")
        self.assertEqual(
            normalize_command("नोटपैड में लिखो hello").lower(),
            "write hello in notepad",
        )
        self.assertEqual(
            normalize_command("notepad kholo aur hello likho").lower(),
            "open notepad and write hello",
        )

    def test_whatsapp_and_yes_no(self) -> None:
        self.assertEqual(
            normalize_command("पापा को मैसेज भेजो").lower().strip(),
            "send message to पापा",
        )
        self.assertEqual(
            normalize_command("papa ko message bhejo").lower().strip(),
            "send message to papa",
        )
        self.assertEqual(normalize_command("हाँ"), "yes")
        self.assertEqual(normalize_command("नहीं"), "no")

    def test_leaves_english_commands_alone(self) -> None:
        self.assertEqual(normalize_command("open chrome"), "open chrome")
        self.assertEqual(normalize_command("play music"), "play music")
        self.assertEqual(
            normalize_command("write hello friday to file phase9-note.txt"),
            "write hello friday to file phase9-note.txt",
        )
        self.assertEqual(
            normalize_command("play despacito on youtube"),
            "play despacito on youtube",
        )


class ClassifyHindiTests(unittest.TestCase):
    def test_hindi_commands_route_like_english(self) -> None:
        self.assertEqual(classify("क्रोम खोलो").name, IntentName.OPEN)
        self.assertEqual(classify("chrome kholo").name, IntentName.OPEN)
        self.assertEqual(classify("मौसम बताओ").name, IntentName.WEATHER)
        self.assertEqual(classify("दिल्ली में मौसम").extra.get("place"), "delhi")
        self.assertEqual(classify("खबरें बताओ").name, IntentName.NEWS)
        self.assertEqual(classify("खेल की खबरें").extra.get("topic"), "sports")
        self.assertEqual(classify("गाना चलाओ").name, IntentName.MEDIA)
        self.assertEqual(classify("स्क्रीनशॉट लो").extra.get("action"), "screenshot")
        self.assertEqual(classify("रुक जाओ").name, IntentName.STOP)
        self.assertEqual(classify("पापा को मैसेज भेजो").name, IntentName.WHATSAPP)
        self.assertEqual(classify("papa ko call karo").name, IntentName.WHATSAPP)
        self.assertEqual(classify("नोटपैड में लिखो hello").name, IntentName.OS)

    def test_hindi_chat_stays_chat(self) -> None:
        intent = classify("तुम कैसे हो")
        self.assertEqual(intent.name, IntentName.CHAT)
        self.assertIn("तुम", intent.query)

    def test_does_not_steal_english_commands(self) -> None:
        self.assertEqual(classify("open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("play music").name, IntentName.MEDIA)
        self.assertEqual(classify("play despacito on youtube").name, IntentName.YOUTUBE)
        self.assertEqual(classify("google for weather in delhi").name, IntentName.BROWSER)
        self.assertEqual(classify("send message to papa").name, IntentName.WHATSAPP)
        self.assertEqual(
            classify("write hello friday to file phase9-note.txt").extra["action"],
            "write",
        )
        self.assertEqual(classify("what is python").name, IntentName.CHAT)
        self.assertEqual(classify("मुझे मौसम पसंद है").name, IntentName.CHAT)
        self.assertEqual(classify("can you see notepad on the screen").extra["needle"], "notepad")
        self.assertEqual(classify("is chrome on the screen").extra["action"], "verify")

    def test_hindi_yes_confirms_pending_send(self) -> None:
        self.addCleanup(clear_pending)
        set_pending(
            PendingSend(kind="email", to="someone@example.com", body="hi"),
            prompt="Say send it.",
        )
        intent = classify("हाँ")
        self.assertEqual(intent.name, IntentName.INTEGRATION)
        self.assertEqual(intent.extra.get("action"), "confirm_pending")


class ConfirmHindiTests(unittest.TestCase):
    def test_hindi_yes_and_no(self) -> None:
        self.assertTrue(is_confirm_yes("हाँ"))
        self.assertTrue(is_confirm_yes("जी"))
        self.assertTrue(is_confirm_no("नहीं"))
        self.assertTrue(is_short_voice_reply("हाँ"))
        self.assertFalse(is_confirm_no("हाँ"))


class DualSttTests(unittest.TestCase):
    def test_picks_among_language_results(self) -> None:
        class Dual:
            def recognize_google(self, audio, language="en-in"):
                if clip_seconds(audio) < 2.0:
                    raise sr.UnknownValueError()
                if str(language).lower().startswith("hi"):
                    return "क्रोम खोलो"
                return "chrome kholo"

        audio = sr.AudioData(b"\x01\x00" * 16000 * 3, 16000, 2)
        heard = recognize_google_best(Dual(), audio, language="hi-IN,en-IN")
        self.assertEqual(normalize_command(heard).lower(), "open chrome")


class SpokenReplyTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_user_language()

    def test_weather_and_news_follow_user_language(self) -> None:
        set_user_language("hi")
        forecast = speak_forecast(
            {
                "place": "Mumbai",
                "temp_c": 31,
                "condition": "partly cloudy skies",
                "high_c": 33,
                "low_c": 26,
            }
        )
        self.assertIn("डिग्री सेल्सियस", forecast)
        self.assertIn("Mumbai", forecast)
        news = speak_headlines(
            {"label": "top", "query": "", "headlines": ["India win"]}
        )
        self.assertIn("हेडलाइन", news)
        self.assertEqual(normalize_place("दिल्ली"), "New Delhi")


if __name__ == "__main__":
    unittest.main()
