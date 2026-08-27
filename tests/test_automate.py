"""Desktop automation: allowlisted hotkeys and typing, without stealing other tools."""

from __future__ import annotations

import unittest

from friday.browser.fake import FakeBrowser
from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName
from friday.os_adapters.app_control import clear_last_type_app, parse_in_app_command
from friday.os_adapters.fake import FakeOsAdapter
from friday.os_adapters.hotkeys import parse_hotkey
from friday.os_adapters.types import WindowInfo
from friday.providers.fake import FakeVision
from friday.tools.builtin import build_legacy_registry
from friday.tools.os_tools import OS_AUTOMATE
from friday.tools.types import ToolContext
from tests.helpers import make_memory_store


class ClassifyAutomateTests(unittest.TestCase):
    def test_named_hotkeys(self) -> None:
        paste = classify("paste")
        self.assertEqual(paste.name, IntentName.OS)
        self.assertEqual(paste.extra["action"], "automate")
        self.assertEqual(paste.extra["task"], "paste")
        self.assertEqual(classify("copy that").extra["task"], "copy")
        self.assertEqual(classify("show desktop").extra["task"], "show_desktop")
        self.assertEqual(classify("undo").extra["task"], "undo")

    def test_type_and_press(self) -> None:
        typed = classify("type hello friday")
        self.assertEqual(typed.extra["task"], "type")
        self.assertEqual(typed.extra["text"], "hello friday")
        pressed = classify("press ctrl s")
        self.assertEqual(pressed.extra["task"], "hotkey")
        self.assertEqual(pressed.extra["keys"], "ctrl+s")

    def test_does_not_steal_other_commands(self) -> None:
        self.assertEqual(classify("copy to clipboard hello friday").extra["action"], "clipboard_set")
        self.assertEqual(classify("switch to chrome").extra["action"], "focus")
        self.assertEqual(
            classify("write hello friday to file phase9-note.txt").extra["action"],
            "write",
        )
        self.assertEqual(classify("open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("play music").name, IntentName.MEDIA)
        self.assertEqual(classify("find a file downloaded yesterday").name, IntentName.FILE)
        self.assertEqual(classify("play despacito on youtube").name, IntentName.YOUTUBE)
        self.assertEqual(classify("search python on google").name, IntentName.BROWSER)
        self.assertEqual(classify("send message to papa").name, IntentName.WHATSAPP)
        self.assertEqual(classify("open spotify").name, IntentName.OPEN)


class ClassifyInAppTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_last_type_app()

    def tearDown(self) -> None:
        clear_last_type_app()

    def test_spotify_search_and_whatsapp_chat(self) -> None:
        song = classify("play despacito on spotify")
        self.assertEqual(song.name, IntentName.OS)
        self.assertEqual(song.extra["app"], "spotify")
        self.assertEqual(song.extra["task"], "search")
        self.assertEqual(song.extra["text"], "despacito")
        chat = classify("search mummy on whatsapp")
        self.assertEqual(chat.extra["app"], "whatsapp")
        self.assertEqual(chat.extra["task"], "search")
        self.assertEqual(chat.extra["text"], "mummy")
        self.assertEqual(classify("whatsapp mummy").extra["text"], "mummy")

    def test_any_app_type(self) -> None:
        intent = classify("in notepad type hello friday")
        self.assertEqual(intent.extra["app"], "notepad")
        self.assertEqual(intent.extra["task"], "type")
        self.assertEqual(intent.extra["text"], "hello friday")

    def test_write_in_any_app(self) -> None:
        for phrase, app, expected in (
            ("open notepad and write how are you doing", "notepad", "how are you doing"),
            ("write how are you doing in notepad", "notepad", "how are you doing"),
            ("open word and write hello", "word", "hello"),
            ("write hello in chrome", "chrome", "hello"),
            ("in whatsapp write hi mummy", "whatsapp", "hi mummy"),
            ("open notepad and in the notepad right how are you", "notepad", "how are you"),
        ):
            with self.subTest(phrase=phrase):
                intent = classify(phrase)
                self.assertEqual(intent.name, IntentName.OS, phrase)
                self.assertEqual(intent.extra["app"], app, phrase)
                self.assertEqual(intent.extra["task"], "type", phrase)
                self.assertEqual(intent.extra["text"], expected, phrase)

    def test_bare_write_goes_to_the_focused_app(self) -> None:
        intent = classify("write how are you doing")
        self.assertEqual(intent.name, IntentName.OS)
        self.assertEqual(intent.extra["task"], "type")
        self.assertEqual(intent.extra["text"], "how are you doing")
        self.assertNotIn("app", intent.extra)

    def test_bare_write_follows_the_last_app(self) -> None:
        from friday.os_adapters.app_control import remember_type_app

        remember_type_app("word")
        intent = classify("write how are you doing")
        self.assertEqual(intent.extra["app"], "word")
        self.assertEqual(intent.extra["text"], "how are you doing")

    def test_web_surfaces_are_not_apps(self) -> None:
        self.assertIsNone(parse_in_app_command("search python on google"))
        self.assertIsNone(parse_in_app_command("play despacito on youtube"))


class ParseHotkeyTests(unittest.TestCase):
    def test_spoken_and_plus_forms(self) -> None:
        self.assertEqual(parse_hotkey("control s"), ("ctrl", "s"))
        self.assertEqual(parse_hotkey("ctrl+alt+delete"), ("ctrl", "alt", "delete"))
        self.assertEqual(parse_hotkey("windows d"), ("win", "d"))
        self.assertIsNone(parse_hotkey("launch the missiles"))


class AutomateToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = FakeOsAdapter()
        self.folder, self.memory, _root = make_memory_store()
        self.registry = build_legacy_registry(
            _UnusedActions(),
            os_adapter=self.adapter,
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=self.memory,
        )
        self.context = ToolContext(task_id="auto-test")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_paste_presses_ctrl_v(self) -> None:
        result = self.registry.invoke(OS_AUTOMATE, {"task": "paste"}, self.context)
        self.assertTrue(result.ok)
        self.assertIn(("press_hotkey", ("ctrl", "v")), self.adapter.calls)
        self.assertEqual(result.data["reply"], "Pasting.")

    def test_type_goes_to_the_adapter(self) -> None:
        result = self.registry.invoke(
            OS_AUTOMATE, {"task": "type", "text": "hello"}, self.context
        )
        self.assertTrue(result.ok)
        self.assertIn(("set_clipboard", "hello"), self.adapter.calls)
        self.assertIn(("press_hotkey", ("ctrl", "v")), self.adapter.calls)

    def test_spotify_search_opens_then_types(self) -> None:
        from unittest.mock import patch

        from friday.tools.os_tools import register_os_tools
        from friday.tools.registry import ToolRegistry

        registry = ToolRegistry()
        register_os_tools(registry, self.adapter, sleeper=lambda _s: None)
        with patch(
            "friday.os_adapters.app_control.lookup_open_target",
            return_value=("path", "shell:AppsFolder\\Spotify"),
        ):
            result = registry.invoke(
                OS_AUTOMATE,
                {"task": "search", "app": "spotify", "text": "despacito"},
                self.context,
            )
        self.assertTrue(result.ok)
        self.assertIn(("open_path", "shell:AppsFolder\\Spotify"), self.adapter.calls)
        self.assertIn(("press_hotkey", ("ctrl", "l")), self.adapter.calls)
        self.assertIn(("set_clipboard", "despacito"), self.adapter.calls)
        self.assertIn(("press_hotkey", ("ctrl", "v")), self.adapter.calls)
        self.assertIn(("press_hotkey", ("enter",)), self.adapter.calls)
        self.assertIn("spotify", result.data["reply"].lower())

    def test_whatsapp_uses_existing_window(self) -> None:
        from friday.tools.os_tools import register_os_tools
        from friday.tools.registry import ToolRegistry

        self.adapter.windows.append(WindowInfo(handle=3, title="WhatsApp", pid=200))
        registry = ToolRegistry()
        register_os_tools(registry, self.adapter, sleeper=lambda _s: None)
        result = registry.invoke(
            OS_AUTOMATE,
            {"task": "search", "app": "whatsapp", "text": "mummy"},
            self.context,
        )
        self.assertTrue(result.ok)
        opened = [call for call in self.adapter.calls if call[0] == "open_path"]
        self.assertEqual(opened, [])
        self.assertIn(("focus_window", "whatsapp"), self.adapter.calls)
        self.assertIn(("press_hotkey", ("ctrl", "f")), self.adapter.calls)
        self.assertIn(("set_clipboard", "mummy"), self.adapter.calls)
        self.assertIn(("press_hotkey", ("ctrl", "v")), self.adapter.calls)

    def test_write_pastes_into_any_named_app(self) -> None:
        from friday.tools.os_tools import register_os_tools
        from friday.tools.registry import ToolRegistry

        self.adapter.windows.append(WindowInfo(handle=4, title="Document - Word", pid=300))
        registry = ToolRegistry()
        register_os_tools(registry, self.adapter, sleeper=lambda _s: None)
        result = registry.invoke(
            OS_AUTOMATE,
            {"task": "type", "app": "word", "text": "how are you doing"},
            self.context,
        )
        self.assertTrue(result.ok)
        self.assertIn(("set_clipboard", "how are you doing"), self.adapter.calls)
        self.assertIn(("press_hotkey", ("ctrl", "v")), self.adapter.calls)
        self.assertIn(("focus_window", "word"), self.adapter.calls)


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
