from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Memory:
    id: int
    kind: str
    content: str
    source: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "id": self.id,
            "kind": self.kind,
            "content": self.content,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class DocumentInfo:
    id: int
    path: str
    title: str
    bytes: int
    ingested_at: str
    chunks: int = 0

    def to_dict(self) -> dict[str, str | int]:
        return {
            "id": self.id,
            "path": self.path,
            "title": self.title,
            "bytes": self.bytes,
            "ingested_at": self.ingested_at,
            "chunks": self.chunks,
        }


@dataclass(frozen=True)
class Note:
    id: int
    content: str
    created_at: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "id": self.id,
            "content": self.content,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class Reminder:
    id: int
    content: str
    due_at: str | None
    status: str
    created_at: str

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "id": self.id,
            "content": self.content,
            "due_at": self.due_at,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class TaskItem:
    id: int
    content: str
    status: str
    created_at: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class SearchHit:
    text: str
    score: float
    source: str  # memory | path
    title: str = ""
    memory_id: int | None = None
    document_id: int | None = None


@dataclass(frozen=True)
class AuditEntry:
    id: int
    created_at: str
    event: str
    task_id: str
    tool: str
    agent: str
    risk_level: str
    ok: bool
    input_hash: str
    observation: str
    error: str

    def to_dict(self) -> dict[str, str | int | bool]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "event": self.event,
            "task_id": self.task_id,
            "tool": self.tool,
            "agent": self.agent,
            "risk_level": self.risk_level,
            "ok": self.ok,
            "input_hash": self.input_hash,
            "observation": self.observation,
            "error": self.error,
        }


@dataclass(frozen=True)
class EventLog:
    id: int
    created_at: str
    event: str
    task_id: str
    intent: str
    tool: str
    tools: str
    status: str
    observation: str
    error: str
    duration_ms: int | None
    request: str

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "event": self.event,
            "task_id": self.task_id,
            "intent": self.intent,
            "tool": self.tool,
            "tools": self.tools,
            "status": self.status,
            "observation": self.observation,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "request": self.request,
        }
