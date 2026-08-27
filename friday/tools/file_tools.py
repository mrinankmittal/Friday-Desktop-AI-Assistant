"""Allowlisted file tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from friday.files.ops import (
    copy_file,
    day_window,
    folder_alias,
    format_read,
    format_search_hits,
    make_directory,
    move_file,
    read_file,
    resolve_user_path,
    search_files,
    write_file,
)
from friday.files.recent import last_file, remember_file
from friday.files.run_source import run_source_file
from friday.os_adapters import get_os_adapter
from friday.memory import get_memory_settings
from friday.tools.registry import FunctionTool, ToolRegistry
from friday.tools.types import (
    PermissionLevel,
    RiskLevel,
    ToolContext,
    ToolResult,
    ToolSpec,
)

FILES_SEARCH = "files.search"
FILES_READ = "files.read"
FILES_WRITE = "files.write"
FILES_MOVE = "files.move"
FILES_COPY = "files.copy"
FILES_MKDIR = "files.mkdir"
FILES_RUN = "files.run"

FILE_TOOL_NAMES = (
    FILES_SEARCH,
    FILES_READ,
    FILES_WRITE,
    FILES_MOVE,
    FILES_COPY,
    FILES_MKDIR,
    FILES_RUN,
)


def register_file_tools(
    registry: ToolRegistry,
    extra_allow: tuple[Path, ...] = (),
) -> None:
    allow_paths = extra_allow + get_memory_settings().allow_paths
    registry.register(_search_tool(allow_paths, extra_allow))
    registry.register(_read_tool(allow_paths, extra_allow))
    registry.register(_write_tool(allow_paths, extra_allow))
    registry.register(_move_tool(allow_paths, extra_allow))
    registry.register(_copy_tool(allow_paths, extra_allow))
    registry.register(_mkdir_tool(allow_paths, extra_allow))
    registry.register(_run_tool(allow_paths, extra_allow))


def _search_tool(allow_paths: tuple[Path, ...], extra_allow: tuple[Path, ...]) -> FunctionTool:
    spec = ToolSpec(
        name=FILES_SEARCH,
        description="Find files by name in allowed folders, optionally by day.",
        agent="file",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "needle": {"type": "string"},
                "folder": {"type": "string"},
                "when": {"type": "string", "enum": ["today", "yesterday", ""]},
            },
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        needle = str(arguments.get("needle") or "").strip()
        folder_name = str(arguments.get("folder") or "").strip()
        when = str(arguments.get("when") or "").strip().lower()
        folder = None
        if folder_name:
            folder = folder_alias(folder_name)
            if folder is None:
                folder = Path(folder_name).expanduser()
        after = before = None
        if when in {"today", "yesterday"}:
            after, before = day_window(when)
        try:
            hits = search_files(
                needle=needle,
                folder=folder,
                allow_paths=allow_paths,
                after=after,
                before=before,
            )
        except (OSError, ValueError, PermissionError) as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        reply = format_search_hits(hits, needle=needle)
        return ToolResult(
            ok=True,
            data={"reply": reply, "count": len(hits)},
            observation="ok" if hits else "empty",
        )

    return FunctionTool(spec, execute)


def _read_tool(allow_paths: tuple[Path, ...], extra_allow: tuple[Path, ...]) -> FunctionTool:
    spec = ToolSpec(
        name=FILES_READ,
        description="Read a text file from allowed folders.",
        agent="file",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string"},
                "open": {"type": "boolean"},
            },
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        raw = str(arguments.get("path") or "").strip()
        open_it = bool(arguments.get("open"))
        try:
            if raw:
                path = resolve_user_path(
                    raw, allow_paths=allow_paths, extra_roots=extra_allow
                )
            else:
                path = last_file()
                if path is None:
                    return ToolResult(
                        ok=False,
                        data={
                            "reply": (
                                "I haven't made a file yet. Say make a cpp file first."
                            )
                        },
                        observation="missing_file",
                    )
            text = read_file(path, allow_paths)
        except (OSError, ValueError, PermissionError) as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        reply = format_read(path, text)
        if open_it:
            try:
                get_os_adapter().open_path(str(path))
                reply = f"Opening {path.name}. {reply}"
            except OSError:
                reply = f"I found {path.name}, but I couldn't open it. {reply}"
        return ToolResult(ok=True, data={"reply": reply, "path": str(path)})

    return FunctionTool(spec, execute)


def _write_tool(
    allow_paths: tuple[Path, ...], extra_allow: tuple[Path, ...]
) -> FunctionTool:
    spec = ToolSpec(
        name=FILES_WRITE,
        description="Write a text file inside allowed folders.",
        agent="file",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["path", "text"],
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "text": {"type": "string"},
                "folder": {"type": "string"},
                "open": {"type": "boolean"},
            },
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        raw = str(arguments["path"]).strip()
        text = str(arguments.get("text") or "")
        folder_name = str(arguments.get("folder") or "").strip()
        target = Path(raw).expanduser()
        if not target.is_absolute():
            base = folder_alias(folder_name) if folder_name else None
            if base is None and folder_name:
                base = Path(folder_name).expanduser()
            if base is None:
                if extra_allow and not (extra_allow[0] / "friday").is_dir():
                    base = extra_allow[0]
                else:
                    base = Path.home() / "Documents"
            target = base / target.name
        try:
            saved = write_file(target, text, allow_paths)
        except (OSError, ValueError, PermissionError) as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        remember_file(saved)
        snippet = text.strip() or "(empty file)"
        if len(snippet) > 280:
            snippet = snippet[:277] + "..."
        reply = f"Saved {saved.name} in {saved.parent}. The code is: {snippet}"
        if arguments.get("open"):
            try:
                get_os_adapter().open_path(str(saved))
                reply = f"{reply} Opening it."
            except OSError:
                reply = f"{reply} I couldn't open it."
        return ToolResult(ok=True, data={"reply": reply, "path": str(saved)})

    return FunctionTool(spec, execute)


def _run_tool(
    allow_paths: tuple[Path, ...], extra_allow: tuple[Path, ...]
) -> FunctionTool:
    spec = ToolSpec(
        name=FILES_RUN,
        description="Compile and run the last .cpp/.c/.py file Friday wrote.",
        agent="file",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"path": {"type": "string"}},
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        raw = str(arguments.get("path") or "").strip()
        try:
            if raw:
                path = resolve_user_path(
                    raw, allow_paths=allow_paths, extra_roots=extra_allow
                )
            else:
                path = last_file()
                if path is None:
                    return ToolResult(
                        ok=False,
                        data={
                            "reply": (
                                "I haven't made a file yet. Say make a cpp file "
                                "named NAME first."
                            )
                        },
                        observation="missing_file",
                    )
            ok, reply = run_source_file(path, allow_paths)
        except (OSError, ValueError, PermissionError) as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        return ToolResult(
            ok=ok,
            data={"reply": reply, "path": str(path)},
            observation="ok" if ok else "run_failed",
        )

    return FunctionTool(spec, execute)


def _move_tool(allow_paths: tuple[Path, ...], extra_allow: tuple[Path, ...]) -> FunctionTool:
    spec = ToolSpec(
        name=FILES_MOVE,
        description="Move or rename a file inside allowed folders.",
        agent="file",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["source", "destination"],
            "properties": {
                "source": {"type": "string", "minLength": 1},
                "destination": {"type": "string", "minLength": 1},
            },
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        try:
            source = resolve_user_path(
                str(arguments["source"]),
                allow_paths=allow_paths,
                extra_roots=extra_allow,
            )
            dest_raw = str(arguments["destination"]).strip()
            alias = folder_alias(dest_raw)
            destination = alias if alias is not None else Path(dest_raw).expanduser()
            if not destination.is_absolute():
                destination = source.parent / dest_raw
            moved = move_file(source, destination, allow_paths)
        except (OSError, ValueError, PermissionError) as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        reply = f"Moved {moved.name} to {moved.parent}."
        return ToolResult(ok=True, data={"reply": reply, "path": str(moved)})

    return FunctionTool(spec, execute)


def _copy_tool(allow_paths: tuple[Path, ...], extra_allow: tuple[Path, ...]) -> FunctionTool:
    spec = ToolSpec(
        name=FILES_COPY,
        description="Copy a file inside allowed folders.",
        agent="file",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["source", "destination"],
            "properties": {
                "source": {"type": "string", "minLength": 1},
                "destination": {"type": "string", "minLength": 1},
            },
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        try:
            source = resolve_user_path(
                str(arguments["source"]),
                allow_paths=allow_paths,
                extra_roots=extra_allow,
            )
            dest_raw = str(arguments["destination"]).strip()
            alias = folder_alias(dest_raw)
            destination = alias if alias is not None else Path(dest_raw).expanduser()
            if not destination.is_absolute():
                destination = source.parent / dest_raw
            copied = copy_file(source, destination, allow_paths)
        except (OSError, ValueError, PermissionError) as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        reply = f"Copied {copied.name} to {copied.parent}."
        return ToolResult(ok=True, data={"reply": reply, "path": str(copied)})

    return FunctionTool(spec, execute)


def _mkdir_tool(allow_paths: tuple[Path, ...], extra_allow: tuple[Path, ...]) -> FunctionTool:
    del extra_allow
    spec = ToolSpec(
        name=FILES_MKDIR,
        description="Create a folder inside allowed folders.",
        agent="file",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["path"],
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "folder": {"type": "string"},
            },
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        raw = str(arguments["path"]).strip()
        folder_name = str(arguments.get("folder") or "").strip()
        try:
            target = Path(raw).expanduser()
            if not target.is_absolute():
                base = folder_alias(folder_name) if folder_name else None
                if base is None and folder_name:
                    base = Path(folder_name).expanduser()
                if base is None:
                    base = folder_alias("desktop") or (Path.home() / "Desktop")
                target = base / target.name
            created = make_directory(target, allow_paths)
        except (OSError, ValueError, PermissionError) as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        reply = f"Created folder {created.name} in {created.parent}."
        return ToolResult(ok=True, data={"reply": reply, "path": str(created)})

    return FunctionTool(spec, execute)
