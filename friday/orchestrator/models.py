from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class IntentName(str, Enum):
    YOUTUBE = "youtube"
    WHATSAPP = "whatsapp"
    OPEN = "open"
    OS = "os"
    MEDIA = "media"
    WEATHER = "weather"
    NEWS = "news"
    BROWSER = "browser"
    VISION = "vision"
    MEMORY = "memory"
    FILE = "file"
    CODE = "code"
    PRODUCTIVITY = "productivity"
    INTEGRATION = "integration"
    RESEARCH = "research"
    STOP = "stop"
    CHAT = "chat"


class TaskStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Intent:
    name: IntentName
    query: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskStep:
    agent: str
    tool: str
    status: TaskStatus = TaskStatus.PLANNED
    observation: str | None = None
    input_hash: str | None = None
    retry_count: int = 0


@dataclass
class Task:
    request: str
    intent: IntentName
    task_id: str = field(default_factory=lambda: uuid4().hex[:12])
    status: TaskStatus = TaskStatus.PLANNED
    steps: list[TaskStep] = field(default_factory=list)


@dataclass
class HandleResult:
    """Outcome of one user request.

    ``assistant_reply`` is spoken and shown in the chat drawer by the UI
    layer. Legacy YouTube / open / WhatsApp tools already speak themselves,
    so those paths leave this as ``None``.
    """

    continue_listening: bool = True
    assistant_reply: str | None = None
    task: Task | None = None
    observation: str | None = None
    status: TaskStatus | None = None
