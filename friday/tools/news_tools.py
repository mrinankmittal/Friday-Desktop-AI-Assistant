"""Live news headlines tool."""

from __future__ import annotations

from typing import Any

import requests

from friday.news.headlines import fetch_headlines, speak_headlines
from friday.tools.registry import FunctionTool, ToolRegistry
from friday.tools.types import (
    PermissionLevel,
    RiskLevel,
    ToolContext,
    ToolResult,
    ToolSpec,
)

NEWS_HEADLINES = "news.headlines"
NEWS_TOOL_NAMES = (NEWS_HEADLINES,)


def register_news_tools(registry: ToolRegistry) -> None:
    registry.register(_news_tool())


def _news_tool() -> FunctionTool:
    spec = ToolSpec(
        name=NEWS_HEADLINES,
        description="Speak live news headlines by topic or search query.",
        agent="system",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Category such as india, world, sports, or technology.",
                },
                "query": {
                    "type": "string",
                    "description": "Free-text search when they ask about a specific story.",
                },
            },
        },
        output_schema={
            "type": "object",
            "properties": {"reply": {"type": "string"}, "ok": {"type": "boolean"}},
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        topic = str(arguments.get("topic") or "").strip()
        query = str(arguments.get("query") or "").strip()
        try:
            data = fetch_headlines(topic=topic, query=query)
        except LookupError as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error), "ok": False},
                observation="no_headlines",
                error=str(error),
            )
        except (requests.RequestException, ValueError, TypeError) as error:
            reply = "I couldn't reach the news service. Try again in a moment."
            return ToolResult(
                ok=False,
                data={"reply": reply, "ok": False},
                observation="news_error",
                error=str(error),
            )
        reply = speak_headlines(data)
        return ToolResult(
            ok=True,
            data={"reply": reply, "ok": True, **data},
            observation="ok",
        )

    return FunctionTool(spec, execute)
