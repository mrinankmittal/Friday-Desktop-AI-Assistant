from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from friday.browser.fake import FakeBrowser
from friday.integrations.pending import clear_pending, get_pending
from friday.integrations.store import IntegrationStore
from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName, TaskStatus
from friday.orchestrator.orchestrator import handle_user_request
from friday.os_adapters.fake import FakeOsAdapter
from friday.providers.fake import FakeVision
from friday.security.allowlist import list_allow_paths
from friday.security.secrets import SecretBox, unwrap_secrets, wrap_secrets
from friday.security.settings import require_confirm_send
from friday.tools.builtin import COMMS_WHATSAPP_MESSAGE, build_legacy_registry
from friday.tools.registry import InvokePolicy
from friday.tools.types import ToolContext, ToolPermissionError
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


def _wrap(data: bytes) -> bytes:
    return b"WRAP" + data


def _unwrap(data: bytes) -> bytes:
    if data.startswith(b"WRAP"):
        return data[4:]
    return data


class ConfirmPolicyTests(unittest.TestCase):
    def test_default_is_on(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FRIDAY_REQUIRE_CONFIRM_SEND", None)
            self.assertTrue(require_confirm_send())
            self.assertTrue(InvokePolicy.from_env().require_confirm_for_high_risk)

    def test_opt_out(self) -> None:
        with patch.dict(os.environ, {"FRIDAY_REQUIRE_CONFIRM_SEND": "false"}):
            self.assertFalse(require_confirm_send())
            self.assertFalse(InvokePolicy.from_env().require_confirm_for_high_risk)

    def test_whatsapp_confirm_override(self) -> None:
        from friday.security.settings import require_confirm_whatsapp

        with patch.dict(
            os.environ,
            {
                "FRIDAY_REQUIRE_CONFIRM_SEND": "true",
                "FRIDAY_WHATSAPP_CONFIRM": "false",
            },
        ):
            self.assertTrue(require_confirm_send())
            self.assertFalse(require_confirm_whatsapp())
        with patch.dict(
            os.environ,
            {
                "FRIDAY_REQUIRE_CONFIRM_SEND": "false",
                "FRIDAY_WHATSAPP_CONFIRM": "true",
            },
        ):
            self.assertTrue(require_confirm_whatsapp())


class SecretWrapTests(unittest.TestCase):
    def test_roundtrip_and_hides_plaintext(self) -> None:
        payload = {"gmail": {"access_token": "super-secret-token"}}
        envelope = wrap_secrets(payload, protect=_wrap)
        self.assertTrue(envelope["_friday_protected"])
        dumped = json.dumps(envelope)
        self.assertNotIn("super-secret-token", dumped)
        self.assertEqual(
            unwrap_secrets(envelope, unprotect=_unwrap),
            payload,
        )

    def test_legacy_plaintext_still_loads(self) -> None:
        legacy = {"gmail": {"access_token": "old-token"}}
        self.assertEqual(unwrap_secrets(legacy, unprotect=_unwrap), legacy)


class AllowlistTests(unittest.TestCase):
    def test_lists_folders(self) -> None:
        paths = list_allow_paths()
        self.assertTrue(paths)
        self.assertTrue(all(isinstance(item, str) and item for item in paths))


class Phase11OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actions = FakeActions()
        self.spoken: list[str] = []
        self.listen_replies: list[str] = []
        self._memory_folder, self.memory, _root = make_memory_store()
        self.env = patch.dict(
            os.environ,
            {
                "FRIDAY_REQUIRE_CONFIRM_SEND": "true",
                "FRIDAY_WHATSAPP_CONFIRM": "true",
            },
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
            listen=lambda: self.listen_replies.pop(0) if self.listen_replies else "",
            actions=self.actions,
            os_adapter=FakeOsAdapter(),
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=self.memory,
        )

    def test_whatsapp_message_waits_for_yes(self) -> None:
        staged = self._handle("send message to papa hello from friday")
        self.assertEqual(staged.task.intent, IntentName.WHATSAPP)
        self.assertIn("say send it", (staged.assistant_reply or "").lower())
        self.assertIsNotNone(get_pending())
        self.assertFalse(any(call[0] == "whatsapp" for call in self.actions.calls))
        sent = self._handle("yes")
        whatsapp = next(call for call in self.actions.calls if call[0] == "whatsapp")
        self.assertEqual(whatsapp[2], "hello from friday")
        self.assertEqual(whatsapp[3], "message")
        self.assertEqual(sent.task.status, TaskStatus.SUCCEEDED)
        self.assertIsNone(get_pending())

    def test_bare_send_confirms_pending_whatsapp(self) -> None:
        self._handle("send message to papa hello from friday")
        self._handle("send")
        whatsapp = next(call for call in self.actions.calls if call[0] == "whatsapp")
        self.assertEqual(whatsapp[3], "message")

    def test_whatsapp_no_cancels(self) -> None:
        self._handle("send message to papa hello from friday")
        cancelled = self._handle("no")
        self.assertEqual(cancelled.task.status, TaskStatus.CANCELLED)
        self.assertFalse(any(call[0] == "whatsapp" for call in self.actions.calls))
        self.assertIsNone(get_pending())

    def test_whatsapp_call_waits(self) -> None:
        staged = self._handle("call papa")
        self.assertEqual(staged.task.intent, IntentName.WHATSAPP)
        self.assertIn("say send it", (staged.assistant_reply or "").lower())
        self.assertFalse(any(call[0] == "whatsapp" for call in self.actions.calls))
        self._handle("sure")
        whatsapp = next(call for call in self.actions.calls if call[0] == "whatsapp")
        self.assertEqual(whatsapp[3], "call")

    def test_does_not_steal_existing_commands(self) -> None:
        self.assertEqual(classify("send message to papa").name, IntentName.WHATSAPP)
        self.assertEqual(classify("call papa").name, IntentName.WHATSAPP)
        self.assertEqual(classify("forget it").name, IntentName.CHAT)
        self.assertEqual(classify("I don't remember").name, IntentName.CHAT)
        self.assertEqual(classify("note that I prefer tea").name, IntentName.MEMORY)
        self.assertEqual(classify("search my documents for goa").name, IntentName.RESEARCH)
        self.assertEqual(classify("remind me later").name, IntentName.CHAT)
        self.assertEqual(classify("open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("yes").name, IntentName.CHAT)
        self.assertEqual(classify("send").name, IntentName.CHAT)

    def test_registry_blocks_unconfirmed_whatsapp(self) -> None:
        registry = build_legacy_registry(
            self.actions,
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=self.memory,
        )
        with self.assertRaises(ToolPermissionError):
            registry.invoke(
                COMMS_WHATSAPP_MESSAGE,
                {
                    "mobile_no": "919999999999",
                    "name": "Papa",
                    "message": "secret-hello",
                },
                ToolContext(task_id="phase11"),
            )

    def test_audit_has_no_secrets(self) -> None:
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
            ToolContext(task_id="phase11", confirmed=True),
        )
        rows = self.memory.list_audit()
        self.assertTrue(rows)
        dumped = json.dumps([row.to_dict() for row in rows])
        self.assertNotIn("secret-hello", dumped)
        self.assertNotIn("919999999999", dumped)
        self.assertIn("comms.whatsapp_message", dumped)

    def test_secret_store_wraps_tokens(self) -> None:
        store = IntegrationStore(
            self.memory.db_path,
            secret_box=SecretBox(protect=_wrap, unprotect=_unwrap),
        )
        store.save("gmail", {"access_token": "super-secret-token"})
        self.assertEqual(store.secrets_for("gmail")["access_token"], "super-secret-token")
        on_disk = store.secrets_path.read_text(encoding="utf-8")
        self.assertNotIn("super-secret-token", on_disk)
        self.assertIn("_friday_protected", on_disk)
        sqlite_dump = self.memory.db_path.read_bytes()
        self.assertNotIn(b"super-secret-token", sqlite_dump)


if __name__ == "__main__":
    unittest.main()
