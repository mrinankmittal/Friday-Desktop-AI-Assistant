"""Workspace-scoped coding tools. Unittest only; no free-form shell."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from friday.code import (
    explain_workspace_file,
    format_code_read,
    format_test_output,
    patch_workspace_file,
    read_workspace_file,
    resolve_workspace_file,
    run_unittests,
    workspace_root,
)
from friday.tools.registry import FunctionTool, ToolRegistry
from friday.tools.types import (
    PermissionLevel,
    RiskLevel,
    ToolContext,
    ToolResult,
    ToolSpec,
)

CODE_READ = "code.read"
CODE_PATCH = "code.patch"
CODE_TEST = "code.test"
CODE_EXPLAIN = "code.explain"

CODE_TOOL_NAMES = (CODE_READ, CODE_PATCH, CODE_TEST, CODE_EXPLAIN)


def register_code_tools(
    registry: ToolRegistry,
    workspace: Path | None = None,
) -> None:
    root = workspace if workspace is not None else workspace_root()
    registry.register(_read_tool(root))
    registry.register(_patch_tool(root))
    registry.register(_test_tool(root))
    registry.register(_explain_tool(root))


def _read_tool(workspace: Path) -> FunctionTool:
    spec = ToolSpec(
        name=CODE_READ,
        description="Read a source file from the Friday workspace.",
        agent="coding",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["path"],
            "properties": {"path": {"type": "string", "minLength": 1}},
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        raw = str(arguments["path"]).strip()
        try:
            path = resolve_workspace_file(raw, workspace)
            text = read_workspace_file(Path(raw), workspace)
        except (OSError, ValueError, PermissionError) as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        reply = format_code_read(path.relative_to(workspace), text)
        return ToolResult(ok=True, data={"reply": reply, "path": str(path)})

    return FunctionTool(spec, execute)


def _patch_tool(workspace: Path) -> FunctionTool:
    spec = ToolSpec(
        name=CODE_PATCH,
        description="Replace one exact snippet in a workspace file.",
        agent="coding",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["path", "old", "new"],
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "old": {"type": "string", "minLength": 1},
                "new": {"type": "string"},
            },
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        try:
            path = patch_workspace_file(
                Path(str(arguments["path"])),
                str(arguments["old"]),
                str(arguments["new"]),
                workspace,
            )
        except (OSError, ValueError, PermissionError) as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        reply = f"Updated {path.name}."
        return ToolResult(ok=True, data={"reply": reply, "path": str(path)})

    return FunctionTool(spec, execute)


def _test_tool(workspace: Path) -> FunctionTool:
    spec = ToolSpec(
        name=CODE_TEST,
        description="Run unittest in the workspace. No arbitrary shell commands.",
        agent="coding",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"target": {"type": "string"}},
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        target = str(arguments.get("target") or "").strip()
        try:
            code, output = run_unittests(workspace, target)
        except (OSError, ValueError, PermissionError) as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        reply = format_test_output(code, output)
        return ToolResult(
            ok=code == 0,
            data={"reply": reply, "returncode": code},
            observation="ok" if code == 0 else "failed",
        )

    return FunctionTool(spec, execute)


def _explain_tool(workspace: Path) -> FunctionTool:
    spec = ToolSpec(
        name=CODE_EXPLAIN,
        description="Explain a workspace source file in a few spoken sentences.",
        agent="coding",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["path"],
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "focus": {"type": "string"},
            },
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        raw = str(arguments["path"]).strip()
        focus = str(arguments.get("focus") or "").strip()
        try:
            path = resolve_workspace_file(raw, workspace)
            reply = explain_workspace_file(path, workspace, focus=focus)
        except (OSError, ValueError, PermissionError) as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        return ToolResult(ok=True, data={"reply": reply, "path": str(path)})

    return FunctionTool(spec, execute)
