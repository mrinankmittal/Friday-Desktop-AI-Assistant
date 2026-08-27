from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from friday.browser.fake import FakeBrowser
from friday.os_adapters.fake import FakeOsAdapter
from friday.orchestrator.models import IntentName, TaskStatus
from friday.orchestrator.orchestrator import handle_user_request
from friday.providers.fake import FakeVision
from tests.helpers import make_memory_store


class FakeActions:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.contact = ("919999999999", "Kabir")
        self.chat_reply = "hello from fake chatbot"

    def play_youtube(self, query: str) -> None:
        self.calls.append(("play_youtube", (query,), {}))

    def open_app(self, query: str) -> None:
        self.calls.append(("open_app", (query,), {}))

    def find_contact(self, query: str) -> tuple:
        self.calls.append(("find_contact", (query,), {}))
        return self.contact

    def whatsapp(self, mobile_no, message, flag, name) -> bool:
        self.calls.append(
            ("whatsapp", (), {
                "mobile_no": mobile_no,
                "message": message,
                "flag": flag,
                "name": name,
            }),
        )
        return True

    def chatbot(self, query: str) -> str:
        self.calls.append(("chatbot", (query,), {}))
        return self.chat_reply


class OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actions = FakeActions()
        self.spoken: list[str] = []
        self.listen_replies: list[str] = ["hi kabir"]
        self._memory_folder, self.memory, _root = make_memory_store()
        self.memory_root = _root
        self.env = patch.dict(
            os.environ,
            {
                "FRIDAY_REQUIRE_CONFIRM_SEND": "false",
                "FRIDAY_WHATSAPP_CONFIRM": "false",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self._memory_folder.cleanup()

    def _handle(self, query: str):
        return handle_user_request(
            query,
            speak=self.spoken.append,
            listen=lambda: self.listen_replies.pop(0) if self.listen_replies else "",
            actions=self.actions,
            os_adapter=FakeOsAdapter(),
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=self.memory,
        )

    def test_youtube_does_not_hit_chatbot(self) -> None:
        result = self._handle("play despacito on youtube")
        self.assertTrue(result.continue_listening)
        self.assertIsNone(result.assistant_reply)
        self.assertEqual(self.actions.calls[0][0], "play_youtube")
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))
        self.assertEqual(result.task.intent, IntentName.YOUTUBE)
        self.assertEqual(result.task.status, TaskStatus.SUCCEEDED)
        self.assertEqual(result.task.steps[0].tool, "media.youtube_play")
        self.assertIsNotNone(result.task.steps[0].input_hash)

    def test_open_delegates_to_open_app(self) -> None:
        result = self._handle("open chrome")
        self.assertEqual(self.actions.calls[0][0], "open_app")
        self.assertEqual(result.task.intent, IntentName.OPEN)

    def test_due_reminder_is_spoken(self) -> None:
        past = (datetime.now().astimezone() - timedelta(minutes=2)).replace(
            microsecond=0
        ).isoformat()
        self.memory.add_reminder("stretch", due_at=past)
        self._handle("open chrome")
        self.assertTrue(any("stretch" in item.lower() for item in self.spoken))
        self.assertEqual(self.memory.list_reminders(), [])

    def test_whatsapp_message_asks_then_sends(self) -> None:
        result = self._handle("send message to kabir")
        self.assertEqual(self.spoken[0], "What message should I send?")
        whatsapp_call = next(call for call in self.actions.calls if call[0] == "whatsapp")
        self.assertEqual(whatsapp_call[2]["flag"], "message")
        self.assertEqual(whatsapp_call[2]["message"], "hi kabir")
        self.assertEqual(whatsapp_call[2]["name"], "Kabir")
        self.assertTrue(result.continue_listening)

    def test_whatsapp_inline_message_skips_prompt(self) -> None:
        result = self._handle("send message to kabir i will be late")
        self.assertEqual(self.spoken, [])
        whatsapp_call = next(call for call in self.actions.calls if call[0] == "whatsapp")
        self.assertEqual(whatsapp_call[2]["message"], "i will be late")
        self.assertTrue(result.continue_listening)

    def test_whatsapp_message_to_phrase_is_the_same_send(self) -> None:
        self._handle("message to kabir hello from friday")
        whatsapp_call = next(call for call in self.actions.calls if call[0] == "whatsapp")
        self.assertEqual(whatsapp_call[2]["flag"], "message")
        self.assertEqual(whatsapp_call[2]["message"], "hello from friday")

    def test_whatsapp_call_skips_message_prompt(self) -> None:
        self._handle("phone call to kabir")
        self.assertEqual(self.spoken, [])
        whatsapp_call = next(call for call in self.actions.calls if call[0] == "whatsapp")
        self.assertEqual(whatsapp_call[2]["flag"], "call")
        self.assertEqual(whatsapp_call[2]["message"], "")

    def test_call_to_phrase_is_the_same_phone_call(self) -> None:
        self._handle("call to kabir")
        whatsapp_call = next(call for call in self.actions.calls if call[0] == "whatsapp")
        self.assertEqual(whatsapp_call[2]["flag"], "call")

    def test_whatsapp_video_call(self) -> None:
        self._handle("video call to kabir")
        whatsapp_call = next(call for call in self.actions.calls if call[0] == "whatsapp")
        self.assertEqual(whatsapp_call[2]["flag"], "video")

    def test_whatsapp_missing_contact_stops_before_send(self) -> None:
        self.actions.contact = (0, 0)
        result = self._handle("send message to nobody")
        self.assertTrue(result.continue_listening)
        self.assertFalse(any(name == "whatsapp" for name, *_ in self.actions.calls))
        self.assertEqual(result.task.status, TaskStatus.FAILED)
        self.assertEqual(result.task.steps[0].tool, "contacts.lookup")
        self.assertEqual(result.task.steps[1].status, TaskStatus.PLANNED)

    def test_whatsapp_empty_listen_cancels(self) -> None:
        self.listen_replies = [""]
        result = self._handle("send message to kabir")
        self.assertIn("I couldn't hear the message, so I cancelled it.", self.spoken)
        self.assertFalse(any(name == "whatsapp" for name, *_ in self.actions.calls))
        self.assertEqual(result.task.status, TaskStatus.CANCELLED)
        self.assertEqual(result.task.steps[1].status, TaskStatus.CANCELLED)

    def test_chat_returns_reply_for_ui(self) -> None:
        result = self._handle("what is python")
        self.assertEqual(result.assistant_reply, "hello from fake chatbot")
        self.assertEqual(self.actions.calls[0][0], "chatbot")

    def test_stop_ends_listening(self) -> None:
        result = self._handle("stop listening")
        self.assertFalse(result.continue_listening)
        self.assertEqual(self.spoken, ["Stopping voice control"])
        self.assertIsNone(result.assistant_reply)

    def test_screenshot_uses_os_tool(self) -> None:
        result = self._handle("take a screenshot")
        self.assertEqual(result.task.intent, IntentName.OS)
        self.assertEqual(result.task.steps[0].tool, "os.screenshot")
        self.assertIn("Screenshot saved", result.assistant_reply)
        self.assertIn("Opening it", result.assistant_reply)

    def test_list_windows_does_not_hit_chatbot(self) -> None:
        result = self._handle("list windows")
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))
        self.assertIn("Chrome", result.assistant_reply)

    def test_list_of_windows_does_not_hit_chatbot(self) -> None:
        result = self._handle("list of windows")
        self.assertEqual(result.task.intent, IntentName.OS)
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))
        self.assertIn("Chrome", result.assistant_reply)

    def test_spoken_process_list_does_not_hit_chatbot(self) -> None:
        result = self._handle("now tell me regarding the list of processes")
        self.assertEqual(result.task.intent, IntentName.OS)
        self.assertEqual(result.task.steps[0].tool, "os.processes.list")
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))

    def test_clipboard_set_and_get(self) -> None:
        adapter = FakeOsAdapter()
        result = handle_user_request(
            "copy to clipboard hello friday",
            speak=self.spoken.append,
            listen=lambda: "",
            actions=self.actions,
            os_adapter=adapter,
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=self.memory,
        )
        self.assertEqual(adapter.clipboard, "hello friday")
        self.assertEqual(result.assistant_reply, "Copied to the clipboard.")

    def test_web_search_does_not_hit_chatbot(self) -> None:
        result = self._handle("search the web for python")
        self.assertEqual(result.task.intent, IntentName.BROWSER)
        self.assertEqual(result.task.steps[0].tool, "browser.search")
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))
        self.assertIn("Python.org", result.assistant_reply)
        self.assertEqual(result.task.status, TaskStatus.SUCCEEDED)

    def test_go_to_url_uses_browser_open(self) -> None:
        result = self._handle("go to example.com")
        self.assertEqual(result.task.steps[0].tool, "browser.open")
        self.assertIn("Opened", result.assistant_reply)

    def test_describe_screen_does_not_hit_chatbot(self) -> None:
        result = self._handle("what's on my screen")
        self.assertEqual(result.task.intent, IntentName.VISION)
        self.assertEqual(result.task.steps[0].tool, "vision.describe_screen")
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))
        self.assertIn("Chrome", result.assistant_reply)
        self.assertIn("Python.org", result.assistant_reply)

    def test_screenshot_is_still_os_not_vision(self) -> None:
        result = self._handle("take a screenshot")
        self.assertEqual(result.task.intent, IntentName.OS)
        self.assertEqual(result.task.steps[0].tool, "os.screenshot")

    def test_show_screenshot_opens_last_file(self) -> None:
        adapter = FakeOsAdapter()

        def handle(query: str):
            return handle_user_request(
                query,
                speak=self.spoken.append,
                listen=lambda: "",
                actions=self.actions,
                os_adapter=adapter,
                browser=FakeBrowser(),
                vision=FakeVision(),
                memory=self.memory,
            )

        missing = handle("show me the screenshot")
        self.assertIn("don't have a screenshot", missing.assistant_reply)

        handle("take a screenshot")
        shown = handle("show me the screenshot")
        self.assertEqual(shown.task.intent, IntentName.OS)
        self.assertEqual(shown.task.steps[0].tool, "os.screenshot")
        self.assertIn("Opening the screenshot", shown.assistant_reply)
        self.assertIn(("open_path", "friday-test-screenshot.png"), adapter.calls)

    def test_take_and_show_is_screenshot_not_chat(self) -> None:
        result = self._handle("take a screenshot and show me the screenshot")
        self.assertEqual(result.task.intent, IntentName.OS)
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))
        self.assertIn("Opening it", result.assistant_reply)

    def test_remember_does_not_hit_chatbot(self) -> None:
        result = self._handle("remember that my name is kabir")
        self.assertEqual(result.task.intent, IntentName.MEMORY)
        self.assertEqual(result.task.steps[0].tool, "memory.remember")
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))
        self.assertIn("remember", result.assistant_reply.lower())

        listed = self._handle("what do you remember")
        self.assertIn("kabir", listed.assistant_reply.lower())

        known = self._handle("do you know my name")
        self.assertEqual(known.task.intent, IntentName.MEMORY)
        self.assertEqual(known.task.steps[0].tool, "rag.search")
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))
        self.assertIn("kabir", known.assistant_reply.lower())

    def test_natural_name_phrase_is_remembered(self) -> None:
        saved = self._handle("my name is Raunak Mittal remember it")
        self.assertEqual(saved.task.intent, IntentName.MEMORY)
        self.assertEqual(saved.task.steps[0].tool, "memory.remember")
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))
        known = self._handle("do you know my name")
        self.assertIn("raunak", known.assistant_reply.lower())
        self.assertNotIn("chatbot", known.assistant_reply.lower())

    def test_other_peoples_names_are_not_confused_with_own_name(self) -> None:
        self._handle("remember that my name is Mrinank Mittal")
        missing = self._handle("do you know my friend's name")
        self.assertEqual(missing.task.intent, IntentName.MEMORY)
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))
        self.assertIn("friend", missing.assistant_reply.lower())
        self.assertNotIn("mrinank", missing.assistant_reply.lower())

        saved = self._handle("my friend's name is Riya")
        self.assertEqual(saved.task.intent, IntentName.MEMORY)
        self.assertEqual(saved.task.steps[0].tool, "memory.remember")

        known = self._handle("do you know my friend's name")
        self.assertIn("riya", known.assistant_reply.lower())
        self.assertNotIn("mrinank", known.assistant_reply.lower())

        mom = self._handle("my mom's name is Seema")
        self.assertEqual(mom.task.intent, IntentName.MEMORY)
        asked_mom = self._handle("do you know mummy's name")
        self.assertIn("seema", asked_mom.assistant_reply.lower())
        self.assertNotIn("mrinank", asked_mom.assistant_reply.lower())
        self.assertNotIn("riya", asked_mom.assistant_reply.lower())

        own = self._handle("do you know my name")
        self.assertIn("mrinank", own.assistant_reply.lower())
        self.assertNotIn("riya", own.assistant_reply.lower())
        self.assertNotIn("seema", own.assistant_reply.lower())

    def test_name_question_without_memory_skips_chatbot(self) -> None:
        result = self._handle("do you know my name")
        self.assertEqual(result.task.intent, IntentName.MEMORY)
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))
        self.assertIn("name", result.assistant_reply.lower())

    def test_chat_uses_local_notes_when_chatbot_fails(self) -> None:
        self._handle("remember that I like cricket")
        self.actions.chat_reply = "Sorry, I could not reach the chatbot right now."
        result = self._handle("what is cricket")
        self.assertEqual(result.task.intent, IntentName.CHAT)
        self.assertTrue(any(name == "chatbot" for name, *_ in self.actions.calls))
        self.assertIn("cricket", result.assistant_reply.lower())
        self.assertNotEqual(
            result.assistant_reply,
            "Sorry, I could not reach the chatbot right now.",
        )

    def test_chat_offline_without_notes_is_not_dead_end(self) -> None:
        self.actions.chat_reply = "Sorry, I could not reach the chatbot right now."
        result = self._handle("what is python")
        self.assertEqual(result.task.intent, IntentName.CHAT)
        self.assertIn("offline", result.assistant_reply.lower())
        self.assertNotEqual(
            result.assistant_reply,
            "Sorry, I could not reach the chatbot right now.",
        )

    def test_spoken_download_search_skips_chatbot(self) -> None:
        result = self._handle("the downloads and search the files")
        self.assertEqual(result.task.intent, IntentName.FILE)
        self.assertEqual(result.task.steps[0].tool, "files.search")
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))

    def test_ingest_then_search_notes(self) -> None:
        path = self.memory_root / "vacation.txt"
        path.write_text("Vacation plans: go to Goa in December.", encoding="utf-8")
        ingested = self._handle(f"ingest {path}")
        self.assertIn("vacation.txt", ingested.assistant_reply.lower())
        found = self._handle("search my documents for goa")
        self.assertIn("goa", found.assistant_reply.lower())
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))

    def test_file_and_note_commands_skip_chatbot(self) -> None:
        path = self.memory_root / "phase9-invoice.txt"
        path.write_text("paid in full", encoding="utf-8")
        found = self._handle("find file phase9-invoice.txt")
        self.assertEqual(found.task.intent, IntentName.FILE)
        self.assertEqual(found.task.steps[0].tool, "files.search")
        self.assertIn("phase9-invoice", found.assistant_reply.lower())
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))

        read = self._handle("read file phase9-invoice.txt")
        self.assertIn("paid", read.assistant_reply.lower())

        note = self._handle("add a note pack charger")
        self.assertEqual(note.task.intent, IntentName.PRODUCTIVITY)
        self.assertIn("pack charger", note.assistant_reply.lower())
        listed = self._handle("list my notes")
        self.assertIn("pack charger", listed.assistant_reply.lower())

        reminder = self._handle("remind me to stretch")
        self.assertIn("stretch", reminder.assistant_reply.lower())
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))

    def test_code_read_in_workspace(self) -> None:
        (self.memory_root / "sample.py").write_text("print('hi')\n", encoding="utf-8")
        result = self._handle("read sample.py in this repo")
        self.assertEqual(result.task.intent, IntentName.CODE)
        self.assertIn("print", result.assistant_reply.lower())
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))


if __name__ == "__main__":
    unittest.main()
