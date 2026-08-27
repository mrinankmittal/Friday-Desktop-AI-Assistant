"""Permission contract: what Friday refuses to do without being told twice.

Three gates are covered here: the confirm gate on high-risk sends, the file
allowlist, and secret handling. All three are the difference between a
mis-heard sentence being harmless and it being a message someone receives.
"""

from __future__ import annotations

import json
import os

import pytest

from friday.files.ops import read_file, write_file
from friday.integrations.store import IntegrationStore
from friday.memory.store import path_is_allowed
from friday.observability import clear_events, emit, recent_events, scrub_request
from friday.security.allowlist import list_allow_paths
from friday.security.secrets import SecretBox, unwrap_secrets, wrap_secrets
from friday.security.settings import require_confirm_send
from friday.tools.builtin import (
    APPS_OPEN,
    COMMS_WHATSAPP_CALL,
    COMMS_WHATSAPP_MESSAGE,
)
from friday.tools.integration_tools import DISCORD_SEND, EMAIL_SEND, SLACK_SEND
from friday.tools.registry import FunctionTool, InvokePolicy, ToolRegistry
from friday.tools.types import (
    PermissionLevel,
    RiskLevel,
    ToolContext,
    ToolPermissionError,
    ToolResult,
    ToolSpec,
)

pytestmark = pytest.mark.permissions

CONFIRM_ENV = "FRIDAY_REQUIRE_CONFIRM_SEND"

# Anything that reaches another human. Adding a tool here is a deliberate act.
TOOLS_THAT_NEED_CONFIRM = {
    COMMS_WHATSAPP_MESSAGE,
    COMMS_WHATSAPP_CALL,
    EMAIL_SEND,
    SLACK_SEND,
    DISCORD_SEND,
}

WHATSAPP_ARGS = {
    "mobile_no": "919999999999",
    "name": "Papa",
    "message": "secret-hello",
}


def _high_risk_tool() -> FunctionTool:
    spec = ToolSpec(
        name="test.send",
        description="Pretend to send something.",
        agent="communication",
        risk_level=RiskLevel.HIGH,
        permission_level=PermissionLevel.SEND,
        input_schema={
            "type": "object",
            "required": ["body"],
            "properties": {"body": {"type": "string"}},
        },
        output_schema={"type": "object"},
    )
    return FunctionTool(spec, lambda _a, _c: ToolResult(ok=True, observation="sent"))


class TestConfirmGate:
    def test_high_risk_set_is_exactly_the_send_tools(self, registry) -> None:
        high = {
            name
            for name in registry.names()
            if registry.get(name).spec.risk_level is RiskLevel.HIGH
        }
        assert high == TOOLS_THAT_NEED_CONFIRM

    @pytest.mark.parametrize("name", sorted(TOOLS_THAT_NEED_CONFIRM))
    def test_send_tools_declare_send_permission(self, registry, name: str) -> None:
        assert registry.get(name).spec.permission_level is PermissionLevel.SEND

    def test_unconfirmed_send_is_blocked(self, registry, actions) -> None:
        with pytest.raises(ToolPermissionError):
            registry.invoke(
                COMMS_WHATSAPP_MESSAGE, dict(WHATSAPP_ARGS), ToolContext(task_id="p")
            )
        assert not actions.called("whatsapp")

    def test_confirmed_send_goes_through(self, registry, actions) -> None:
        result = registry.invoke(
            COMMS_WHATSAPP_MESSAGE,
            dict(WHATSAPP_ARGS),
            ToolContext(task_id="p", confirmed=True),
        )
        assert result.ok
        assert actions.called("whatsapp")

    def test_gate_off_sends_without_confirm(self, open_registry, actions) -> None:
        open_registry.invoke(
            COMMS_WHATSAPP_MESSAGE, dict(WHATSAPP_ARGS), ToolContext(task_id="p")
        )
        assert actions.called("whatsapp")

    def test_low_risk_tool_is_never_gated(self, registry, actions) -> None:
        registry.invoke(APPS_OPEN, {"query": "open chrome"}, ToolContext(task_id="p"))
        assert actions.called("open_app")

    def test_denial_is_audited_without_the_message(self, registry, memory) -> None:
        with pytest.raises(ToolPermissionError):
            registry.invoke(
                COMMS_WHATSAPP_MESSAGE, dict(WHATSAPP_ARGS), ToolContext(task_id="p")
            )
        rows = memory.list_audit()
        assert rows[0].event == "tool_permission_denied"
        assert rows[0].ok is False
        dumped = json.dumps([row.to_dict() for row in rows])
        assert "secret-hello" not in dumped
        assert "919999999999" not in dumped

    def test_gate_survives_a_blocked_then_confirmed_retry(
        self, registry, actions
    ) -> None:
        with pytest.raises(ToolPermissionError):
            registry.invoke(
                COMMS_WHATSAPP_MESSAGE, dict(WHATSAPP_ARGS), ToolContext(task_id="p")
            )
        registry.invoke(
            COMMS_WHATSAPP_MESSAGE,
            dict(WHATSAPP_ARGS),
            ToolContext(task_id="p", confirmed=True),
        )
        assert len([c for c in actions.calls if c[0] == "whatsapp"]) == 1

    def test_synthetic_high_risk_tool_is_gated_too(self) -> None:
        registry = ToolRegistry(policy=InvokePolicy(require_confirm_for_high_risk=True))
        registry.register(_high_risk_tool())
        with pytest.raises(ToolPermissionError):
            registry.invoke("test.send", {"body": "hi"}, ToolContext(task_id="p"))


class TestConfirmSetting:
    def test_default_is_on_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(CONFIRM_ENV, raising=False)
        assert require_confirm_send() is True
        assert InvokePolicy.from_env().require_confirm_for_high_risk is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "off"])
    def test_explicit_opt_out(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv(CONFIRM_ENV, value)
        assert require_confirm_send() is False

    @pytest.mark.parametrize("value", ["true", "1", "yes", "", "maybe"])
    def test_anything_else_keeps_the_gate_on(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv(CONFIRM_ENV, value)
        assert require_confirm_send() is True


class TestFileAllowlist:
    def test_allowlist_is_never_empty(self) -> None:
        paths = list_allow_paths()
        assert paths
        assert all(isinstance(item, str) and item for item in paths)

    def test_path_inside_an_allowed_root_is_allowed(self, data_dir) -> None:
        target = data_dir / "notes.txt"
        target.write_text("hi", encoding="utf-8")
        assert path_is_allowed(target, (data_dir,))

    def test_path_outside_every_root_is_denied(self, data_dir, tmp_path) -> None:
        outside = tmp_path / "outside.txt"
        outside.write_text("hi", encoding="utf-8")
        assert not path_is_allowed(outside, (data_dir,))

    def test_read_outside_the_allowlist_raises(self, data_dir, tmp_path) -> None:
        outside = tmp_path / "outside.txt"
        outside.write_text("private", encoding="utf-8")
        with pytest.raises(PermissionError):
            read_file(outside, (data_dir,))

    def test_traversal_out_of_an_allowed_root_raises(self, data_dir, tmp_path) -> None:
        outside = tmp_path / "outside.txt"
        outside.write_text("private", encoding="utf-8")
        sneaky = data_dir / ".." / outside.name
        with pytest.raises((PermissionError, FileNotFoundError)):
            read_file(sneaky, (data_dir,))

    @pytest.mark.parametrize("name", [".env", "cookies.json", "model.onnx", "tool.exe"])
    def test_blocked_names_stay_blocked_inside_an_allowed_root(
        self, data_dir, name: str
    ) -> None:
        target = data_dir / name
        target.write_text("secret", encoding="utf-8")
        with pytest.raises(PermissionError):
            read_file(target, (data_dir,))

    def test_write_is_limited_to_text_files(self, data_dir) -> None:
        written = write_file(data_dir / "note.txt", "hello", (data_dir,))
        assert written.read_text(encoding="utf-8") == "hello"
        with pytest.raises(PermissionError):
            write_file(data_dir / "payload.exe", "hello", (data_dir,))

    def test_write_outside_the_allowlist_raises(self, data_dir, tmp_path) -> None:
        with pytest.raises(PermissionError):
            write_file(tmp_path / "note.txt", "hello", (data_dir,))


class TestSecretHandling:
    @staticmethod
    def _wrap(data: bytes) -> bytes:
        return b"WRAP" + data

    @staticmethod
    def _unwrap(data: bytes) -> bytes:
        return data[4:] if data.startswith(b"WRAP") else data

    def test_wrapped_envelope_hides_the_token(self) -> None:
        payload = {"gmail": {"access_token": "super-secret-token"}}
        envelope = wrap_secrets(payload, protect=self._wrap)
        assert envelope["_friday_protected"]
        assert "super-secret-token" not in json.dumps(envelope)
        assert unwrap_secrets(envelope, unprotect=self._unwrap) == payload

    def test_legacy_plaintext_still_loads(self) -> None:
        legacy = {"gmail": {"access_token": "old-token"}}
        assert unwrap_secrets(legacy, unprotect=self._unwrap) == legacy

    def test_sqlite_never_holds_the_token(self, memory) -> None:
        store = IntegrationStore(
            memory.db_path,
            secret_box=SecretBox(protect=self._wrap, unprotect=self._unwrap),
        )
        store.save("gmail", {"access_token": "super-secret-token"})
        assert store.secrets_for("gmail")["access_token"] == "super-secret-token"
        assert b"super-secret-token" not in memory.db_path.read_bytes()
        assert "super-secret-token" not in store.secrets_path.read_text(encoding="utf-8")


class TestTraceRedaction:
    """The developer log shows which command ran, not what it said."""

    @pytest.mark.parametrize(
        ("spoken", "expected"),
        [
            ("send message to papa hello from friday", "send message to papa <redacted>"),
            ("message to kabir i will be late", "message to kabir <redacted>"),
            ("send me an email saying the invoice is paid", "send me an email saying <redacted>"),
            ("copy to clipboard my api key", "copy to clipboard <redacted>"),
            ("text papa 919999999999", "text papa <redacted>"),
        ],
    )
    def test_bodies_are_dropped(self, spoken: str, expected: str) -> None:
        assert scrub_request(spoken) == expected

    @pytest.mark.parametrize(
        "spoken",
        [
            "send message to papa",
            "call papa",
            "open chrome",
            "list of windows",
            "read the clipboard",
            "search my documents for goa",
            "take a screenshot",
            "remind me to call papa tomorrow",
        ],
    )
    def test_ordinary_commands_stay_readable(self, spoken: str) -> None:
        assert scrub_request(spoken) == spoken

    def test_emitted_trace_never_carries_the_body(self, memory) -> None:
        clear_events()
        emit(
            "task_start",
            task_id="trace-1",
            store=memory,
            intent="whatsapp",
            request="send message to papa hello from friday",
        )
        buffered = recent_events(1)[0]
        assert "hello from friday" not in json.dumps(buffered)
        assert "hello from friday" not in json.dumps(
            [row.to_dict() for row in memory.list_events()]
        )


def test_env_is_restored_between_tests() -> None:
    """The autouse fixture pins the shipped default for every other test here."""
    assert os.environ[CONFIRM_ENV] == "true"
