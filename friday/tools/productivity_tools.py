"""SQLite notes, reminders, and tasks."""

from __future__ import annotations

from typing import Any

from friday.memory import get_memory_store
from friday.memory.store import MemoryStore
from friday.memory.types import Note, Reminder, TaskItem
from friday.productivity import split_reminder
from friday.tools.registry import FunctionTool, ToolRegistry
from friday.tools.types import (
    PermissionLevel,
    RiskLevel,
    ToolContext,
    ToolResult,
    ToolSpec,
)

NOTES_ADD = "notes.add"
NOTES_LIST = "notes.list"
REMINDERS_ADD = "reminders.add"
REMINDERS_LIST = "reminders.list"
TASKS_ADD = "tasks.add"
TASKS_LIST = "tasks.list"
TASKS_DONE = "tasks.done"

PRODUCTIVITY_TOOL_NAMES = (
    NOTES_ADD,
    NOTES_LIST,
    REMINDERS_ADD,
    REMINDERS_LIST,
    TASKS_ADD,
    TASKS_LIST,
    TASKS_DONE,
)


def register_productivity_tools(
    registry: ToolRegistry,
    store: MemoryStore | None = None,
) -> None:
    memory = store if store is not None else get_memory_store()
    registry.register(_notes_add_tool(memory))
    registry.register(_notes_list_tool(memory))
    registry.register(_reminders_add_tool(memory))
    registry.register(_reminders_list_tool(memory))
    registry.register(_tasks_add_tool(memory))
    registry.register(_tasks_list_tool(memory))
    registry.register(_tasks_done_tool(memory))


def format_notes(notes: list[Note]) -> str:
    if not notes:
        return "You don't have any notes yet. Say add a note, then the text."
    lines = [f"Note {item.id}: {item.content}" for item in notes[:12]]
    spoken = "Here are your notes. " + " ".join(lines)
    if len(notes) > 12:
        spoken += f" And {len(notes) - 12} more in Settings."
    return spoken


def format_reminders(reminders: list[Reminder]) -> str:
    if not reminders:
        return "You don't have any reminders. Say remind me to, then the task."
    parts: list[str] = []
    for item in reminders[:12]:
        due = f" due {item.due_at}" if item.due_at else ""
        parts.append(f"Reminder {item.id}: {item.content}{due}.")
    spoken = "Here are your reminders. " + " ".join(parts)
    if len(reminders) > 12:
        spoken += f" And {len(reminders) - 12} more in Settings."
    return spoken


def format_tasks(tasks: list[TaskItem]) -> str:
    if not tasks:
        return "You don't have any open tasks. Say add a task, then the work."
    lines = [f"Task {item.id}: {item.content}." for item in tasks[:12]]
    spoken = "Here are your tasks. " + " ".join(lines)
    if len(tasks) > 12:
        spoken += f" And {len(tasks) - 12} more."
    return spoken


def _notes_add_tool(store: MemoryStore) -> FunctionTool:
    spec = ToolSpec(
        name=NOTES_ADD,
        description="Store a short note in SQLite.",
        agent="productivity",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["content"],
            "properties": {"content": {"type": "string", "minLength": 1}},
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        try:
            note = store.add_note(str(arguments["content"]))
        except ValueError as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        reply = f"I've added a note. Note {note.id}: {note.content}."
        return ToolResult(ok=True, data={"reply": reply, "id": note.id})

    return FunctionTool(spec, execute)


def _notes_list_tool(store: MemoryStore) -> FunctionTool:
    spec = ToolSpec(
        name=NOTES_LIST,
        description="List stored notes.",
        agent="productivity",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={"type": "object", "additionalProperties": False, "properties": {}},
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(_arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        notes = store.list_notes()
        reply = format_notes(notes)
        return ToolResult(
            ok=True,
            data={"reply": reply, "count": len(notes)},
            observation="ok" if notes else "empty",
        )

    return FunctionTool(spec, execute)


def _reminders_add_tool(store: MemoryStore) -> FunctionTool:
    spec = ToolSpec(
        name=REMINDERS_ADD,
        description="Store a reminder with an optional due time.",
        agent="productivity",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["content"],
            "properties": {
                "content": {"type": "string", "minLength": 1},
                "due_at": {"type": "string"},
            },
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        raw = str(arguments["content"])
        given_due = str(arguments.get("due_at") or "").strip() or None
        content, parsed_due = split_reminder(raw)
        due_at = given_due or parsed_due
        try:
            reminder = store.add_reminder(content, due_at=due_at)
        except ValueError as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        if reminder.due_at:
            reply = (
                f"I'll remind you to {reminder.content} at {reminder.due_at}. "
                f"That's reminder {reminder.id}."
            )
        else:
            reply = (
                f"I'll remind you to {reminder.content}. "
                f"That's reminder {reminder.id}."
            )
        return ToolResult(ok=True, data={"reply": reply, "id": reminder.id})

    return FunctionTool(spec, execute)


def _reminders_list_tool(store: MemoryStore) -> FunctionTool:
    spec = ToolSpec(
        name=REMINDERS_LIST,
        description="List open reminders.",
        agent="productivity",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={"type": "object", "additionalProperties": False, "properties": {}},
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(_arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        reminders = store.list_reminders()
        reply = format_reminders(reminders)
        return ToolResult(
            ok=True,
            data={"reply": reply, "count": len(reminders)},
            observation="ok" if reminders else "empty",
        )

    return FunctionTool(spec, execute)


def _tasks_add_tool(store: MemoryStore) -> FunctionTool:
    spec = ToolSpec(
        name=TASKS_ADD,
        description="Add an open personal task.",
        agent="productivity",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["content"],
            "properties": {"content": {"type": "string", "minLength": 1}},
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        try:
            task = store.add_task(str(arguments["content"]))
        except ValueError as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        reply = f"Task {task.id} added: {task.content}."
        return ToolResult(ok=True, data={"reply": reply, "id": task.id})

    return FunctionTool(spec, execute)


def _tasks_list_tool(store: MemoryStore) -> FunctionTool:
    spec = ToolSpec(
        name=TASKS_LIST,
        description="List open personal tasks.",
        agent="productivity",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={"type": "object", "additionalProperties": False, "properties": {}},
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(_arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        tasks = store.list_tasks()
        reply = format_tasks(tasks)
        return ToolResult(
            ok=True,
            data={"reply": reply, "count": len(tasks)},
            observation="ok" if tasks else "empty",
        )

    return FunctionTool(spec, execute)


def _tasks_done_tool(store: MemoryStore) -> FunctionTool:
    spec = ToolSpec(
        name=TASKS_DONE,
        description="Mark a personal task done by id or matching text.",
        agent="productivity",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["needle"],
            "properties": {"needle": {"type": "string", "minLength": 1}},
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        done = store.complete_task(str(arguments["needle"]))
        if done is None:
            return ToolResult(
                ok=False,
                data={"reply": "I couldn't find that open task."},
                observation="missing",
            )
        reply = f"Marked task {done.id} done: {done.content}."
        return ToolResult(ok=True, data={"reply": reply, "id": done.id})

    return FunctionTool(spec, execute)
