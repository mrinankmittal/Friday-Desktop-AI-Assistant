from __future__ import annotations

import json
import unittest

from friday.browser.fake import FakeBrowser
from friday.providers.fake import FakeVision
from friday.tools import (
    REGISTERED_TOOL_NAMES,
    InvokePolicy,
    RiskLevel,
    ToolContext,
    ToolPermissionError,
    ToolValidationError,
    build_legacy_registry,
)
from friday.tools.builtin import (
    APPS_OPEN,
    COMMS_WHATSAPP_CALL,
    COMMS_WHATSAPP_MESSAGE,
    CONTACTS_LOOKUP,
    LLM_CHAT,
    MEDIA_YOUTUBE_PLAY,
)
from friday.tools.browser_tools import BROWSER_SEARCH
from friday.tools.vision_tools import VISION_DESCRIBE
from friday.tools.redact import hash_arguments, redact_arguments
from friday.tools.schema import SchemaError, validate_schema
from tests.helpers import make_memory_store


class FakeActions:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def play_youtube(self, query: str) -> None:
        self.calls.append(("play_youtube", query))

    def open_app(self, query: str) -> None:
        self.calls.append(("open_app", query))

    def find_contact(self, query: str) -> tuple:
        self.calls.append(("find_contact", query))
        return ("919999999999", "Kabir")

    def whatsapp(self, mobile_no, message, flag, name) -> bool:
        self.calls.append(("whatsapp", mobile_no, message, flag, name))
        return True

    def chatbot(self, query: str) -> str:
        self.calls.append(("chatbot", query))
        return "fake reply"


class SchemaTests(unittest.TestCase):
    def test_rejects_missing_required(self) -> None:
        schema = {
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
        }
        with self.assertRaises(SchemaError):
            validate_schema(schema, {})

    def test_rejects_additional_properties(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"query": {"type": "string"}},
        }
        with self.assertRaises(SchemaError):
            validate_schema(schema, {"query": "x", "extra": 1})

    def test_enforces_enum(self) -> None:
        schema = {"type": "string", "enum": ["voice", "video"]}
        self.assertEqual(validate_schema(schema, "voice"), "voice")
        with self.assertRaises(SchemaError):
            validate_schema(schema, "group")


class RedactTests(unittest.TestCase):
    def test_redacts_phone_and_message(self) -> None:
        redacted = redact_arguments(
            {"mobile_no": "919999999999", "name": "Kabir", "message": "secret-hello"}
        )
        self.assertEqual(redacted["mobile_no"], "<redacted>")
        self.assertEqual(redacted["message"], "<redacted>")
        self.assertEqual(redacted["name"], "Kabir")

    def test_redacts_integration_payloads(self) -> None:
        redacted = redact_arguments(
            {
                "to": "a@b.com",
                "body": "secret-body",
                "access_token": "tok",
                "channel": "#general",
            }
        )
        self.assertEqual(redacted["to"], "<redacted>")
        self.assertEqual(redacted["body"], "<redacted>")
        self.assertEqual(redacted["access_token"], "<redacted>")
        self.assertEqual(redacted["channel"], "<redacted>")

    def test_hash_is_stable(self) -> None:
        payload = {"mobile_no": "919999999999", "message": "hi"}
        self.assertEqual(hash_arguments(payload), hash_arguments(payload))
        self.assertNotEqual(
            hash_arguments(payload),
            hash_arguments({"mobile_no": "919999999999", "message": "bye"}),
        )


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actions = FakeActions()
        self._memory_folder, self.memory, _root = make_memory_store()
        self.registry = build_legacy_registry(
            self.actions,
            policy=InvokePolicy(),
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=self.memory,
        )
        self.context = ToolContext(task_id="testtask")

    def tearDown(self) -> None:
        self._memory_folder.cleanup()

    def test_registers_expected_tools(self) -> None:
        self.assertEqual(tuple(self.registry.names()), tuple(sorted(REGISTERED_TOOL_NAMES)))

    def test_llm_manifest_has_schemas_not_python(self) -> None:
        manifest = self.registry.llm_manifest()
        names = {item["name"] for item in manifest}
        self.assertIn(APPS_OPEN, names)
        self.assertIn(MEDIA_YOUTUBE_PLAY, names)
        self.assertIn(COMMS_WHATSAPP_MESSAGE, names)
        self.assertIn(LLM_CHAT, names)
        self.assertIn(BROWSER_SEARCH, names)
        self.assertIn(VISION_DESCRIBE, names)
        self.assertIn("memory.remember", names)
        self.assertIn("files.search", names)
        self.assertIn("code.test", names)
        self.assertIn("notes.add", names)
        self.assertIn("reminders.add", names)
        self.assertIn("email.send", names)
        self.assertIn("slack.send", names)
        self.assertIn("discord.send", names)
        self.assertEqual(len(REGISTERED_TOOL_NAMES), 61)
        for item in manifest:
            self.assertIn("parameters", item)
            self.assertIn("risk_level", item)
            dumped = json.dumps(item)
            self.assertNotIn("def execute", dumped)
            self.assertNotIn("engine.features", dumped)

    def test_youtube_and_open_are_low_risk(self) -> None:
        youtube = self.registry.get(MEDIA_YOUTUBE_PLAY)
        open_app = self.registry.get(APPS_OPEN)
        self.assertEqual(youtube.spec.risk_level, RiskLevel.LOW)
        self.assertEqual(open_app.spec.risk_level, RiskLevel.LOW)

    def test_whatsapp_tools_are_high_risk(self) -> None:
        for name in (COMMS_WHATSAPP_MESSAGE, COMMS_WHATSAPP_CALL):
            self.assertEqual(self.registry.get(name).spec.risk_level, RiskLevel.HIGH)

    def test_invoke_open(self) -> None:
        result = self.registry.invoke(APPS_OPEN, {"query": "open chrome"}, self.context)
        self.assertTrue(result.ok)
        self.assertEqual(self.actions.calls[0], ("open_app", "open chrome"))
        self.assertIsNotNone(result.input_hash)

    def test_open_reports_failure(self) -> None:
        class FailingOpen(FakeActions):
            def open_app(self, query: str) -> bool:
                self.calls.append(("open_app", query))
                return False

        actions = FailingOpen()
        registry = build_legacy_registry(
            actions,
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=self.memory,
        )
        result = registry.invoke(APPS_OPEN, {"query": "open missing"}, self.context)
        self.assertFalse(result.ok)
        self.assertEqual(result.observation, "open_failed")

    def test_invalid_arguments_raise(self) -> None:
        with self.assertRaises(ToolValidationError):
            self.registry.invoke(MEDIA_YOUTUBE_PLAY, {}, self.context)

    def test_high_risk_confirm_policy_blocks_then_allows(self) -> None:
        registry = build_legacy_registry(
            self.actions,
            policy=InvokePolicy(require_confirm_for_high_risk=True),
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=self.memory,
        )
        payload = {
            "mobile_no": "919999999999",
            "name": "Kabir",
            "message": "secret-hello",
        }
        with self.assertRaises(ToolPermissionError):
            registry.invoke(COMMS_WHATSAPP_MESSAGE, payload, self.context)

        self.context.confirmed = True
        result = registry.invoke(COMMS_WHATSAPP_MESSAGE, payload, self.context)
        self.assertTrue(result.ok)

    def test_logs_do_not_include_message_or_phone(self) -> None:
        payload = {
            "mobile_no": "919999999999",
            "name": "Kabir",
            "message": "secret-hello",
        }
        with self.assertLogs("friday.tools", level="INFO") as captured:
            self.registry.invoke(COMMS_WHATSAPP_MESSAGE, payload, self.context)

        combined = "\n".join(captured.output)
        self.assertNotIn("secret-hello", combined)
        self.assertNotIn("919999999999", combined)
        self.assertIn("comms.whatsapp_message", combined)
        self.assertIn("high", combined)

    def test_opt_out_policy_sends_without_confirm(self) -> None:
        result = self.registry.invoke(
            COMMS_WHATSAPP_MESSAGE,
            {"mobile_no": "919999999999", "name": "Kabir", "message": "hi"},
            self.context,
        )
        self.assertTrue(result.ok)
        self.assertEqual(self.actions.calls[-1][3], "message")

    def test_contacts_lookup(self) -> None:
        result = self.registry.invoke(
            CONTACTS_LOOKUP, {"query": "send message to kabir"}, self.context
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.data["name"], "Kabir")


if __name__ == "__main__":
    unittest.main()
