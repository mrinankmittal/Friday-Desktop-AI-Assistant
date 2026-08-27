"""Tool registry contract.

The planner only ever sees ``llm_manifest``, so a malformed spec is invisible
until a tool is called. These tests check every registered tool up front and
pin the registry's behaviour on bad names and bad arguments.
"""

from __future__ import annotations

import json

import pytest

from friday.tools.builtin import (
    APPS_OPEN,
    COMMS_WHATSAPP_MESSAGE,
    LLM_CHAT,
    REGISTERED_TOOL_NAMES,
)
from friday.tools.redact import hash_arguments, redact_arguments
from friday.tools.registry import FunctionTool, ToolRegistry
from friday.tools.schema import SchemaError, validate_schema
from friday.tools.types import (
    PermissionLevel,
    RiskLevel,
    ToolContext,
    ToolResult,
    ToolSpec,
    ToolValidationError,
)

pytestmark = pytest.mark.tools

KNOWN_AGENTS = {
    "system",
    "browser",
    "coding",
    "communication",
    "conversation",
    "file",
    "memory",
    "productivity",
    "research",
    "vision",
}


def _spec(name: str = "test.echo", risk: RiskLevel = RiskLevel.LOW) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Echo a value back.",
        agent="system",
        risk_level=risk,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {"query": {"type": "string", "minLength": 1}},
        },
        output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
    )


def _echo_tool(name: str = "test.echo", risk: RiskLevel = RiskLevel.LOW) -> FunctionTool:
    def execute(arguments, _context) -> ToolResult:
        return ToolResult(ok=True, data={"ok": True}, observation=arguments["query"])

    return FunctionTool(_spec(name, risk), execute)


def test_registry_holds_exactly_the_declared_tools(registry) -> None:
    assert sorted(registry.names()) == sorted(REGISTERED_TOOL_NAMES)


def test_tool_count_is_pinned(registry) -> None:
    """A new phase must not silently add or drop a tool."""
    assert len(registry.names()) == 61


@pytest.mark.parametrize("name", sorted(REGISTERED_TOOL_NAMES))
def test_every_spec_is_well_formed(registry, name: str) -> None:
    spec = registry.get(name).spec
    assert spec.name == name
    assert spec.description.strip()
    assert spec.description.endswith("."), "descriptions are sentences for the planner"
    assert spec.agent in KNOWN_AGENTS
    assert isinstance(spec.risk_level, RiskLevel)
    assert isinstance(spec.permission_level, PermissionLevel)
    assert spec.input_schema.get("type") == "object"
    assert isinstance(spec.output_schema, dict)


@pytest.mark.parametrize("name", sorted(REGISTERED_TOOL_NAMES))
def test_manifest_entry_is_json_and_hides_python(registry, name: str) -> None:
    entry = registry.get(name).spec.to_llm_dict()
    dumped = json.dumps(entry)
    assert set(entry) == {
        "name",
        "description",
        "agent",
        "risk_level",
        "permission_level",
        "parameters",
        "returns",
    }
    assert "function" not in dumped
    assert "friday." not in dumped


def test_manifest_covers_the_whole_registry(registry) -> None:
    manifest = registry.llm_manifest()
    assert [entry["name"] for entry in manifest] == registry.names()


def test_unknown_tool_raises_keyerror(registry) -> None:
    with pytest.raises(KeyError):
        registry.get("does.not.exist")


def test_duplicate_registration_is_rejected() -> None:
    bare = ToolRegistry()
    bare.register(_echo_tool())
    with pytest.raises(ValueError, match="already registered"):
        bare.register(_echo_tool())


class TestArgumentValidation:
    @pytest.fixture
    def bare(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(_echo_tool())
        return registry

    def test_missing_required_argument(self, bare: ToolRegistry) -> None:
        with pytest.raises(ToolValidationError):
            bare.invoke("test.echo", {}, ToolContext(task_id="t"))

    def test_wrong_type(self, bare: ToolRegistry) -> None:
        with pytest.raises(ToolValidationError):
            bare.invoke("test.echo", {"query": 7}, ToolContext(task_id="t"))

    def test_unexpected_argument(self, bare: ToolRegistry) -> None:
        with pytest.raises(ToolValidationError):
            bare.invoke(
                "test.echo",
                {"query": "hi", "shell": "rm -rf /"},
                ToolContext(task_id="t"),
            )

    def test_min_length(self, bare: ToolRegistry) -> None:
        with pytest.raises(ToolValidationError):
            bare.invoke("test.echo", {"query": ""}, ToolContext(task_id="t"))

    def test_valid_call_returns_result(self, bare: ToolRegistry) -> None:
        result = bare.invoke("test.echo", {"query": "hi"}, ToolContext(task_id="t"))
        assert result.ok
        assert result.observation == "hi"
        assert result.input_hash


@pytest.mark.parametrize(
    "schema, value",
    [
        ({"type": "string"}, 1),
        ({"type": "boolean"}, "true"),
        ({"type": "integer"}, True),
        ({"type": "integer"}, "3"),
        ({"type": "string", "enum": ["a", "b"]}, "c"),
        ({"type": "object", "required": ["a"]}, {}),
    ],
)
def test_schema_subset_rejects(schema, value) -> None:
    with pytest.raises(SchemaError):
        validate_schema(schema, value)


def test_input_hash_is_stable_and_hides_the_value() -> None:
    args = {"mobile_no": "919999999999", "message": "secret-hello"}
    digest = hash_arguments(args)
    assert digest == hash_arguments(dict(reversed(list(args.items()))))
    assert digest != hash_arguments({**args, "message": "other"})
    assert "919999999999" not in digest
    assert "secret-hello" not in digest


def test_redaction_masks_bodies_but_keeps_shape() -> None:
    redacted = redact_arguments(
        {"mobile_no": "919999999999", "message": "secret-hello", "name": "Papa"}
    )
    assert redacted["mobile_no"] == "<redacted>"
    assert redacted["message"] == "<redacted>"
    assert redacted["name"] == "Papa"


def test_successful_call_is_audited_without_arguments(registry, memory) -> None:
    registry.invoke(APPS_OPEN, {"query": "open chrome"}, ToolContext(task_id="audit-1"))
    rows = memory.list_audit()
    assert rows
    row = rows[0]
    assert row.tool == APPS_OPEN
    assert row.ok
    assert row.task_id == "audit-1"
    assert row.input_hash
    dumped = json.dumps([entry.to_dict() for entry in rows])
    assert "open chrome" not in dumped


def test_failing_tool_is_audited_as_not_ok(memory) -> None:
    def boom(_arguments, _context) -> ToolResult:
        return ToolResult(ok=False, observation="nope", error="boom")

    registry = ToolRegistry(memory=memory)
    registry.register(FunctionTool(_spec("test.boom"), boom))
    result = registry.invoke("test.boom", {"query": "hi"}, ToolContext(task_id="t"))
    assert not result.ok
    assert memory.list_audit()[0].ok is False


def test_raising_tool_is_audited_then_reraised(memory) -> None:
    def boom(_arguments, _context):
        raise RuntimeError("kaboom")

    registry = ToolRegistry(memory=memory)
    registry.register(FunctionTool(_spec("test.raise"), boom))
    with pytest.raises(RuntimeError):
        registry.invoke("test.raise", {"query": "hi"}, ToolContext(task_id="t"))
    row = memory.list_audit()[0]
    assert row.event == "tool_exception"
    assert row.ok is False
    assert "kaboom" not in json.dumps(row.to_dict())


def test_chat_tool_is_low_risk_and_whatsapp_is_high(registry) -> None:
    assert registry.get(LLM_CHAT).spec.risk_level is RiskLevel.LOW
    assert registry.get(COMMS_WHATSAPP_MESSAGE).spec.risk_level is RiskLevel.HIGH
