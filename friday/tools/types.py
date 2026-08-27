from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PermissionLevel(str, Enum):
    READ = "read"
    LOCAL_APP = "local_app"
    SEND = "send"
    SESSION = "session"


class ToolError(Exception):
    """Base error for the tool registry."""


class ToolValidationError(ToolError):
    """Arguments did not match the tool's JSON Schema."""


class ToolPermissionError(ToolError):
    """High-risk tool blocked because confirmation was required and missing."""


SpeakFn = Callable[[str], None]
ListenFn = Callable[[], str]


@dataclass
class ToolSpec:
    name: str
    description: str
    agent: str
    risk_level: RiskLevel
    permission_level: PermissionLevel
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]

    def to_llm_dict(self) -> dict[str, Any]:
        """JSON the planner/LLM can see. No Python source."""
        return {
            "name": self.name,
            "description": self.description,
            "agent": self.agent,
            "risk_level": self.risk_level.value,
            "permission_level": self.permission_level.value,
            "parameters": self.input_schema,
            "returns": self.output_schema,
        }


@dataclass
class ToolContext:
    task_id: str
    speak: SpeakFn | None = None
    listen: ListenFn | None = None
    confirmed: bool = False


@dataclass
class ToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    observation: str = "ok"
    error: str | None = None
    input_hash: str | None = None


class Tool(Protocol):
    spec: ToolSpec

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]: ...

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult: ...

    def rollback(
        self,
        arguments: dict[str, Any],
        observation: str | None,
    ) -> None: ...
