"""Create a source file and show the last one.

'Make a c plus plus file of hello' used to fall through to chat, which printed
markdown and never wrote a file. The filename is whatever they say — hello is
not required. 'Show me the file' opens the last one Friday wrote.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from friday.files.create import plan_new_file, starter_text
from friday.files.ops import write_file
from friday.files.recent import clear_last_file, last_file
from friday.files.run_source import find_cxx_compiler, run_source_file
from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName
from friday.os_adapters.fake import FakeOsAdapter
from friday.tools.builtin import build_legacy_registry
from friday.tools.file_tools import FILES_READ, FILES_RUN, FILES_WRITE
from friday.tools.types import ToolContext
from friday.browser.fake import FakeBrowser
from friday.providers.fake import FakeVision
from tests.helpers import make_memory_store


class PlanNewFileTests(unittest.TestCase):
    def test_spoken_cpp_hello(self) -> None:
        path, text = plan_new_file(kind="c plus plus", name="hello")
        self.assertEqual(path, "hello.cpp")
        self.assertIn("#include <iostream>", text)
        self.assertIn("hello", text)

    def test_named_extension_wins(self) -> None:
        path, text = plan_new_file(name="notes.md")
        self.assertEqual(path, "notes.md")
        self.assertTrue(text.startswith("# "))

    def test_any_stem_is_the_filename(self) -> None:
        path, text = plan_new_file(kind="cpp", name="calculator")
        self.assertEqual(path, "calculator.cpp")
        self.assertIn("calculator", text)

    def test_printed_text_is_not_the_filename(self) -> None:
        path, text = plan_new_file(kind="cpp", name="demo", says="hello")
        self.assertEqual(path, "demo.cpp")
        self.assertIn('"hello"', text)

    def test_blank_name_means_ask(self) -> None:
        path, text = plan_new_file(kind="cpp", name="")
        self.assertEqual(path, "")
        self.assertIn("iostream", text)

    def test_kind_word_is_not_a_filename(self) -> None:
        path, text = plan_new_file(kind="cpp", name="c plus plus")
        self.assertEqual(path, "")
        self.assertIn("iostream", text)


class ClassifyCreateFileTests(unittest.TestCase):
    def test_the_logged_utterance_writes_hello_cpp(self) -> None:
        intent = classify("i want you to make a c plus plus file of hello")
        self.assertEqual(intent.name, IntentName.FILE)
        self.assertEqual(intent.extra["action"], "write")
        self.assertEqual(intent.extra["path"], "hello.cpp")
        self.assertIn("iostream", intent.extra["text"])
        self.assertEqual(intent.extra["folder"], "desktop")

    def test_make_a_cpp_file(self) -> None:
        intent = classify("make a cpp file")
        self.assertEqual(intent.extra["action"], "write")
        self.assertEqual(intent.extra["path"], "")
        self.assertEqual(intent.extra["kind"], "cpp")

    def test_stt_c_plus_plus_uses_the_spoken_name(self) -> None:
        intent = classify(
            "i want you to make a c + + file of calculator where it shows hello"
        )
        self.assertEqual(intent.name, IntentName.FILE)
        self.assertEqual(intent.extra["path"], "calculator.cpp")
        self.assertIn('"hello"', intent.extra["text"])

    def test_named_file_is_not_hello(self) -> None:
        intent = classify("make a cpp file named weather")
        self.assertEqual(intent.extra["path"], "weather.cpp")

    def test_trailing_of_still_asks_for_name(self) -> None:
        intent = classify("i want you to make a c plus plus file of")
        self.assertEqual(intent.name, IntentName.FILE)
        self.assertEqual(intent.extra["action"], "write")
        self.assertEqual(intent.extra["path"], "")
        self.assertTrue(intent.extra.get("open"))

    def test_make_opens_and_can_run(self) -> None:
        intent = classify(
            "make a cpp file of demo where it shows hi and compile and run"
        )
        self.assertEqual(intent.extra["path"], "demo.cpp")
        self.assertTrue(intent.extra.get("open"))
        self.assertTrue(intent.extra.get("run"))
        self.assertIn('"hi"', intent.extra["text"])

    def test_compile_and_run_is_run_last(self) -> None:
        for phrase in ("compile and run", "run the file", "compile it", "run it"):
            intent = classify(phrase)
            self.assertEqual(intent.name, IntentName.FILE, phrase)
            self.assertEqual(intent.extra["action"], "run", phrase)

    def test_and_show_marks_the_write_to_open(self) -> None:
        intent = classify("make a cpp file of hello and show")
        self.assertTrue(intent.extra.get("open"))

    def test_show_me_the_file_is_the_last_file(self) -> None:
        for phrase in (
            "show me the file",
            "show the file",
            "show it",
            "open the file",
            "sure and also show",
        ):
            with self.subTest(phrase=phrase):
                intent = classify(phrase)
                self.assertEqual(intent.name, IntentName.FILE, phrase)
                self.assertEqual(intent.extra["action"], "show_last", phrase)

    def test_named_show_still_reads_that_file(self) -> None:
        intent = classify("show me the file phase9-note.txt")
        self.assertEqual(intent.extra["action"], "read")
        self.assertEqual(intent.extra["path"], "phase9-note.txt")

    def test_does_not_steal_other_commands(self) -> None:
        self.assertEqual(classify("make a note buy milk").name, IntentName.PRODUCTIVITY)
        self.assertEqual(classify("show me the screenshot").name, IntentName.OS)
        self.assertEqual(classify("show me the files in downloads").extra["action"], "search")
        self.assertEqual(classify("open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("sure").name, IntentName.CHAT)
        self.assertEqual(classify("write hello friday to file phase9-note.txt").extra["action"], "write")


class WriteCppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder, _store, self.root = make_memory_store()
        clear_last_file()

    def tearDown(self) -> None:
        clear_last_file()
        self.folder.cleanup()

    def test_cpp_is_an_allowed_text_file(self) -> None:
        path = write_file(self.root / "hello.cpp", starter_text(".cpp", "Hello"), (self.root,))
        self.assertTrue(path.is_file())
        self.assertIn("iostream", path.read_text(encoding="utf-8"))


class ShowLastFileToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder, self.memory, self.root = make_memory_store()
        clear_last_file()
        self.adapter = FakeOsAdapter()
        self.registry = build_legacy_registry(
            _UnusedActions(),
            os_adapter=self.adapter,
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=self.memory,
        )
        self.context = ToolContext(task_id="file-show")

    def tearDown(self) -> None:
        clear_last_file()
        self.folder.cleanup()

    def test_write_then_show_opens_the_same_file(self) -> None:
        written = self.registry.invoke(
            FILES_WRITE,
            {"path": str(self.root / "hello.cpp"), "text": starter_text(".cpp", "Hello")},
            self.context,
        )
        self.assertTrue(written.ok)
        self.assertIn("The code is:", written.data["reply"])
        self.assertEqual(last_file(), self.root / "hello.cpp")
        with patch("friday.tools.file_tools.get_os_adapter", return_value=self.adapter):
            shown = self.registry.invoke(FILES_READ, {"open": True}, self.context)
        self.assertTrue(shown.ok)
        self.assertIn("hello.cpp", shown.data["reply"])
        self.assertIn(("open_path", str(self.root / "hello.cpp")), self.adapter.calls)

    def test_show_without_a_file_explains_itself(self) -> None:
        result = self.registry.invoke(FILES_READ, {"open": True}, self.context)
        self.assertFalse(result.ok)
        self.assertIn("haven't made a file", result.data["reply"])

    def test_run_compiles_cpp_when_gpp_available(self) -> None:
        if not find_cxx_compiler():
            self.skipTest("g++ not installed")
        path = self.root / "demo.cpp"
        path.write_text(starter_text(".cpp", "hi from friday"), encoding="utf-8")
        from friday.files.recent import remember_file

        remember_file(path)
        result = self.registry.invoke(FILES_RUN, {}, self.context)
        self.assertTrue(result.ok, result.data)
        self.assertIn("hi from friday", result.data["reply"])


class RunSourceTests(unittest.TestCase):
    def test_missing_compiler_message(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        path = root / "demo.cpp"
        path.write_text(starter_text(".cpp", "x"), encoding="utf-8")
        with patch("friday.files.run_source.find_cxx_compiler", return_value=None):
            ok, reply = run_source_file(path, (root,))
        self.assertFalse(ok)
        self.assertIn("compiler", reply.lower())


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
        return ""


if __name__ == "__main__":
    unittest.main()
