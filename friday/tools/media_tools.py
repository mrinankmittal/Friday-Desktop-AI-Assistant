"""Media transport control (play / pause / next / previous / stop).

Windows media keys drive whatever app owns the current media session, so this
controls Spotify, a browser playing YouTube, or any other player without any
login. "Play" is the one action that needs help: if nothing is playing yet
(Spotify is not even running) a bare play/pause key has no session to resume,
so we launch Spotify first, give it a moment to register, then press play.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

from friday.os_adapters import get_os_adapter
from friday.os_adapters.apps import execute_open, lookup_open_target
from friday.os_adapters.types import OsAdapter
from friday.tools.registry import FunctionTool, ToolRegistry
from friday.tools.types import (
    PermissionLevel,
    RiskLevel,
    ToolContext,
    ToolResult,
    ToolSpec,
)

MEDIA_CONTROL = "media.control"
MEDIA_TOOL_NAMES = (MEDIA_CONTROL,)

_ACTIONS = ("play", "pause", "next", "previous", "stop")

# play and pause are the same hardware toggle; only the spoken word differs.
_KEY_FOR_ACTION = {
    "play": "play_pause",
    "pause": "play_pause",
    "next": "next",
    "previous": "previous",
    "stop": "stop",
}

_REPLY = {
    "pause": "Pausing.",
    "next": "Skipping to the next track.",
    "previous": "Going back a track.",
    "stop": "Stopping playback.",
}

_DEFAULT_WARMUP_SEC = 3.5


def warmup_seconds() -> float:
    """Seconds to wait for a freshly launched Spotify to accept media keys."""
    raw = os.environ.get("FRIDAY_SPOTIFY_WARMUP_SEC")
    if not raw:
        return _DEFAULT_WARMUP_SEC
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_WARMUP_SEC
    return max(0.0, value)


def is_spotify_running(adapter: OsAdapter) -> bool:
    return any(
        process.name.casefold().startswith("spotify")
        for process in adapter.list_processes()
    )


def register_media_tools(
    registry: ToolRegistry,
    adapter: OsAdapter | None = None,
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    os_adapter = adapter or get_os_adapter()
    registry.register(_media_tool(os_adapter, sleeper=sleeper))


def _media_tool(
    adapter: OsAdapter,
    *,
    sleeper: Callable[[float], None],
) -> FunctionTool:
    spec = ToolSpec(
        name=MEDIA_CONTROL,
        description="Control media playback: play, pause, next, previous, stop.",
        agent="system",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["action"],
            "properties": {"action": {"type": "string", "enum": list(_ACTIONS)}},
        },
        output_schema={
            "type": "object",
            "properties": {"reply": {"type": "string"}, "ok": {"type": "boolean"}},
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        action = str(arguments["action"]).strip().lower()
        if action not in _KEY_FOR_ACTION:
            return ToolResult(
                ok=False,
                data={"reply": "I can't do that with the player.", "ok": False},
                observation="unknown_action",
            )

        reply = _REPLY.get(action, "Playing.")
        if action == "play" and not is_spotify_running(adapter):
            kind, target = lookup_open_target("spotify")
            if target:
                execute_open(kind, target, adapter)
                sleeper(warmup_seconds())
                reply = "Opening Spotify and starting playback."

        adapter.media_control(_KEY_FOR_ACTION[action])
        return ToolResult(ok=True, data={"reply": reply, "ok": True}, observation="ok")

    return FunctionTool(spec, execute)
