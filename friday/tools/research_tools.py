"""Research agent tools: web report and local document summary."""

from __future__ import annotations

from typing import Any

from friday.browser import get_browser
from friday.browser.types import BrowserDriver
from friday.memory import get_memory_store
from friday.memory.store import MemoryStore
from friday.research import docs_research_report, web_research_report
from friday.tools.registry import FunctionTool, ToolRegistry
from friday.tools.types import (
    PermissionLevel,
    RiskLevel,
    ToolContext,
    ToolResult,
    ToolSpec,
)

RESEARCH_REPORT = "research.report"
RESEARCH_DOCS = "research.docs"

RESEARCH_TOOL_NAMES = (RESEARCH_REPORT, RESEARCH_DOCS)


def register_research_tools(
    registry: ToolRegistry,
    *,
    browser: BrowserDriver | None = None,
    memory: MemoryStore | None = None,
) -> None:
    driver = browser if browser is not None else get_browser()
    store = memory if memory is not None else get_memory_store()
    registry.register(_report_tool(driver))
    registry.register(_docs_tool(store))


def _report_tool(browser: BrowserDriver) -> FunctionTool:
    spec = ToolSpec(
        name=RESEARCH_REPORT,
        description="Search the web, read top results, and speak a short cited brief.",
        agent="research",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {"query": {"type": "string", "minLength": 1}},
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        query = str(arguments["query"]).strip()
        try:
            reply = web_research_report(query, browser)
        except Exception as error:
            return ToolResult(
                ok=False,
                data={"reply": "I couldn't finish that research right now."},
                observation="error",
                error=str(error),
            )
        return ToolResult(ok=True, data={"reply": reply}, observation="ok")

    return FunctionTool(spec, execute)


def _docs_tool(memory: MemoryStore) -> FunctionTool:
    spec = ToolSpec(
        name=RESEARCH_DOCS,
        description="Search ingested documents and speak a short cited summary.",
        agent="research",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {"query": {"type": "string", "minLength": 1}},
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        query = str(arguments["query"]).strip()
        try:
            reply = docs_research_report(query, memory)
        except Exception as error:
            return ToolResult(
                ok=False,
                data={"reply": "I couldn't search your documents right now."},
                observation="error",
                error=str(error),
            )
        return ToolResult(ok=True, data={"reply": reply}, observation="ok")

    return FunctionTool(spec, execute)
