"""Speech-to-text cleanup and command-aware alternative picking."""

from __future__ import annotations

import unittest

from friday.language.stt_fix import fix_transcript, pick_best_transcript, score_for_command
from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName


class SttFixTests(unittest.TestCase):
    def test_strips_wake_name(self) -> None:
        self.assertEqual(fix_transcript("Friday open chrome"), "open chrome")
        self.assertEqual(fix_transcript("hey friday open calendar"), "open calendar")

    def test_common_mishearings(self) -> None:
        self.assertEqual(fix_transcript("open what's app"), "open whatsapp")
        self.assertEqual(fix_transcript("take screen shot"), "take a screenshot")
        self.assertEqual(fix_transcript("list the windows"), "list of windows")
        self.assertEqual(fix_transcript("open calender"), "open calendar")
        self.assertEqual(
            fix_transcript("what is the weather in delhi"),
            "what's the weather in delhi",
        )

    def test_picks_command_like_alternative(self) -> None:
        chosen = pick_best_transcript(
            [
                "whether in Mumbai",
                "weather in mumbai",
                "whether",
            ]
        )
        self.assertEqual(chosen, "weather in mumbai")
        self.assertGreater(
            score_for_command("weather in mumbai"),
            score_for_command("whether"),
        )

    def test_fixed_transcript_routes_to_intent(self) -> None:
        intent = classify(fix_transcript("Friday open calendar"))
        self.assertEqual(intent.name, IntentName.OPEN)
        self.assertEqual(intent.query, "open calendar")

        weather = classify(fix_transcript("what is the weather in delhi"))
        self.assertEqual(weather.name, IntentName.WEATHER)


if __name__ == "__main__":
    unittest.main()
