"""Browser tools backed by ``friday.browser``."""

from __future__ import annotations

from typing import Any

from friday.browser import get_browser
from friday.browser.format import format_open, format_read, format_search
from friday.browser.types import BrowserDriver
from friday.browser.urls import normalize_url
from friday.tools.registry import FunctionTool, ToolRegistry
from friday.tools.types import (
    PermissionLevel,
    RiskLevel,
    ToolContext,
    ToolResult,
    ToolSpec,
)

BROWSER_SEARCH = "browser.search"
BROWSER_OPEN = "browser.open"
BROWSER_READ = "browser.read"
BROWSER_CLICK = "browser.click"
BROWSER_FILL = "browser.fill"
BROWSER_DOWNLOAD = "browser.download"
BROWSER_TABS = "browser.tabs"

BROWSER_TOOL_NAMES = (
    BROWSER_SEARCH,
    BROWSER_OPEN,
    BROWSER_READ,
    BROWSER_CLICK,
    BROWSER_FILL,
    BROWSER_DOWNLOAD,
    BROWSER_TABS,
)


def register_browser_tools(
    registry: ToolRegistry,
    browser: BrowserDriver | None = None,
) -> None:
    driver = browser if browser is not None else get_browser()
    registry.register(_search_tool(driver))
    registry.register(_open_tool(driver))
    registry.register(_read_tool(driver))
    registry.register(_click_tool(driver))
    registry.register(_fill_tool(driver))
    registry.register(_download_tool(driver))
    registry.register(_tabs_tool(driver))


def _search_tool(driver: BrowserDriver) -> FunctionTool:
    spec = ToolSpec(
        name=BROWSER_SEARCH,
        description="Search the public web and return top result titles and snippets.",
        agent="browser",
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
                    "description": "Search terms",
                }
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "count": {"type": "integer"},
            },
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        query = str(arguments["query"]).strip()
        try:
            result = driver.search(query)
        except Exception as exc:
            reply = "I couldn't search the web right now."
            return ToolResult(
                ok=False,
                data={"reply": reply, "count": 0},
                observation="browser_error",
                error=str(exc),
            )
        reply = format_search(result)
        return ToolResult(
            ok=bool(result.hits) or not result.extracted,
            data={"reply": reply, "count": len(result.hits)},
            observation="ok" if result.hits or not result.extracted else "no_results",
        )

    return FunctionTool(spec, execute)


def _open_tool(driver: BrowserDriver) -> FunctionTool:
    spec = ToolSpec(
        name=BROWSER_OPEN,
        description="Open an http(s) URL in the browser agent.",
        agent="browser",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["url"],
            "properties": {
                "url": {
                    "type": "string",
                    "minLength": 1,
                    "description": "http or https URL",
                }
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "url": {"type": "string"},
            },
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        raw = str(arguments["url"]).strip()
        url = normalize_url(raw)
        if url is None:
            reply = "That doesn't look like a safe web address."
            return ToolResult(
                ok=False,
                data={"reply": reply, "url": raw},
                observation="invalid_url",
            )
        try:
            page = driver.open_url(url)
        except Exception as exc:
            reply = "I couldn't open that page."
            return ToolResult(
                ok=False,
                data={"reply": reply, "url": url},
                observation="browser_error",
                error=str(exc),
            )
        reply = format_open(page)
        return ToolResult(
            ok=bool(page.url) or page.extracted is False,
            data={"reply": reply, "url": page.url or url},
            observation="ok",
        )

    return FunctionTool(spec, execute)


def _read_tool(driver: BrowserDriver) -> FunctionTool:
    spec = ToolSpec(
        name=BROWSER_READ,
        description="Read visible text from the current page or a given URL.",
        agent="browser",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Optional http(s) URL; omit to read the current page",
                }
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
            },
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        raw = str(arguments.get("url") or "").strip()
        url = normalize_url(raw) if raw else None
        if raw and url is None:
            reply = "That doesn't look like a safe web address."
            return ToolResult(
                ok=False,
                data={"reply": reply},
                observation="invalid_url",
            )
        try:
            page = driver.read(url)
        except Exception as exc:
            reply = "I couldn't read that page."
            return ToolResult(
                ok=False,
                data={"reply": reply},
                observation="browser_error",
                error=str(exc),
            )
        reply = format_read(page)
        ok = bool(page.text) or (not page.extracted and bool(page.url))
        return ToolResult(
            ok=ok or bool(page.title),
            data={"reply": reply},
            observation="ok" if ok or page.title else "empty_page",
        )

    return FunctionTool(spec, execute)


def _click_tool(driver: BrowserDriver) -> FunctionTool:
    spec = ToolSpec(
        name=BROWSER_CLICK,
        description="Click a button, link, or CSS selector on the current page.",
        agent="browser",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["target"],
            "properties": {"target": {"type": "string", "minLength": 1}},
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        target = str(arguments["target"]).strip()
        try:
            result = driver.click(target)
        except Exception as exc:
            return ToolResult(
                ok=False,
                data={"reply": "I couldn't click that."},
                observation="browser_error",
                error=str(exc),
            )
        return ToolResult(
            ok=result.ok,
            data={"reply": result.reply, "url": result.url},
            observation="ok" if result.ok else "click_failed",
        )

    return FunctionTool(spec, execute)


def _fill_tool(driver: BrowserDriver) -> FunctionTool:
    spec = ToolSpec(
        name=BROWSER_FILL,
        description="Fill an input field by label, name, or CSS selector.",
        agent="browser",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["target", "value"],
            "properties": {
                "target": {"type": "string", "minLength": 1},
                "value": {"type": "string"},
            },
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        target = str(arguments["target"]).strip()
        value = str(arguments.get("value") or "")
        try:
            result = driver.fill(target, value)
        except Exception as exc:
            return ToolResult(
                ok=False,
                data={"reply": "I couldn't fill that field."},
                observation="browser_error",
                error=str(exc),
            )
        return ToolResult(
            ok=result.ok,
            data={"reply": result.reply, "url": result.url},
            observation="ok" if result.ok else "fill_failed",
        )

    return FunctionTool(spec, execute)


def _download_tool(driver: BrowserDriver) -> FunctionTool:
    from pathlib import Path

    from friday.files.ops import folder_alias
    from friday.memory import get_memory_settings
    from friday.memory.store import path_is_allowed

    spec = ToolSpec(
        name=BROWSER_DOWNLOAD,
        description="Download a file from a URL or named control into Downloads.",
        agent="browser",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["target"],
            "properties": {
                "target": {"type": "string", "minLength": 1},
                "folder": {"type": "string"},
            },
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        target = str(arguments["target"]).strip()
        folder_name = str(arguments.get("folder") or "downloads").strip() or "downloads"
        dest = folder_alias(folder_name) or (Path.home() / "Downloads")
        allow = get_memory_settings().allow_paths
        if not path_is_allowed(dest, allow):
            return ToolResult(
                ok=False,
                data={"reply": "That download folder is not allowed."},
                observation="denied",
            )
        try:
            result = driver.download(target, str(dest))
        except Exception as exc:
            return ToolResult(
                ok=False,
                data={"reply": "I couldn't download that."},
                observation="browser_error",
                error=str(exc),
            )
        return ToolResult(
            ok=result.ok,
            data={"reply": result.reply, "path": result.path, "url": result.url},
            observation="ok" if result.ok else "download_failed",
        )

    return FunctionTool(spec, execute)


def _tabs_tool(driver: BrowserDriver) -> FunctionTool:
    spec = ToolSpec(
        name=BROWSER_TABS,
        description="List browser tabs, or open a URL in a new tab.",
        agent="browser",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"url": {"type": "string"}},
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        raw = str(arguments.get("url") or "").strip()
        url = normalize_url(raw) if raw else None
        if raw and url is None:
            return ToolResult(
                ok=False,
                data={"reply": "That doesn't look like a safe web address."},
                observation="invalid_url",
            )
        try:
            tabs = driver.tabs(url)
        except Exception as exc:
            return ToolResult(
                ok=False,
                data={"reply": "I couldn't manage browser tabs."},
                observation="browser_error",
                error=str(exc),
            )
        if not tabs:
            reply = "There are no browser tabs open yet."
        else:
            parts = [
                f"Tab {tab.index + 1}: {tab.title or tab.url or 'untitled'}"
                for tab in tabs[:8]
            ]
            reply = "Open tabs. " + ". ".join(parts) + "."
            if url:
                reply = f"Opened a new tab. {reply}"
        return ToolResult(
            ok=True,
            data={"reply": reply, "count": len(tabs)},
            observation="ok",
        )

    return FunctionTool(spec, execute)
