"""Memory and document tools backed by ``friday.memory`` / ``friday.rag``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from friday.memory import (
    format_memory_list,
    format_search_hits,
    get_memory_settings,
    get_memory_store,
    guess_kind,
)
from friday.memory.store import MemoryStore
from friday.tools.registry import FunctionTool, ToolRegistry
from friday.tools.types import (
    PermissionLevel,
    RiskLevel,
    ToolContext,
    ToolResult,
    ToolSpec,
)

MEMORY_REMEMBER = "memory.remember"
MEMORY_LIST = "memory.list"
MEMORY_FORGET = "memory.forget"
MEMORY_INGEST = "memory.ingest"
RAG_SEARCH = "rag.search"

MEMORY_TOOL_NAMES = (
    MEMORY_REMEMBER,
    MEMORY_LIST,
    MEMORY_FORGET,
    MEMORY_INGEST,
    RAG_SEARCH,
)


def register_memory_tools(
    registry: ToolRegistry,
    store: MemoryStore | None = None,
) -> None:
    memory = store if store is not None else get_memory_store()
    allow_paths = get_memory_settings().allow_paths
    if store is not None:
        # Tests pass a store whose db folder is the allowlist root.
        allow_paths = (Path(store.db_path).parent,) + allow_paths
    registry.register(_remember_tool(memory))
    registry.register(_list_tool(memory))
    registry.register(_forget_tool(memory))
    registry.register(_ingest_tool(memory, allow_paths))
    registry.register(_search_tool(memory))


def _remember_tool(store: MemoryStore) -> FunctionTool:
    spec = ToolSpec(
        name=MEMORY_REMEMBER,
        description="Store a user fact or preference in local SQLite memory.",
        agent="memory",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["content"],
            "properties": {
                "content": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Fact to remember",
                }
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "id": {"type": "integer"},
            },
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        content = str(arguments["content"]).strip()
        saved = store.remember(content, kind=guess_kind(content))
        return ToolResult(
            ok=True,
            data={"reply": "I'll remember that.", "id": saved.id},
            observation="ok",
        )

    return FunctionTool(spec, execute)


def _list_tool(store: MemoryStore) -> FunctionTool:
    spec = ToolSpec(
        name=MEMORY_LIST,
        description="List stored user facts and preferences.",
        agent="memory",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
        output_schema={
            "type": "object",
            "properties": {"reply": {"type": "string"}},
        },
    )

    def execute(_arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        memories = store.list_memories()
        reply = format_memory_list(memories)
        return ToolResult(
            ok=True,
            data={"reply": reply, "count": len(memories)},
            observation="ok" if memories else "empty",
        )

    return FunctionTool(spec, execute)


def _forget_tool(store: MemoryStore) -> FunctionTool:
    spec = ToolSpec(
        name=MEMORY_FORGET,
        description="Delete a stored memory by id or matching text.",
        agent="memory",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "id": {"type": "integer"},
                "text": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {"reply": {"type": "string"}},
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        memory_id = arguments.get("id")
        text = str(arguments.get("text") or "").strip()
        if memory_id is None and not text:
            return ToolResult(
                ok=False,
                data={"reply": "Tell me which memory to forget."},
                observation="missing_target",
            )
        removed = store.forget(
            memory_id=int(memory_id) if memory_id is not None else None,
            text=text or None,
        )
        if not removed:
            return ToolResult(
                ok=False,
                data={"reply": "I don't have a memory matching that."},
                observation="not_found",
            )
        if len(removed) == 1:
            reply = "I forgot that."
        else:
            reply = f"I forgot {len(removed)} memories."
        return ToolResult(
            ok=True,
            data={"reply": reply, "removed": [item.id for item in removed]},
            observation="ok",
        )

    return FunctionTool(spec, execute)


def _ingest_tool(store: MemoryStore, allow_paths: tuple[Path, ...]) -> FunctionTool:
    spec = ToolSpec(
        name=MEMORY_INGEST,
        description="Ingest a local document into the RAG index.",
        agent="memory",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Local file path to index",
                }
            },
        },
        output_schema={
            "type": "object",
            "properties": {"reply": {"type": "string"}},
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        raw = str(arguments["path"]).strip().strip('"').strip("'")
        try:
            document = store.ingest_file(Path(raw), allow_paths)
        except FileNotFoundError:
            return ToolResult(
                ok=False,
                data={"reply": "I couldn't find that file."},
                observation="missing_file",
            )
        except PermissionError as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="blocked",
            )
        except ValueError as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="ingest_failed",
            )
        reply = (
            f"Indexed {document.chunks} chunks from {document.title}."
        )
        return ToolResult(
            ok=True,
            data={
                "reply": reply,
                "path": document.path,
                "chunks": document.chunks,
            },
            observation="ok",
        )

    return FunctionTool(spec, execute)


def _search_tool(store: MemoryStore) -> FunctionTool:
    spec = ToolSpec(
        name=RAG_SEARCH,
        description="Search stored memories and ingested documents.",
        agent="memory",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Search text",
                }
            },
        },
        output_schema={
            "type": "object",
            "properties": {"reply": {"type": "string"}},
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        query = str(arguments["query"]).strip()
        hits = store.search(query)
        reply = format_search_hits(hits, query)
        return ToolResult(
            ok=True,
            data={"reply": reply, "count": len(hits)},
            observation="ok" if hits else "empty",
        )

    return FunctionTool(spec, execute)
