"""Emailing a contact by name.

Sending mail used to demand a full address spoken aloud, because the ``email``
column on the ``contacts`` table was never populated or read. The CSV importer
now pulls Google's ``E-mail N - Value`` columns and the send path looks a name
up there, so "send email to Kabir saying hi" resolves to a stored address.
"""

from __future__ import annotations

import csv
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.db import import_contacts
from friday.integrations.contacts import resolve_contact_email
from friday.integrations.pending import clear_pending, get_pending
from friday.orchestrator import handle_user_request
from friday.os_adapters.fake import FakeOsAdapter
from friday.browser.fake import FakeBrowser
from friday.providers.fake import FakeVision
from friday.integrations.store import IntegrationStore
from friday.orchestrator.models import TaskStatus
from tests.helpers import make_memory_store


def _make_contacts_table(db_path: Path, rows: list[tuple[str, str, str | None]]) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY, "
            "name VARCHAR(200), mobile_no VARCHAR(255), email VARCHAR(255) NULL)"
        )
        connection.executemany(
            "INSERT INTO contacts (name, mobile_no, email) VALUES (?, ?, ?)", rows
        )
        connection.commit()


class ResolveContactEmailTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self._folder.name) / "friday.db"
        _make_contacts_table(
            self.db_path,
            [
                ("Kabir", "9958184743", "kabir@example.com"),
                ("Kabir Sharma", "9000000000", "kabir.sharma@work.com"),
                ("Papa", "9810765085", None),
                ("Mummy", "9891326111", "shalinimittal27@gmail.com"),
            ],
        )

    def tearDown(self) -> None:
        self._folder.cleanup()

    def test_exact_name_returns_the_email(self) -> None:
        result = resolve_contact_email("Kabir", self.db_path)
        self.assertTrue(result.has_email)
        self.assertEqual(result.email, "kabir@example.com")
        self.assertTrue(result.matched)

    def test_lookup_is_case_insensitive(self) -> None:
        self.assertEqual(
            resolve_contact_email("kabir", self.db_path).email, "kabir@example.com"
        )

    def test_exact_full_name_beats_prefix(self) -> None:
        self.assertEqual(
            resolve_contact_email("kabir sharma", self.db_path).email,
            "kabir.sharma@work.com",
        )

    def test_known_contact_without_email_is_matched_but_emailless(self) -> None:
        result = resolve_contact_email("Papa", self.db_path)
        self.assertTrue(result.matched)
        self.assertFalse(result.has_email)
        self.assertEqual(result.name, "Papa")

    def test_blank_stored_email_is_treated_as_missing(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE contacts SET email = '' WHERE name = 'Kabir Sharma'"
            )
            connection.commit()
        result = resolve_contact_email("Kabir Sharma", self.db_path)
        self.assertTrue(result.matched)
        self.assertIsNone(result.email)

    def test_mummy_aliases_resolve_to_the_stored_address(self) -> None:
        for spoken in ("mummy", "mom", "mother", "my mummy", "mommy"):
            with self.subTest(spoken=spoken):
                result = resolve_contact_email(spoken, self.db_path)
                self.assertTrue(result.has_email, spoken)
                self.assertEqual(result.email, "shalinimittal27@gmail.com")
                self.assertEqual(result.name, "Mummy")

    def test_unknown_name_is_not_matched(self) -> None:
        result = resolve_contact_email("Nobody", self.db_path)
        self.assertFalse(result.matched)
        self.assertFalse(result.has_email)

    def test_blank_query_is_not_matched(self) -> None:
        self.assertFalse(resolve_contact_email("   ", self.db_path).matched)

    def test_missing_database_is_safe(self) -> None:
        missing = Path(self._folder.name) / "nope.db"
        self.assertFalse(resolve_contact_email("Kabir", missing).matched)

    def test_missing_table_is_safe(self) -> None:
        empty = Path(self._folder.name) / "empty.db"
        sqlite3.connect(empty).close()
        self.assertFalse(resolve_contact_email("Kabir", empty).matched)


class ImportContactsEmailTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._folder.name)
        self.db_path = self.root / "friday.db"
        self.csv_path = self.root / "contacts.csv"

    def tearDown(self) -> None:
        self._folder.cleanup()

    def _write_csv(self, rows: list[dict[str, str]], columns: list[str]) -> None:
        with self.csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _run_import(self):
        with (
            patch("engine.db.DB_PATH", self.db_path),
            patch("engine.db.CONTACTS_CSV_PATH", self.csv_path),
        ):
            return import_contacts()

    def _emails(self) -> dict[str, str | None]:
        with sqlite3.connect(self.db_path) as connection:
            return {
                str(name): email
                for name, email in connection.execute(
                    "SELECT name, email FROM contacts"
                )
            }

    def test_email_column_is_imported(self) -> None:
        self._write_csv(
            [
                {
                    "First Name": "Kabir",
                    "Phone 1 - Value": "9958184743",
                    "E-mail 1 - Value": "kabir@example.com",
                }
            ],
            ["First Name", "Phone 1 - Value", "E-mail 1 - Value"],
        )
        result = self._run_import()
        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.with_email, 1)
        self.assertEqual(self._emails()["Kabir"], "kabir@example.com")

    def test_existing_contact_gets_its_email_backfilled(self) -> None:
        _make_contacts_table(self.db_path, [("Kabir", "9958184743", None)])
        self._write_csv(
            [
                {
                    "First Name": "Kabir",
                    "Phone 1 - Value": "9958184743",
                    "E-mail 1 - Value": "kabir@example.com",
                }
            ],
            ["First Name", "Phone 1 - Value", "E-mail 1 - Value"],
        )
        result = self._run_import()
        self.assertEqual(result.inserted, 0)
        self.assertEqual(result.updated, 1)
        self.assertEqual(self._emails()["Kabir"], "kabir@example.com")

    def test_a_csv_without_emails_reports_none(self) -> None:
        self._write_csv(
            [{"First Name": "Papa", "Phone 1 - Value": "9810765085"}],
            ["First Name", "Phone 1 - Value"],
        )
        result = self._run_import()
        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.with_email, 0)

    def test_the_first_valid_address_wins(self) -> None:
        self._write_csv(
            [
                {
                    "First Name": "Multi",
                    "Phone 1 - Value": "9000000001",
                    "E-mail 1 - Value": "  ",
                    "E-mail 2 - Value": "real@example.com ::: alt@example.com",
                }
            ],
            ["First Name", "Phone 1 - Value", "E-mail 1 - Value", "E-mail 2 - Value"],
        )
        self._run_import()
        self.assertEqual(self._emails()["Multi"], "real@example.com")

    def test_missing_required_column_raises(self) -> None:
        self._write_csv([{"First Name": "X"}], ["First Name"])
        with self.assertRaises(ValueError):
            self._run_import()


class EmailByNameOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spoken: list[str] = []
        self._memory_folder, self.memory, _root = make_memory_store()
        _make_contacts_table(
            self.memory.db_path,
            [
                ("Kabir", "9958184743", "kabir@example.com"),
                ("Papa", "9810765085", None),
                ("Mummy", "9891326111", "shalinimittal27@gmail.com"),
            ],
        )
        self.store = IntegrationStore(self.memory.db_path)
        self.store.save("gmail", {"access_token": "tok"})
        self.env = patch.dict(
            os.environ,
            {"FRIDAY_USER_EMAIL": "", "FRIDAY_REQUIRE_CONFIRM_SEND": "true"},
            clear=False,
        )
        self.env.start()
        clear_pending()

    def tearDown(self) -> None:
        clear_pending()
        self.env.stop()
        self._memory_folder.cleanup()

    def _handle(self, query: str):
        return handle_user_request(
            query,
            speak=self.spoken.append,
            listen=lambda: "",
            os_adapter=FakeOsAdapter(),
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=self.memory,
        )

    def test_email_to_a_named_contact_resolves_the_stored_address(self) -> None:
        result = self._handle("send an email to Kabir saying running late")
        self.assertEqual(result.observation, "awaiting_confirm")
        pending = get_pending()
        self.assertIsNotNone(pending)
        self.assertEqual(pending.to, "kabir@example.com")
        self.assertIn("kabir@example.com", result.assistant_reply)

    def test_a_known_contact_without_an_email_explains_itself(self) -> None:
        result = self._handle("send an email to Papa saying hi")
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("Papa", result.assistant_reply)
        self.assertIsNone(get_pending())

    def test_an_unknown_name_asks_for_an_address(self) -> None:
        result = self._handle("send an email to Zaphod saying hi")
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("email address", result.assistant_reply.lower())
        self.assertIsNone(get_pending())

    def test_a_dictated_address_still_works(self) -> None:
        result = self._handle("send an email to rahul@example.com saying hi")
        self.assertEqual(result.observation, "awaiting_confirm")
        self.assertEqual(get_pending().to, "rahul@example.com")

    def _handle_with_body(self, query: str, body: str):
        return handle_user_request(
            query,
            speak=self.spoken.append,
            listen=lambda: body,
            os_adapter=FakeOsAdapter(),
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=self.memory,
        )

    def test_name_without_a_body_asks_for_it_and_keeps_the_contact(self) -> None:
        # "send email to Kabir" (no "saying ...") used to fall to chat, where the
        # LLM invented a fake "sent to <you>" reply. It must resolve the contact
        # and ask for the message instead.
        result = self._handle_with_body("send email to Kabir", "call me back")
        self.assertEqual(result.observation, "awaiting_confirm")
        self.assertIn("What should the email say?", self.spoken)
        pending = get_pending()
        self.assertIsNotNone(pending)
        self.assertEqual(pending.to, "kabir@example.com")
        self.assertEqual(pending.body, "call me back")

    def test_bare_name_email_never_falls_back_to_the_user(self) -> None:
        # The reported bug: "send email to <name>" quietly addressed the user's
        # own inbox. It must never resolve to a self address for a real name.
        result = self._handle_with_body("email Kabir", "hello there")
        self.assertEqual(get_pending().to, "kabir@example.com")
        self.assertNotEqual(get_pending().to, os.environ.get("FRIDAY_USER_EMAIL"))

    def test_send_email_to_mummy_uses_her_address_not_mine(self) -> None:
        for phrase in (
            "send email to mummy",
            "email to mummy",
            "send email to mummy that",
            "send email to mom",
            "send email to mother",
        ):
            with self.subTest(phrase=phrase):
                clear_pending()
                self.spoken.clear()
                result = self._handle_with_body(phrase, "how are you")
                pending = get_pending()
                self.assertEqual(result.observation, "awaiting_confirm", phrase)
                self.assertIsNotNone(pending)
                self.assertEqual(pending.to, "shalinimittal27@gmail.com")
                self.assertNotIn("mrinank", (pending.to or "").lower())


class MummyUtteranceTests(unittest.TestCase):
    """The exact phrases from the live session must not fall through to chat."""

    def test_logged_phrases_are_email_sends_to_mummy(self) -> None:
        from friday.orchestrator.intents import classify
        from friday.orchestrator.models import IntentName

        for phrase in (
            "send email to mummy",
            "email to mummy",
            "send email to mummy that",
            "send an email to mummy",
        ):
            with self.subTest(phrase=phrase):
                intent = classify(phrase)
                self.assertEqual(intent.name, IntentName.INTEGRATION, phrase)
                self.assertEqual(intent.extra.get("action"), "email_send")
                self.assertEqual(intent.extra.get("to"), "mummy")
                self.assertNotEqual(intent.extra.get("to"), "me")

    def test_my_does_not_steal_mummy(self) -> None:
        from friday.orchestrator.intents import classify

        intent = classify("send email to mummy saying hello")
        self.assertEqual(intent.extra.get("to"), "mummy")
        self.assertEqual(intent.extra.get("body"), "hello")


if __name__ == "__main__":
    unittest.main()
