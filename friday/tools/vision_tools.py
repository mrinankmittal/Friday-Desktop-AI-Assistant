"""Screen describe / OCR / verify tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from friday.os_adapters import get_os_adapter
from friday.os_adapters.types import OsAdapter
from friday.providers.factory import get_vision_provider
from friday.providers.types import VisionProvider
from friday.providers.vision import format_ocr, verify_on_screen
from friday.tools.registry import FunctionTool, ToolRegistry
from friday.tools.types import (
    PermissionLevel,
    RiskLevel,
    ToolContext,
    ToolResult,
    ToolSpec,
)

VISION_DESCRIBE = "vision.describe_screen"
VISION_OCR = "vision.ocr"
VISION_VERIFY = "vision.verify"

VISION_TOOL_NAMES = (
    VISION_DESCRIBE,
    VISION_OCR,
    VISION_VERIFY,
)

_PATH_SCHEMA = {
    "path": {
        "type": "string",
        "description": "Optional PNG path; omit to capture the screen now",
    }
}


def register_vision_tools(
    registry: ToolRegistry,
    adapter: OsAdapter | None = None,
    vision: VisionProvider | None = None,
) -> None:
    os_adapter = adapter if adapter is not None else get_os_adapter()
    provider = vision if vision is not None else get_vision_provider()
    registry.register(_describe_tool(os_adapter, provider))
    registry.register(_ocr_tool(os_adapter, provider))
    registry.register(_verify_tool(os_adapter, provider))


def _capture(adapter: OsAdapter, raw_path: str) -> Path:
    cleaned = raw_path.strip()
    if cleaned:
        return Path(cleaned)
    return adapter.screenshot()


def _describe_tool(adapter: OsAdapter, vision: VisionProvider) -> FunctionTool:
    spec = ToolSpec(
        name=VISION_DESCRIBE,
        description="Capture the screen, list windows, and summarize visible text.",
        agent="vision",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": _PATH_SCHEMA,
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
        path = _capture(adapter, str(arguments.get("path") or ""))
        windows = adapter.list_windows()
        result = vision.describe(path, windows=windows)
        return ToolResult(
            ok=True,
            data={"reply": result.spoken, "path": str(path)},
            observation="ok",
        )

    return FunctionTool(spec, execute)


def _ocr_tool(adapter: OsAdapter, vision: VisionProvider) -> FunctionTool:
    spec = ToolSpec(
        name=VISION_OCR,
        description="Capture the screen and read visible text with OCR.",
        agent="vision",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": _PATH_SCHEMA,
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
        path = _capture(adapter, str(arguments.get("path") or ""))
        ocr = vision.ocr(path)
        reply = format_ocr(ocr)
        ok = bool(ocr.text.strip()) or ocr.available
        return ToolResult(
            ok=ok,
            data={"reply": reply, "path": str(path)},
            observation="ok" if ocr.text.strip() else "ocr_empty",
        )

    return FunctionTool(spec, execute)


def _verify_tool(adapter: OsAdapter, vision: VisionProvider) -> FunctionTool:
    spec = ToolSpec(
        name=VISION_VERIFY,
        description="Check whether text appears in window titles or on-screen OCR.",
        agent="vision",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["needle"],
            "properties": {
                "needle": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Text to look for on screen",
                },
                **_PATH_SCHEMA,
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "ok": {"type": "boolean"},
                "source": {"type": "string"},
            },
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        needle = str(arguments["needle"]).strip()
        path = _capture(adapter, str(arguments.get("path") or ""))
        windows = adapter.list_windows()
        ocr = vision.ocr(path)
        checked = verify_on_screen(
            needle,
            windows=windows,
            ocr_text=ocr.text,
            path=path,
        )
        return ToolResult(
            ok=True,
            data={
                "reply": checked.spoken,
                "ok": checked.ok,
                "source": checked.source,
                "path": str(path),
            },
            observation="verified" if checked.ok else "not_found",
        )

    return FunctionTool(spec, execute)
