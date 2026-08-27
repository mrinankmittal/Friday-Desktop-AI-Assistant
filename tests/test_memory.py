from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from friday.memory import format_memory_list, guess_kind
from friday.memory.store import path_is_allowed
from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName
from friday.rag.extract import is_blocked
from friday.tools.builtin import build_legacy_registry
from friday.tools.memory_tools import (
    MEMORY_FORGET,
    MEMORY_INGEST,
    MEMORY_LIST,
    MEMORY_REMEMBER,
    RAG_SEARCH,
)
from friday.tools.types import ToolContext
from tests.helpers import make_memory_store


class ClassifyMemoryTests(unittest.TestCase):
    def test_remember_and_list(self) -> None:
        remembered = classify("remember that my name is kabir")
        self.assertEqual(remembered.name, IntentName.MEMORY)
        self.assertEqual(remembered.extra["action"], "remember")
        self.assertEqual(remembered.extra["content"], "my name is kabir")

        spoken = classify("my name is raunak mittal remember it")
        self.assertEqual(spoken.extra["action"], "remember")
        self.assertEqual(spoken.extra["content"], "my name is raunak mittal")

        stated = classify("my name is raunak mittal")
        self.assertEqual(stated.extra["action"], "remember")
        self.assertEqual(stated.extra["content"], "my name is raunak mittal")

        note = classify("note that I prefer tea")
        self.assertEqual(note.extra["content"], "i prefer tea")

        listed = classify("what do you remember")
        self.assertEqual(listed.extra["action"], "list")
        self.assertEqual(classify("list memories").extra["action"], "list")
        self.assertEqual(classify("do you remember").extra["action"], "list")

    def test_forget_and_search(self) -> None:
        forgotten = classify("forget that my name is kabir")
        self.assertEqual(forgotten.extra["action"], "forget")
        self.assertEqual(forgotten.extra["text"], "my name is kabir")
        self.assertEqual(classify("forget memory 3").extra["id"], 3)

        search = classify("search my documents for goa")
        self.assertEqual(search.name, IntentName.RESEARCH)
        self.assertEqual(search.extra["action"], "docs")
        self.assertEqual(search.extra["query"], "goa")
        self.assertEqual(
            classify("what do my notes say about vacation").extra["search_query"],
            "vacation",
        )
        self.assertEqual(
            classify("do you remember my name").extra["search_query"],
            "my name",
        )
        known = classify("do you know my name")
        self.assertEqual(known.name, IntentName.MEMORY)
        self.assertEqual(known.extra["action"], "search")
        self.assertEqual(known.extra["search_query"], "my name")
        self.assertEqual(classify("what is my name").extra["search_query"], "my name")
        self.assertEqual(classify("what's my name").extra["search_query"], "my name")
        self.assertEqual(classify("who am i").extra["search_query"], "my name")
        self.assertEqual(
            classify("do you know my friend's name").extra["search_query"],
            "my friend's name",
        )
        self.assertEqual(
            classify("do you know my friends name").extra["search_query"],
            "my friend's name",
        )
        self.assertEqual(
            classify("what's my friend's name").extra["search_query"],
            "my friend's name",
        )
        self.assertEqual(
            classify("do you know papa's name").extra["search_query"],
            "my dad's name",
        )
        self.assertEqual(
            classify("do you know my mom's name").extra["search_query"],
            "my mom's name",
        )
        friend = classify("my friend's name is riya")
        self.assertEqual(friend.extra["action"], "remember")
        self.assertEqual(friend.extra["content"], "my friend's name is riya")
        spoken_friend = classify("my friends name is riya remember it")
        self.assertEqual(spoken_friend.extra["action"], "remember")
        self.assertEqual(
            spoken_friend.extra["content"],
            "my friend's name is riya",
        )
        mom = classify("my mom's name is Seema")
        self.assertEqual(mom.extra["content"], "my mom's name is Seema")
        cased = classify("my name is Mrinank Mittal")
        self.assertEqual(cased.extra["content"], "my name is Mrinank Mittal")

    def test_ingest_phrase(self) -> None:
        ingest = classify(r"remember this file C:\notes\todo.txt")
        self.assertEqual(ingest.extra["action"], "ingest")
        self.assertIn("todo.txt", ingest.extra["path"])

        ingest2 = classify("ingest notes.md")
        self.assertEqual(ingest2.extra["action"], "ingest")
        self.assertEqual(ingest2.extra["path"], "notes.md")

    def test_does_not_steal_existing_commands(self) -> None:
        self.assertEqual(classify("list windows").extra["action"], "windows")
        self.assertEqual(classify("what is python").name, IntentName.CHAT)
        self.assertEqual(classify("do you know python").name, IntentName.CHAT)
        self.assertEqual(classify("search the web for python").name, IntentName.BROWSER)
        self.assertEqual(classify("open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("I don't remember").name, IntentName.CHAT)
        self.assertEqual(classify("forget it").name, IntentName.CHAT)


class MemoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder, self.store, self.root = make_memory_store()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_remember_list_forget_round_trip(self) -> None:
        saved = self.store.remember("my name is kabir")
        self.assertEqual(guess_kind("I prefer dark mode"), "preference")
        listed = self.store.list_memories()
        self.assertEqual(listed[0].content, "my name is kabir")
        self.assertIn("Memory", format_memory_list(listed))
        removed = self.store.forget(text="kabir")
        self.assertEqual(removed[0].id, saved.id)
        self.assertEqual(self.store.list_memories(), [])

    def test_search_memories(self) -> None:
        self.store.remember("my favorite color is blue")
        hits = self.store.search("favorite color")
        self.assertTrue(hits)
        self.assertIn("blue", hits[0].text)
        self.store.remember("my name is kabir")
        name_hits = self.store.search("do you know my name")
        self.assertTrue(name_hits)
        self.assertIn("kabir", name_hits[0].text.lower())

        friend_hits = self.store.search("my friend's name")
        self.assertEqual(friend_hits, [])

        self.store.remember("my friend's name is riya")
        friend_hits = self.store.search("do you know my friend's name")
        self.assertTrue(friend_hits)
        self.assertIn("riya", friend_hits[0].text.lower())
        self.assertNotIn("kabir", friend_hits[0].text.lower())

        own_hits = self.store.search("my name")
        self.assertTrue(own_hits)
        self.assertIn("kabir", own_hits[0].text.lower())
        self.assertNotIn("riya", own_hits[0].text.lower())

        mom_hits = self.store.search("do you know my mom's name")
        self.assertEqual(mom_hits, [])
        self.store.remember("my mom's name is seema")
        mom_hits = self.store.search("do you know mummy's name")
        self.assertTrue(mom_hits)
        self.assertIn("seema", mom_hits[0].text.lower())
        self.assertNotIn("kabir", mom_hits[0].text.lower())
        own_hits = self.store.search("do you know my name")
        self.assertIn("kabir", own_hits[0].text.lower())
        self.assertNotIn("seema", own_hits[0].text.lower())

    def test_ingest_and_search_document(self) -> None:
        path = self.root / "vacation.txt"
        path.write_text(
            "Vacation plans: go to Goa in December. Pack sunscreen.",
            encoding="utf-8",
        )
        info = self.store.ingest_file(path, (self.root,))
        self.assertGreaterEqual(info.chunks, 1)
        hits = self.store.search("Goa")
        self.assertTrue(any("Goa" in hit.text for hit in hits))
        self.assertTrue(any(hit.title == "vacation.txt" for hit in hits))

    def test_ingest_rejects_secrets_and_outside_allowlist(self) -> None:
        secret = self.root / "cookies.json"
        secret.write_text("token", encoding="utf-8")
        self.assertTrue(is_blocked(secret))
        with self.assertRaises(PermissionError):
            self.store.ingest_file(secret, (self.root,))

        other = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        try:
            outsider = Path(other.name) / "note.txt"
            outsider.write_text("hi", encoding="utf-8")
            self.assertFalse(path_is_allowed(outsider, (self.root,)))
            with self.assertRaises(PermissionError):
                self.store.ingest_file(outsider, (self.root,))
        finally:
            other.cleanup()

    def test_task_and_conversation_rows(self) -> None:
        self.store.record_turn("user", "hello")
        self.store.record_turn("assistant", "hi")
        self.store.record_task(
            task_id="abc",
            request="hello",
            intent="chat",
            status="succeeded",
            observation="ok",
        )
        self.assertEqual(self.store.recent_messages()[-1], ("assistant", "hi"))


class MemoryToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder, self.store, self.root = make_memory_store()
        self.registry = build_legacy_registry(
            _UnusedActions(),
            memory=self.store,
        )
        self.context = ToolContext(task_id="mem-test")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_remember_list_forget_tools(self) -> None:
        saved = self.registry.invoke(
            MEMORY_REMEMBER, {"content": "I live in Pune"}, self.context
        )
        self.assertTrue(saved.ok)
        listed = self.registry.invoke(MEMORY_LIST, {}, self.context)
        self.assertIn("Pune", listed.data["reply"])
        forgotten = self.registry.invoke(
            MEMORY_FORGET, {"text": "pune"}, self.context
        )
        self.assertTrue(forgotten.ok)

    def test_ingest_and_search_tools(self) -> None:
        path = self.root / "todo.md"
        path.write_text("Buy milk and bread.", encoding="utf-8")
        ingested = self.registry.invoke(
            MEMORY_INGEST, {"path": str(path)}, self.context
        )
        self.assertTrue(ingested.ok)
        self.assertIn("todo.md", ingested.data["reply"])
        found = self.registry.invoke(RAG_SEARCH, {"query": "milk"}, self.context)
        self.assertIn("milk", found.data["reply"].lower())

    def test_logs_redact_memory_content(self) -> None:
        with self.assertLogs("friday.tools", level="INFO") as captured:
            self.registry.invoke(
                MEMORY_REMEMBER, {"content": "secret-fact-xyz"}, self.context
            )
        combined = "\n".join(captured.output)
        self.assertNotIn("secret-fact-xyz", combined)


class _UnusedActions:
    def play_youtube(self, query: str) -> None:
        return None

    def open_app(self, query: str) -> None:
        return None

    def find_contact(self, query: str) -> tuple:
        return (0, 0)

    def whatsapp(self, mobile_no, message, flag, name) -> bool:
        return False

    def chatbot(self, query: str) -> str:
        return "should not be called"


if __name__ == "__main__":
    unittest.main()
