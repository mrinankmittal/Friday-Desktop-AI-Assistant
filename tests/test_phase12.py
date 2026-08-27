from __future__ import annotations

import json
import unittest

from friday.browser.fake import FakeBrowser
from friday.observability import clear_events, emit, recent_events
from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName, TaskStatus
from friday.orchestrator.orchestrator import handle_user_request
from friday.os_adapters.fake import FakeOsAdapter
from friday.providers.fake import FakeVision
from friday.tools.builtin import COMMS_WHATSAPP_MESSAGE, REGISTERED_TOOL_NAMES, build_legacy_registry
from friday.tools.registry import InvokePolicy
from friday.tools.types import ToolContext
from tests.helpers import make_memory_store


class FakeActions:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.contact = ("919999999999", "Papa")
        self.chat_reply = "chat reply"

    def play_youtube(self, query: str) -> None:
        self.calls.append(("play_youtube", query))

    def open_app(self, query: str) -> None:
        self.calls.append(("open_app", query))

    def find_contact(self, query: str) -> tuple:
        self.calls.append(("find_contact", query))
        return self.contact

    def whatsapp(self, mobile_no, message, flag, name) -> bool:
        self.calls.append(("whatsapp", mobile_no, message, flag, name))
        return True

    def chatbot(self, query: str) -> str:
        self.calls.append(("chatbot", query))
        return self.chat_reply


class JsonLogTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_events()

    def tearDown(self) -> None:
        clear_events()

    def test_json_has_task_id_and_drops_secrets(self) -> None:
        with self.assertLogs("friday.events", level="INFO") as captured:
            payload = emit(
                "task_start",
                task_id="task-abc",
                intent="open",
                request="open chrome",
                password="super-secret",
                body="secret-body",
                mobile_no="919999999999",
                arguments={"message": "secret-hello"},
            )
        self.assertEqual(payload["task_id"], "task-abc")
        self.assertEqual(payload["event"], "task_start")
        self.assertNotIn("password", payload)
        self.assertNotIn("body", payload)
        self.assertNotIn("mobile_no", payload)
        self.assertNotIn("arguments", payload)
        combined = "\n".join(captured.output)
        self.assertIn("task-abc", combined)
        self.assertNotIn("super-secret", combined)
        self.assertNotIn("secret-body", combined)
        self.assertNotIn("919999999999", combined)
        self.assertNotIn("secret-hello", combined)
        recent = recent_events()
        self.assertEqual(recent[0]["task_id"], "task-abc")

    def test_persists_without_arguments(self) -> None:
        folder, store, _root = make_memory_store()
        try:
            emit(
                "tool_call",
                task_id="task-xyz",
                store=store,
                log=False,
                tool="comms.whatsapp_message",
                status="ok",
                arguments={"mobile_no": "919999999999", "message": "secret-hello"},
            )
            rows = store.list_events()
            self.assertEqual(len(rows), 1)
            dumped = json.dumps(rows[0].to_dict())
            self.assertIn("task-xyz", dumped)
            self.assertNotIn("secret-hello", dumped)
            self.assertNotIn("919999999999", dumped)
            self.assertNotIn("arguments", dumped)
        finally:
            folder.cleanup()


class Phase12OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_events()
        self.actions = FakeActions()
        self.spoken: list[str] = []
        self._memory_folder, self.memory, _root = make_memory_store()

    def tearDown(self) -> None:
        clear_events()
        self._memory_folder.cleanup()

    def _handle(self, query: str):
        return handle_user_request(
            query,
            speak=self.spoken.append,
            listen=lambda: "",
            actions=self.actions,
            os_adapter=FakeOsAdapter(),
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=self.memory,
        )

    def test_open_chrome_emits_start_and_end(self) -> None:
        with self.assertLogs("friday.events", level="INFO") as captured:
            result = self._handle("open chrome")
        self.assertEqual(result.task.intent, IntentName.OPEN)
        self.assertEqual(result.task.status, TaskStatus.SUCCEEDED)
        combined = "\n".join(captured.output)
        self.assertIn("task_start", combined)
        self.assertIn("task_end", combined)
        self.assertIn(result.task.task_id, combined)
        events = self.memory.list_events()
        names = {item.event for item in events}
        self.assertIn("task_start", names)
        self.assertIn("task_end", names)
        self.assertIn("tool_call", names)
        for item in events:
            self.assertEqual(item.task_id, result.task.task_id)
        start = next(item for item in events if item.event == "task_start")
        self.assertEqual(start.intent, "open")
        self.assertIn("apps.open", start.tools)

    def test_event_logs_omit_tool_secrets(self) -> None:
        registry = build_legacy_registry(
            self.actions,
            policy=InvokePolicy(),
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=self.memory,
        )
        registry.invoke(
            COMMS_WHATSAPP_MESSAGE,
            {
                "mobile_no": "919999999999",
                "name": "Papa",
                "message": "secret-hello",
            },
            ToolContext(task_id="phase12", confirmed=True),
        )
        dumped = json.dumps([row.to_dict() for row in self.memory.list_events()])
        self.assertIn("comms.whatsapp_message", dumped)
        self.assertIn("phase12", dumped)
        self.assertNotIn("secret-hello", dumped)
        self.assertNotIn("919999999999", dumped)

    def test_still_43_tools(self) -> None:
        self.assertEqual(len(REGISTERED_TOOL_NAMES), 61)

    def test_does_not_steal_existing_commands(self) -> None:
        self.assertEqual(classify("send message to papa").name, IntentName.WHATSAPP)
        self.assertEqual(classify("call papa").name, IntentName.WHATSAPP)
        self.assertEqual(classify("forget it").name, IntentName.CHAT)
        self.assertEqual(classify("I don't remember").name, IntentName.CHAT)
        self.assertEqual(classify("note that I prefer tea").name, IntentName.MEMORY)
        self.assertEqual(classify("search my documents for goa").name, IntentName.RESEARCH)
        self.assertEqual(classify("remind me later").name, IntentName.CHAT)
        self.assertEqual(classify("open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("show the logs").name, IntentName.CHAT)
        self.assertEqual(classify("show me the logs").name, IntentName.CHAT)


if __name__ == "__main__":
    unittest.main()
