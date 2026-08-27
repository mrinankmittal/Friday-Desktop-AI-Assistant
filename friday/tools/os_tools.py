"""Laptop-control tools backed by ``friday.os_adapters``."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from friday.os_adapters import get_os_adapter
from friday.os_adapters.types import OsAdapter, ProcessInfo, WindowInfo
from friday.tools.registry import FunctionTool, ToolRegistry
from friday.tools.types import (
    PermissionLevel,
    RiskLevel,
    ToolContext,
    ToolResult,
    ToolSpec,
)

OS_WINDOWS_LIST = "os.windows.list"
OS_WINDOWS_FOCUS = "os.windows.focus"
OS_PROCESSES_LIST = "os.processes.list"
OS_SCREENSHOT = "os.screenshot"
OS_CLIPBOARD_GET = "os.clipboard.get"
OS_CLIPBOARD_SET = "os.clipboard.set"
OS_AUTOMATE = "os.automate"
OS_INFO = "os.info"
OS_NETWORK = "os.network"

OS_TOOL_NAMES = (
    OS_WINDOWS_LIST,
    OS_WINDOWS_FOCUS,
    OS_PROCESSES_LIST,
    OS_SCREENSHOT,
    OS_CLIPBOARD_GET,
    OS_CLIPBOARD_SET,
    OS_AUTOMATE,
    OS_INFO,
    OS_NETWORK,
)

_WINDOW_LIMIT = 8
_PROCESS_LIMIT = 12
_CLIPBOARD_SPEAK_LIMIT = 300


def register_os_tools(
    registry: ToolRegistry,
    adapter: OsAdapter | None = None,
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    os_adapter = adapter or get_os_adapter()
    registry.register(_windows_list_tool(os_adapter))
    registry.register(_windows_focus_tool(os_adapter))
    registry.register(_processes_list_tool(os_adapter))
    registry.register(_screenshot_tool(os_adapter))
    registry.register(_clipboard_get_tool(os_adapter))
    registry.register(_clipboard_set_tool(os_adapter))
    registry.register(_automate_tool(os_adapter, sleeper=sleeper))
    registry.register(_info_tool())
    registry.register(_network_tool())


def format_windows(windows: list[WindowInfo]) -> str:
    if not windows:
        return "I don't see any open windows."
    titles = [window.title for window in windows[:_WINDOW_LIMIT]]
    extra = len(windows) - len(titles)
    spoken = ", ".join(titles)
    if extra > 0:
        return (
            f"There are {len(windows)} windows. The first ones are: {spoken}, "
            f"and {extra} more."
        )
    if len(titles) == 1:
        return f"The open window is {titles[0]}."
    return f"Open windows: {spoken}."


def format_processes(processes: list[ProcessInfo]) -> str:
    if not processes:
        return "I don't see any running processes."
    names: list[str] = []
    seen: set[str] = set()
    for process in processes:
        key = process.name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(process.name)
        if len(names) >= _PROCESS_LIMIT:
            break
    spoken = ", ".join(names)
    unique_total = len({item.name.casefold() for item in processes})
    leftover = unique_total - len(names)
    if leftover > 0:
        return f"Running processes include {spoken}, and {leftover} more."
    return f"Running processes: {spoken}."


def format_clipboard(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return "The clipboard is empty."
    if len(cleaned) > _CLIPBOARD_SPEAK_LIMIT:
        return cleaned[:_CLIPBOARD_SPEAK_LIMIT] + "…"
    return cleaned


def _windows_list_tool(adapter: OsAdapter) -> FunctionTool:
    spec = ToolSpec(
        name=OS_WINDOWS_LIST,
        description="List visible desktop window titles.",
        agent="system",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={"type": "object", "additionalProperties": False, "properties": {}},
        output_schema={
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "count": {"type": "integer"},
            },
        },
    )

    def execute(_arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        windows = adapter.list_windows()
        reply = format_windows(windows)
        return ToolResult(
            ok=True,
            data={"reply": reply, "count": len(windows)},
            observation="ok",
        )

    return FunctionTool(spec, execute)


def _windows_focus_tool(adapter: OsAdapter) -> FunctionTool:
    spec = ToolSpec(
        name=OS_WINDOWS_FOCUS,
        description="Focus a window whose title contains the given text.",
        agent="system",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["title"],
            "properties": {"title": {"type": "string", "minLength": 1}},
        },
        output_schema={
            "type": "object",
            "properties": {"reply": {"type": "string"}, "ok": {"type": "boolean"}},
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        title = str(arguments["title"]).strip()
        focused = adapter.focus_window(title)
        if focused:
            reply = f"Switched to {title}."
            return ToolResult(ok=True, data={"reply": reply, "ok": True})
        reply = f"I couldn't find a window named {title}."
        return ToolResult(
            ok=False,
            data={"reply": reply, "ok": False},
            observation="window_not_found",
        )

    return FunctionTool(spec, execute)


def _processes_list_tool(adapter: OsAdapter) -> FunctionTool:
    spec = ToolSpec(
        name=OS_PROCESSES_LIST,
        description="List running process image names.",
        agent="system",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={"type": "object", "additionalProperties": False, "properties": {}},
        output_schema={
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "count": {"type": "integer"},
            },
        },
    )

    def execute(_arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        processes = adapter.list_processes()
        reply = format_processes(processes)
        return ToolResult(
            ok=True,
            data={"reply": reply, "count": len(processes)},
            observation="ok",
        )

    return FunctionTool(spec, execute)


def _screenshot_tool(adapter: OsAdapter) -> FunctionTool:
    spec = ToolSpec(
        name=OS_SCREENSHOT,
        description="Capture the screen, save a PNG under Pictures/Friday, and open it.",
        agent="system",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "capture": {
                    "type": "boolean",
                    "description": "Take a new screenshot. False opens the latest saved one.",
                },
                "open": {
                    "type": "boolean",
                    "description": "Open the PNG in the default image viewer.",
                },
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "path": {"type": "string"},
            },
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        capture = arguments.get("capture", True)
        open_it = arguments.get("open", True)
        if capture is None:
            capture = True
        if open_it is None:
            open_it = True

        path = None
        if capture:
            path = adapter.screenshot()
        else:
            path = adapter.latest_screenshot()
            if path is None:
                return ToolResult(
                    ok=False,
                    data={
                        "reply": "I don't have a screenshot yet. Say take a screenshot first.",
                        "path": "",
                    },
                    observation="screenshot_missing",
                )

        opened = False
        if open_it:
            try:
                adapter.open_path(str(path))
                opened = True
            except OSError:
                opened = False

        if capture and opened:
            reply = f"Screenshot saved to {path}. Opening it."
        elif capture:
            reply = f"Screenshot saved to {path}."
        elif opened:
            reply = "Opening the screenshot."
        else:
            reply = f"I found the screenshot at {path}, but I couldn't open it."
        return ToolResult(
            ok=True,
            data={"reply": reply, "path": str(path), "opened": opened},
            observation="ok",
        )

    return FunctionTool(spec, execute)


def _clipboard_get_tool(adapter: OsAdapter) -> FunctionTool:
    spec = ToolSpec(
        name=OS_CLIPBOARD_GET,
        description="Read Unicode text from the clipboard.",
        agent="system",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.READ,
        input_schema={"type": "object", "additionalProperties": False, "properties": {}},
        output_schema={
            "type": "object",
            "properties": {"reply": {"type": "string"}},
        },
    )

    def execute(_arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        text = adapter.get_clipboard()
        reply = format_clipboard(text)
        return ToolResult(ok=True, data={"reply": reply}, observation="ok")

    return FunctionTool(spec, execute)


def _clipboard_set_tool(adapter: OsAdapter) -> FunctionTool:
    spec = ToolSpec(
        name=OS_CLIPBOARD_SET,
        description="Write Unicode text to the clipboard.",
        agent="system",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["text"],
            "properties": {"text": {"type": "string", "minLength": 1}},
        },
        output_schema={
            "type": "object",
            "properties": {"reply": {"type": "string"}},
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        text = str(arguments["text"])
        adapter.set_clipboard(text)
        return ToolResult(
            ok=True,
            data={"reply": "Copied to the clipboard."},
            observation="ok",
        )

    return FunctionTool(spec, execute)


def _automate_tool(
    adapter: OsAdapter,
    *,
    sleeper: Callable[[float], None],
) -> FunctionTool:
    from friday.os_adapters.app_control import run_app_task
    from friday.os_adapters.hotkeys import keys_for_task, task_reply

    spec = ToolSpec(
        name=OS_AUTOMATE,
        description="Open an app if needed, then type or press an allowlisted hotkey in it.",
        agent="system",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["task"],
            "properties": {
                "task": {"type": "string", "minLength": 1},
                "app": {"type": "string"},
                "keys": {"type": "string"},
                "text": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {"reply": {"type": "string"}, "ok": {"type": "boolean"}},
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        task = str(arguments.get("task") or "").strip().lower()
        app = str(arguments.get("app") or "").strip().lower()
        text = str(arguments.get("text") or "")
        keys = str(arguments.get("keys") or "")
        if app:
            result = run_app_task(
                adapter,
                app=app,
                task=task,
                text=text,
                keys=keys,
                sleeper=sleeper,
            )
            return ToolResult(
                ok=bool(result.get("ok")),
                data={"reply": str(result.get("reply") or ""), "ok": bool(result.get("ok"))},
                observation=str(result.get("observation") or "ok"),
            )
        if task == "type":
            from friday.os_adapters.app_control import paste_text

            if not text.strip():
                return ToolResult(
                    ok=False,
                    data={"reply": "I need something to type.", "ok": False},
                    observation="missing_text",
                )
            paste_text(adapter, text, sleeper)
            return ToolResult(
                ok=True,
                data={"reply": task_reply("type"), "ok": True},
                observation="ok",
            )
        sequence = keys_for_task(task, keys)
        if sequence is None:
            return ToolResult(
                ok=False,
                data={"reply": "I can't press that.", "ok": False},
                observation="unknown_hotkey",
            )
        adapter.press_hotkey(sequence)
        return ToolResult(
            ok=True,
            data={"reply": task_reply(task), "ok": True},
            observation="ok",
        )

    return FunctionTool(spec, execute)


def _info_tool() -> FunctionTool:
    from friday.os_adapters.info import system_info_reply

    spec = ToolSpec(
        name=OS_INFO,
        description="Speak safe laptop system information such as OS and hostname.",
        agent="system",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={"type": "object", "additionalProperties": False, "properties": {}},
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(_arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        reply = system_info_reply()
        return ToolResult(ok=True, data={"reply": reply}, observation="ok")

    return FunctionTool(spec, execute)


def _network_tool() -> FunctionTool:
    from friday.os_adapters.info import network_info_reply

    spec = ToolSpec(
        name=OS_NETWORK,
        description="Speak local IP and whether the network looks online.",
        agent="system",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={"type": "object", "additionalProperties": False, "properties": {}},
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(_arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        reply = network_info_reply()
        return ToolResult(ok=True, data={"reply": reply}, observation="ok")

    return FunctionTool(spec, execute)
