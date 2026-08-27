from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from pathlib import Path

from friday.code import patch_workspace_file, read_workspace_file, unittest_argv
from friday.files.ops import day_window, move_file, read_file, search_files, write_file
from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName
from friday.productivity import split_reminder
from friday.tools.builtin import build_legacy_registry
from friday.tools.types import ToolContext
from tests.helpers import make_memory_store


class ClassifyPhase9Tests(unittest.TestCase):
    def test_file_phrases(self) -> None:
        found = classify("find file phase9-invoice.pdf")
        self.assertEqual(found.name, IntentName.FILE)
        self.assertEqual(found.extra["action"], "search")
        self.assertEqual(found.extra["needle"], "phase9-invoice.pdf")

        yesterday = classify("find a file downloaded yesterday")
        self.assertEqual(yesterday.extra["folder"], "downloads")
        self.assertEqual(yesterday.extra["when"], "yesterday")

        folder = classify("search downloads for invoice")
        self.assertEqual(folder.extra["needle"], "invoice")
        self.assertEqual(folder.extra["folder"], "downloads")

        listed = classify("list files in downloads")
        self.assertEqual(listed.extra["action"], "search")
        self.assertEqual(listed.extra["folder"], "downloads")

        shown = classify("show me the file")
        self.assertEqual(shown.name, IntentName.FILE)
        self.assertEqual(shown.extra["action"], "show_last")

        opened_file = classify("open a file")
        self.assertEqual(opened_file.name, IntentName.FILE)
        self.assertEqual(opened_file.extra["action"], "search")

        named_open = classify("open the file phase9-note.txt")
        self.assertEqual(named_open.extra["action"], "read")
        self.assertEqual(named_open.extra["path"], "phase9-note.txt")

        folder_shown = classify("show me the files in downloads")
        self.assertEqual(folder_shown.extra["folder"], "downloads")

        spoken = classify("the downloads and search the files")
        self.assertEqual(spoken.name, IntentName.FILE)
        self.assertEqual(spoken.extra["folder"], "downloads")

        regarding = classify(
            "search the download regarding the files which I downloaded"
        )
        self.assertEqual(regarding.name, IntentName.FILE)
        self.assertEqual(regarding.extra["folder"], "downloads")

        bare = classify("search the downloads")
        self.assertEqual(bare.extra["folder"], "downloads")

        read = classify("read file phase9-note.txt")
        self.assertEqual(read.extra["action"], "read")
        self.assertEqual(read.extra["path"], "phase9-note.txt")

        written = classify("write hello friday to file phase9-note.txt on the desktop")
        self.assertEqual(written.extra["action"], "write")
        self.assertEqual(written.extra["text"], "hello friday")
        self.assertEqual(written.extra["path"], "phase9-note.txt")
        self.assertEqual(written.extra["folder"], "desktop")

        moved = classify("move file phase9-note.txt to downloads")
        self.assertEqual(moved.extra["action"], "move")
        self.assertEqual(moved.extra["source"], "phase9-note.txt")
        self.assertEqual(moved.extra["destination"], "downloads")

    def test_code_and_productivity_phrases(self) -> None:
        source = classify("read orchestrator.py in this repo")
        self.assertEqual(source.name, IntentName.CODE)
        self.assertEqual(source.extra["action"], "read")
        self.assertEqual(source.extra["path"], "orchestrator.py")

        tests = classify("run the tests")
        self.assertEqual(tests.name, IntentName.CODE)
        self.assertEqual(tests.extra["action"], "test")

        targeted = classify("run tests for test_memory")
        self.assertEqual(targeted.extra["target"], "test_memory")

        patched = classify("replace hello with goodbye in notes.py")
        self.assertEqual(patched.extra["old"], "hello")
        self.assertEqual(patched.extra["new"], "goodbye")
        self.assertEqual(patched.extra["path"], "notes.py")

        note = classify("add a note buy milk")
        self.assertEqual(note.name, IntentName.PRODUCTIVITY)
        self.assertEqual(note.extra["action"], "notes_add")
        self.assertEqual(note.extra["content"], "buy milk")

        reminder = classify("remind me to call papa tomorrow")
        self.assertEqual(reminder.extra["action"], "reminders_add")
        self.assertEqual(reminder.extra["content"], "call papa tomorrow")

        listed = classify("list my notes")
        self.assertEqual(listed.extra["action"], "notes_list")
        self.assertEqual(classify("what are my reminders").extra["action"], "reminders_list")

    def test_does_not_steal_existing_commands(self) -> None:
        self.assertEqual(classify("open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("open a file").name, IntentName.FILE)
        self.assertEqual(classify("show me the file").name, IntentName.FILE)
        self.assertEqual(classify("play despacito on youtube").name, IntentName.YOUTUBE)
        self.assertEqual(classify("read the screen").name, IntentName.VISION)
        self.assertEqual(classify("read this page").name, IntentName.BROWSER)
        self.assertEqual(classify("read the clipboard").name, IntentName.OS)
        self.assertEqual(classify("tell me where is the screenshot").name, IntentName.CHAT)
        self.assertEqual(
            classify("search my documents for goa").name, IntentName.RESEARCH
        )
        self.assertEqual(classify("note that I prefer tea").name, IntentName.MEMORY)
        self.assertEqual(classify("remind me later").name, IntentName.CHAT)
        self.assertEqual(classify("what is python").name, IntentName.CHAT)
        self.assertEqual(classify("forget it").name, IntentName.CHAT)
        self.assertEqual(classify("call papa").name, IntentName.WHATSAPP)
        self.assertEqual(classify("search the web for python").name, IntentName.BROWSER)


class FileOpsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder, self.store, self.root = make_memory_store()
        self.allow = (self.root,)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_search_read_write_move(self) -> None:
        path = write_file(self.root / "phase9-invoice.txt", "paid", self.allow)
        hits = search_files(needle="phase9-invoice", allow_paths=self.allow)
        self.assertEqual(hits[0], path)
        text = read_file(path, self.allow)
        self.assertEqual(text, "paid")
        moved = move_file(path, self.root / "archive.txt", self.allow)
        self.assertTrue(moved.is_file())
        self.assertFalse(path.exists())

    def test_rejects_blocked_and_outside(self) -> None:
        secret = self.root / "cookies.json"
        secret.write_text("token", encoding="utf-8")
        with self.assertRaises(PermissionError):
            read_file(secret, self.allow)
        with self.assertRaises(PermissionError):
            write_file(Path.home() / "phase9-not-allowed.txt", "no", self.allow)

    def test_yesterday_window(self) -> None:
        start, end = day_window("yesterday", now=datetime(2026, 8, 20, 19, 0, 0))
        self.assertEqual(end - start, timedelta(days=1))


class CodeAndNotesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder, self.store, self.root = make_memory_store()
        (self.root / "sample.py").write_text("value = 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_read_and_patch(self) -> None:
        text = read_workspace_file(Path("sample.py"), self.root)
        self.assertIn("value = 1", text)
        patch_workspace_file(Path("sample.py"), "value = 1", "value = 2", self.root)
        updated = (self.root / "sample.py").read_text(encoding="utf-8")
        self.assertIn("value = 2", updated)

    def test_unittest_argv_is_fixed(self) -> None:
        argv = unittest_argv("test_memory")
        self.assertEqual(argv[1:3], ["-m", "unittest"])
        self.assertEqual(argv[-1], "tests.test_memory")
        with self.assertRaises(ValueError):
            unittest_argv("test_memory; rm -rf /")

    def test_notes_and_reminders(self) -> None:
        note = self.store.add_note("buy milk")
        self.assertEqual(self.store.list_notes()[0].content, "buy milk")
        self.store.delete_note(note.id)
        self.assertEqual(self.store.list_notes(), [])
        content, due = split_reminder("call papa tomorrow")
        self.assertEqual(content, "call papa")
        self.assertIsNotNone(due)
        reminder = self.store.add_reminder(content, due_at=due)
        listed = self.store.list_reminders()
        self.assertEqual(listed[0].id, reminder.id)
        past = (datetime.now().astimezone() - timedelta(minutes=5)).replace(
            microsecond=0
        ).isoformat()
        due_item = self.store.add_reminder("stretch", due_at=past)
        self.assertEqual(self.store.due_reminders()[0].id, due_item.id)
        self.store.complete_reminder(due_item.id)
        self.assertEqual(self.store.due_reminders(), [])


class Phase9ToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder, self.store, self.root = make_memory_store()
        self.registry = build_legacy_registry(
            _UnusedActions(),
            memory=self.store,
        )
        self.context = ToolContext(task_id="phase9")
        (self.root / "phase9-note.txt").write_text("hello", encoding="utf-8")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_file_and_note_tools(self) -> None:
        found = self.registry.invoke(
            "files.search", {"needle": "phase9-note"}, self.context
        )
        self.assertTrue(found.ok)
        self.assertIn("phase9-note.txt", found.data["reply"])
        read = self.registry.invoke(
            "files.read", {"path": "phase9-note.txt"}, self.context
        )
        self.assertIn("hello", read.data["reply"])
        saved = self.registry.invoke(
            "notes.add", {"content": "pack charger"}, self.context
        )
        self.assertTrue(saved.ok)
        listed = self.registry.invoke("notes.list", {}, self.context)
        self.assertIn("pack charger", listed.data["reply"])
        reminded = self.registry.invoke(
            "reminders.add", {"content": "stretch in 10 minutes"}, self.context
        )
        self.assertTrue(reminded.ok)
        self.assertIn("stretch", reminded.data["reply"].lower())


class _UnusedActions:
    def play_youtube(self, query: str) -> None:
        return None

    def open_app(self, query: str) -> None:
        return None

    def find_contact(self, query: str) -> tuple:
        return ("0", "x")

    def whatsapp(self, mobile_no, message, flag, name) -> bool:
        return False

    def chatbot(self, query: str) -> str:
        return "should not be called"


if __name__ == "__main__":
    unittest.main()
