from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from friday.memory.store import MemoryStore
from friday.observability import emit
from friday.security.settings import require_confirm_send
from friday.tools.redact import hash_arguments, redact_arguments
from friday.tools.schema import SchemaError, validate_schema
from friday.tools.types import (
    RiskLevel,
    Tool,
    ToolContext,
    ToolPermissionError,
    ToolResult,
    ToolSpec,
    ToolValidationError,
)

logger = logging.getLogger("friday.tools")

ToolHandler = Callable[[dict[str, Any], ToolContext], ToolResult]


@dataclass
class InvokePolicy:
    """High-risk tools (WhatsApp, email, Slack, Discord) wait for confirm when on."""

    require_confirm_for_high_risk: bool = False

    @classmethod
    def from_env(cls) -> InvokePolicy:
        return cls(require_confirm_for_high_risk=require_confirm_send())


class FunctionTool:
    """A tool backed by a Python function. The LLM never sees the function."""

    def __init__(self, spec: ToolSpec, handler: ToolHandler) -> None:
        self.spec = spec
        self._handler = handler

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return validate_schema(self.spec.input_schema, arguments)
        except SchemaError as error:
            raise ToolValidationError(str(error)) from error

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return self._handler(arguments, context)

    def rollback(self, arguments: dict[str, Any], observation: str | None) -> None:
        return None


class ToolRegistry:
    def __init__(
        self,
        policy: InvokePolicy | None = None,
        memory: MemoryStore | None = None,
    ) -> None:
        self.policy = policy or InvokePolicy.from_env()
        self._memory = memory
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as error:
            raise KeyError(f"Unknown tool: {name}") from error

    def names(self) -> list[str]:
        return sorted(self._tools)

    def llm_manifest(self) -> list[dict[str, Any]]:
        return [self._tools[name].spec.to_llm_dict() for name in self.names()]

    def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        tool = self.get(name)
        spec = tool.spec
        digest = hash_arguments(arguments)
        started = time.perf_counter()

        try:
            validated = tool.validate(arguments)
        except ToolValidationError as error:
            self._log(
                event="tool_validation_error",
                task_id=context.task_id,
                tool=spec.name,
                agent=spec.agent,
                risk_level=spec.risk_level.value,
                permission_level=spec.permission_level.value,
                ok=False,
                input_hash=digest,
                arguments=redact_arguments(arguments),
                error=str(error),
                duration_ms=0,
            )
            raise

        if (
            spec.risk_level is RiskLevel.HIGH
            and self.policy.require_confirm_for_high_risk
            and not context.confirmed
        ):
            self._log(
                event="tool_permission_denied",
                task_id=context.task_id,
                tool=spec.name,
                agent=spec.agent,
                risk_level=spec.risk_level.value,
                permission_level=spec.permission_level.value,
                ok=False,
                input_hash=digest,
                arguments=redact_arguments(validated),
                error="confirm_required",
                duration_ms=0,
            )
            raise ToolPermissionError(
                f"{spec.name} is high-risk and requires confirmation"
            )

        try:
            result = tool.execute(validated, context)
        except Exception:
            duration_ms = int((time.perf_counter() - started) * 1000)
            self._log(
                event="tool_exception",
                task_id=context.task_id,
                tool=spec.name,
                agent=spec.agent,
                risk_level=spec.risk_level.value,
                permission_level=spec.permission_level.value,
                ok=False,
                input_hash=digest,
                arguments=redact_arguments(validated),
                error="exception",
                duration_ms=duration_ms,
            )
            raise

        result.input_hash = digest
        duration_ms = int((time.perf_counter() - started) * 1000)
        self._log(
            event="tool_call",
            task_id=context.task_id,
            tool=spec.name,
            agent=spec.agent,
            risk_level=spec.risk_level.value,
            permission_level=spec.permission_level.value,
            ok=result.ok,
            input_hash=digest,
            arguments=redact_arguments(validated),
            observation=result.observation,
            error=result.error,
            duration_ms=duration_ms,
        )
        return result

    def _log(self, **fields: Any) -> None:
        logger.info(json.dumps(fields, default=str, sort_keys=True))
        try:
            emit(
                str(fields.get("event") or "tool_call"),
                task_id=str(fields.get("task_id") or ""),
                store=self._memory,
                log=False,
                tool=fields.get("tool"),
                status="ok" if fields.get("ok") else "error",
                observation=fields.get("observation"),
                error=fields.get("error"),
                duration_ms=fields.get("duration_ms"),
            )
        except Exception:
            logger.exception("event emit failed")
        if self._memory is None:
            return
        try:
            self._memory.record_audit(
                event=str(fields.get("event") or "tool_call"),
                task_id=fields.get("task_id"),
                tool=fields.get("tool"),
                agent=fields.get("agent"),
                risk_level=fields.get("risk_level"),
                ok=fields.get("ok"),
                input_hash=fields.get("input_hash"),
                observation=fields.get("observation"),
                error=fields.get("error"),
            )
        except Exception:
            logger.exception("audit persist failed")
