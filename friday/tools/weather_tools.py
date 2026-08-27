"""India weather forecast tool."""

from __future__ import annotations

from typing import Any

import requests

from friday.tools.registry import FunctionTool, ToolRegistry
from friday.tools.types import (
    PermissionLevel,
    RiskLevel,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from friday.weather.india import DEFAULT_PLACE, fetch_forecast, speak_forecast

WEATHER_GET = "weather.get"
WEATHER_TOOL_NAMES = (WEATHER_GET,)


def register_weather_tools(registry: ToolRegistry) -> None:
    registry.register(_weather_tool())


def _weather_tool() -> FunctionTool:
    spec = ToolSpec(
        name=WEATHER_GET,
        description="Speak the current India weather forecast in Celsius.",
        agent="system",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "place": {
                    "type": "string",
                    "description": "Indian city. Defaults to New Delhi.",
                }
            },
        },
        output_schema={
            "type": "object",
            "properties": {"reply": {"type": "string"}, "ok": {"type": "boolean"}},
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        place = str(arguments.get("place") or "").strip() or DEFAULT_PLACE
        try:
            data = fetch_forecast(place)
        except LookupError as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error), "ok": False},
                observation="unknown_place",
                error=str(error),
            )
        except (requests.RequestException, ValueError, TypeError, KeyError) as error:
            reply = "I couldn't reach the weather service. Try again in a moment."
            return ToolResult(
                ok=False,
                data={"reply": reply, "ok": False},
                observation="weather_error",
                error=str(error),
            )
        reply = speak_forecast(data)
        return ToolResult(
            ok=True,
            data={"reply": reply, "ok": True, **data},
            observation="ok",
        )

    return FunctionTool(spec, execute)
