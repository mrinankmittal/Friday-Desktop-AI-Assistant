"""Safe-subset agent gaps: files, os info, tasks, code explain, research, browser."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from friday.browser.fake import FakeBrowser
from friday.files.ops import make_directory
from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName
from friday.os_adapters.fake import FakeOsAdapter
from friday.os_adapters.info import network_info_reply, system_info_reply
from friday.providers.fake import FakeVision
from friday.tools.browser_tools import (
    BROWSER_CLICK,
    BROWSER_FILL,
    BROWSER_TABS,
)
from friday.tools.builtin import build_legacy_registry
from friday.tools.code_tools import CODE_EXPLAIN
from friday.tools.file_tools import FILES_COPY, FILES_MKDIR
from friday.tools.os_tools import OS_INFO, OS_NETWORK
from friday.tools.productivity_tools import TASKS_ADD, TASKS_DONE, TASKS_LIST
from friday.tools.research_tools import RESEARCH_DOCS, RESEARCH_REPORT
from friday.tools.types import ToolContext
from tests.helpers import make_memory_store


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
        return "unused"


class ClassifyAgentGapTests(unittest.TestCase):
    def test_file_copy_and_mkdir(self) -> None:
        copied = classify("copy the file notes.txt to desktop")
        self.assertEqual(copied.name, IntentName.FILE)
        self.assertEqual(copied.extra["action"], "copy")
        folder = classify("create a folder named inbox on the desktop")
        self.assertEqual(folder.extra["action"], "mkdir")
        self.assertEqual(folder.extra["path"], "inbox")

    def test_os_info_and_network(self) -> None:
        self.assertEqual(classify("system info").extra["action"], "info")
        self.assertEqual(classify("what's my ip").extra["action"], "network")
        self.assertEqual(classify("am i online").extra["action"], "network")

    def test_tasks_and_explain(self) -> None:
        added = classify("add a task buy milk")
        self.assertEqual(added.name, IntentName.PRODUCTIVITY)
        self.assertEqual(added.extra["action"], "tasks_add")
        self.assertEqual(classify("list my tasks").extra["action"], "tasks_list")
        done = classify("mark task buy milk done")
        self.assertEqual(done.extra["action"], "tasks_done")
        explained = classify("explain intents.py")
        self.assertEqual(explained.name, IntentName.CODE)
        self.assertEqual(explained.extra["action"], "explain")

    def test_research_and_browser(self) -> None:
        report = classify("write a report on climate")
        self.assertEqual(report.name, IntentName.RESEARCH)
        self.assertEqual(report.extra["action"], "report")
        docs = classify("search my documents for goa")
        self.assertEqual(docs.extra["action"], "docs")
        self.assertEqual(
            classify("click the login button").extra["action"], "click"
        )
        filled = classify("fill email with hello")
        self.assertEqual(filled.extra["action"], "fill")
        self.assertEqual(classify("what tabs are open").extra["action"], "tabs")
        self.assertEqual(
            classify("find Submit on screen").extra["action"], "verify"
        )

    def test_does_not_steal_existing(self) -> None:
        self.assertEqual(classify("write hello in chrome").name, IntentName.OS)
        self.assertEqual(classify("look up python on the web").name, IntentName.BROWSER)
        self.assertEqual(classify("type hello friday").extra["task"], "type")
        self.assertEqual(classify("paste").extra["task"], "paste")


class ToolAgentGapTests(unittest.TestCase):
    def setUp(self) -> None:
        self._memory_folder, self.memory, self.root = make_memory_store()
        self.browser = FakeBrowser()
        (self.root / "sample.py").write_text(
            "def add(a, b):\n    return a + b\n", encoding="utf-8"
        )
        self.registry = build_legacy_registry(
            _UnusedActions(),
            os_adapter=FakeOsAdapter(),
            browser=self.browser,
            vision=FakeVision(),
            memory=self.memory,
        )
        self.context = ToolContext(task_id="agent-gaps")

    def tearDown(self) -> None:
        self._memory_folder.cleanup()

    def test_os_info_speaks(self) -> None:
        reply = system_info_reply()
        self.assertIn("Python", reply)
        result = self.registry.invoke(OS_INFO, {}, self.context)
        self.assertTrue(result.ok)
        self.assertIn("Python", result.data["reply"])
        net = self.registry.invoke(OS_NETWORK, {}, self.context)
        self.assertTrue(net.ok)
        self.assertTrue(network_info_reply())

    def test_files_copy_and_mkdir(self) -> None:
        source = self.root / "notes.txt"
        source.write_text("hello", encoding="utf-8")
        dest_dir = self.root / "backup"
        dest_dir.mkdir()
        copied = self.registry.invoke(
            FILES_COPY,
            {"source": str(source), "destination": str(dest_dir)},
            self.context,
        )
        self.assertTrue(copied.ok)
        self.assertTrue((dest_dir / "notes.txt").is_file())
        made = self.registry.invoke(
            FILES_MKDIR,
            {"path": "inbox", "folder": str(self.root)},
            self.context,
        )
        self.assertTrue(made.ok, made.data)
        self.assertTrue((self.root / "inbox").is_dir())
        # Ops helper stays allowlisted too.
        nested = make_directory(self.root / "inbox" / "nested", (self.root,))
        self.assertTrue(nested.is_dir())

    def test_tasks_crud(self) -> None:
        added = self.registry.invoke(
            TASKS_ADD, {"content": "buy milk"}, self.context
        )
        self.assertTrue(added.ok)
        listed = self.registry.invoke(TASKS_LIST, {}, self.context)
        self.assertIn("buy milk", listed.data["reply"].lower())
        done = self.registry.invoke(
            TASKS_DONE, {"needle": "buy milk"}, self.context
        )
        self.assertTrue(done.ok)
        empty = self.registry.invoke(TASKS_LIST, {}, self.context)
        self.assertIn("don't have any open tasks", empty.data["reply"].lower())

    def test_code_explain_stubbed_llm(self) -> None:
        with patch(
            "friday.providers.llm.complete_chat",
            return_value="It adds two numbers.",
        ):
            result = self.registry.invoke(
                CODE_EXPLAIN, {"path": "sample.py"}, self.context
            )
        self.assertTrue(result.ok)
        self.assertIn("adds", result.data["reply"].lower())

    def test_research_report_with_fake_browser(self) -> None:
        with patch(
            "friday.research.complete_chat",
            side_effect=RuntimeError("offline"),
        ):
            result = self.registry.invoke(
                RESEARCH_REPORT, {"query": "python"}, self.context
            )
        self.assertTrue(result.ok)
        self.assertIn("python", result.data["reply"].lower())
        self.assertTrue(
            any(call[0] == "search" for call in self.browser.calls)
        )

    def test_research_docs(self) -> None:
        self.memory.remember("goa trip planned for december", kind="note")
        with patch(
            "friday.research.complete_chat",
            side_effect=RuntimeError("offline"),
        ):
            result = self.registry.invoke(
                RESEARCH_DOCS, {"query": "goa"}, self.context
            )
        self.assertTrue(result.ok)
        self.assertIn("goa", result.data["reply"].lower())

    def test_browser_click_fill_tabs_download(self) -> None:
        clicked = self.registry.invoke(
            BROWSER_CLICK, {"target": "login"}, self.context
        )
        self.assertTrue(clicked.ok)
        filled = self.registry.invoke(
            BROWSER_FILL,
            {"target": "email", "value": "a@b.com"},
            self.context,
        )
        self.assertTrue(filled.ok)
        tabs = self.registry.invoke(BROWSER_TABS, {}, self.context)
        self.assertTrue(tabs.ok)
        downloads = self.root / "Downloads"
        downloads.mkdir(exist_ok=True)
        dl = self.browser.download("https://example.com/a.bin", str(downloads))
        self.assertTrue(dl.ok)
        self.assertTrue(Path(dl.path).is_file())
        self.assertIn(
            ("download", "https://example.com/a.bin", str(downloads)),
            self.browser.calls,
        )


if __name__ == "__main__":
    unittest.main()
