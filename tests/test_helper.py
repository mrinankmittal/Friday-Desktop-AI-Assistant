from __future__ import annotations

import unittest

from engine.helper import comms_search_text, match_named_contact, message_after_contact


class ContactMatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contacts = [
            ("Mummy", "9891326111"),
            ("Papa", "9810765085"),
            ("Kabir", "9958184743"),
        ]

    def test_every_contact_keeps_the_words_after_the_name(self) -> None:
        cases = (
            ("kabir i will be late", "Kabir", "i will be late"),
            ("mummy reach home soon", "Mummy", "reach home soon"),
            ("papa call me later", "Papa", "call me later"),
        )
        for text, expected_name, expected_message in cases:
            name, _mobile, message = match_named_contact(text, self.contacts)
            self.assertEqual(name, expected_name, text)
            self.assertEqual(message, expected_message, text)

    def test_command_words_in_the_body_are_kept(self) -> None:
        text = comms_search_text("send message to papa call me later", {"friday"})
        self.assertEqual(text, "papa call me later")
        name, _mobile, message = match_named_contact(text, self.contacts)
        self.assertEqual(name, "Papa")
        self.assertEqual(message, "call me later")

    def test_name_only_has_empty_message(self) -> None:
        name, _mobile, message = match_named_contact("mummy", self.contacts)
        self.assertEqual(name, "Mummy")
        self.assertEqual(message, "")

    def test_longer_name_wins(self) -> None:
        contacts = [("Mary", "1"), ("Mary Jane", "2")]
        name, _mobile, message = match_named_contact("mary jane hello", contacts)
        self.assertEqual(name, "Mary Jane")
        self.assertEqual(message, "hello")

    def test_message_after_contact_strips_command_words(self) -> None:
        query = "friday send message to kabir i will be late"
        self.assertEqual(comms_search_text(query, {"friday"}), "kabir i will be late")
        self.assertEqual(
            message_after_contact(query, "Kabir", extra_words={"friday"}),
            "i will be late",
        )


if __name__ == "__main__":
    unittest.main()
