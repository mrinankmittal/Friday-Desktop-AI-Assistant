from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from friday.browser.fake import FakeBrowser
from friday.os_adapters.apps import execute_open, lookup_open_target
from friday.os_adapters.fake import FakeOsAdapter
from friday.providers.fake import FakeVision
from friday.os_adapters.types import ProcessInfo, WindowInfo
from friday.tools.builtin import build_legacy_registry
from friday.tools.os_tools import (
    OS_CLIPBOARD_GET,
    OS_CLIPBOARD_SET,
    OS_PROCESSES_LIST,
    OS_SCREENSHOT,
    OS_WINDOWS_FOCUS,
    OS_WINDOWS_LIST,
    format_processes,
    format_windows,
)
from friday.tools.types import ToolContext
from tests.helpers import make_memory_store


class LookupOpenTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self._folder.name) / "friday.db"
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "CREATE TABLE sys_command (name TEXT, path TEXT)"
            )
            connection.execute(
                "CREATE TABLE web_command (name TEXT, url TEXT)"
            )
            connection.execute(
                "INSERT INTO sys_command VALUES (?, ?)",
                ("notepad", r"C:\Windows\notepad.exe"),
            )
            connection.execute(
                "INSERT INTO web_command VALUES (?, ?)",
                ("youtube", "https://youtube.com"),
            )
            connection.commit()

    def tearDown(self) -> None:
        self._folder.cleanup()

    def test_sys_command_path(self) -> None:
        kind, target = lookup_open_target("notepad", self.db_path)
        self.assertEqual(kind, "path")
        self.assertEqual(target, r"C:\Windows\notepad.exe")

    def test_web_command_url(self) -> None:
        kind, target = lookup_open_target("youtube", self.db_path)
        self.assertEqual(kind, "url")
        self.assertEqual(target, "https://youtube.com")

    def test_unknown_falls_back_to_name(self) -> None:
        kind, target = lookup_open_target("calc", self.db_path)
        self.assertEqual(kind, "name")
        self.assertEqual(target, "calc")

    def test_task_aliases_do_not_use_the_spoken_leftover(self) -> None:
        kind, target = lookup_open_target("the task", self.db_path)
        self.assertIn(kind, {"path", "name"})
        self.assertTrue(target)
        self.assertNotEqual(target.lower(), "the task")
        if kind == "path":
            self.assertTrue(target.lower().endswith("taskmgr.exe"))
        else:
            self.assertEqual(target, "taskmgr")

    def test_incomplete_open_target_is_empty(self) -> None:
        kind, target = lookup_open_target("the", self.db_path)
        self.assertEqual(kind, "name")
        self.assertEqual(target, "")

    def test_calendar_prefers_catalog_calendar(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT INTO sys_command VALUES (?, ?)",
                (
                    "Calendar",
                    r"shell:AppsFolder\microsoft.windowscommunicationsapps_8wekyb3d8bbwe!microsoft.windowslive.calendar",
                ),
            )
            connection.commit()
        kind, target = lookup_open_target("the calendar", self.db_path)
        self.assertEqual(kind, "path")
        self.assertIn("windowslive.calendar", target.lower())

    def test_calendar_prefers_one_calendar(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT INTO sys_command VALUES (?, ?)",
                (
                    "One Calendar",
                    r"shell:AppsFolder\64885BlueEdge.OneCalendar_8kea50m9krsh2!App",
                ),
            )
            connection.execute(
                "INSERT INTO sys_command VALUES (?, ?)",
                (
                    "Outlook",
                    r"shell:AppsFolder\Microsoft.OutlookForWindows_8wekyb3d8bbwe!Microsoft.OutlookforWindows",
                ),
            )
            connection.commit()
        kind, target = lookup_open_target("calendar", self.db_path)
        self.assertEqual(kind, "path")
        self.assertIn("onecalendar", target.lower())
        kind, target = lookup_open_target("one calendar", self.db_path)
        self.assertIn("onecalendar", target.lower())

    def test_outlook_calendar_phrase_opens_outlook(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT INTO sys_command VALUES (?, ?)",
                (
                    "Outlook",
                    r"shell:AppsFolder\Microsoft.OutlookForWindows_8wekyb3d8bbwe!Microsoft.OutlookforWindows",
                ),
            )
            connection.commit()
        kind, target = lookup_open_target("outlook calendar", self.db_path)
        self.assertEqual(kind, "path")
        self.assertIn("outlook", target.lower())

    def test_calendar_defaults_to_one_calendar_without_catalog(self) -> None:
        kind, target = lookup_open_target("calendar", self.db_path)
        self.assertEqual(kind, "path")
        self.assertTrue(target.startswith("shell:AppsFolder\\"))
        self.assertIn("onecalendar", target.lower())

    def test_execute_open_uses_adapter(self) -> None:
        adapter = FakeOsAdapter()
        self.assertTrue(execute_open("path", r"C:\Windows\notepad.exe", adapter))
        self.assertEqual(adapter.calls[0], ("open_path", r"C:\Windows\notepad.exe"))
        self.assertTrue(execute_open("url", "https://example.com", adapter))
        self.assertEqual(adapter.calls[1], ("open_url", "https://example.com"))


class OsToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = FakeOsAdapter()
        self._memory_folder, memory, _root = make_memory_store()
        self.registry = build_legacy_registry(
            actions=_UnusedActions(),
            os_adapter=self.adapter,
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=memory,
        )
        self.context = ToolContext(task_id="os-test")

    def tearDown(self) -> None:
        self._memory_folder.cleanup()

    def test_screenshot_and_windows(self) -> None:
        shot = self.registry.invoke(OS_SCREENSHOT, {}, self.context)
        self.assertTrue(shot.ok)
        self.assertIn("friday-test-screenshot.png", shot.data["path"])
        self.assertIn(("open_path", "friday-test-screenshot.png"), self.adapter.calls)
        listed = self.registry.invoke(OS_WINDOWS_LIST, {}, self.context)
        self.assertIn("Google Chrome", listed.data["reply"])

    def test_show_latest_screenshot_without_capture(self) -> None:
        missing = self.registry.invoke(
            OS_SCREENSHOT, {"capture": False, "open": True}, self.context
        )
        self.assertFalse(missing.ok)
        self.registry.invoke(OS_SCREENSHOT, {}, self.context)
        shown = self.registry.invoke(
            OS_SCREENSHOT, {"capture": False, "open": True}, self.context
        )
        self.assertTrue(shown.ok)
        self.assertIn("Opening the screenshot", shown.data["reply"])

    def test_focus_and_processes(self) -> None:
        focused = self.registry.invoke(
            OS_WINDOWS_FOCUS, {"title": "chrome"}, self.context
        )
        self.assertTrue(focused.ok)
        processes = self.registry.invoke(OS_PROCESSES_LIST, {}, self.context)
        self.assertIn("chrome.exe", processes.data["reply"])

    def test_clipboard_round_trip_redacts_text_in_logs(self) -> None:
        with self.assertLogs("friday.tools", level="INFO") as captured:
            self.registry.invoke(
                OS_CLIPBOARD_SET, {"text": "secret-clipboard"}, self.context
            )
            read = self.registry.invoke(OS_CLIPBOARD_GET, {}, self.context)
        self.assertEqual(self.adapter.clipboard, "secret-clipboard")
        self.assertEqual(read.data["reply"], "secret-clipboard")
        combined = "\n".join(captured.output)
        self.assertNotIn("secret-clipboard", combined)

    def test_format_helpers(self) -> None:
        self.assertEqual(format_windows([]), "I don't see any open windows.")
        self.assertIn(
            "Notepad",
            format_windows([WindowInfo(1, "Notepad")]),
        )
        self.assertIn(
            "chrome.exe",
            format_processes([ProcessInfo(1, "chrome.exe")]),
        )


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
