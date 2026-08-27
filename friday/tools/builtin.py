"""Legacy ``engine.features`` functions registered as Friday 2.0 tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from friday.browser.types import BrowserDriver
from friday.code import workspace_root
from friday.tools.browser_tools import BROWSER_TOOL_NAMES, register_browser_tools
from friday.tools.code_tools import CODE_TOOL_NAMES, register_code_tools
from friday.tools.file_tools import FILE_TOOL_NAMES, register_file_tools
from friday.tools.memory_tools import MEMORY_TOOL_NAMES, register_memory_tools
from friday.tools.media_tools import MEDIA_TOOL_NAMES, register_media_tools
from friday.tools.os_tools import OS_TOOL_NAMES, register_os_tools
from friday.tools.productivity_tools import (
    PRODUCTIVITY_TOOL_NAMES,
    register_productivity_tools,
)
from friday.tools.integration_tools import (
    INTEGRATION_TOOL_NAMES,
    register_integration_tools,
)
from friday.tools.vision_tools import VISION_TOOL_NAMES, register_vision_tools
from friday.tools.weather_tools import WEATHER_TOOL_NAMES, register_weather_tools
from friday.tools.news_tools import NEWS_TOOL_NAMES, register_news_tools
from friday.tools.research_tools import RESEARCH_TOOL_NAMES, register_research_tools
from friday.integrations.store import IntegrationStore
from friday.memory.store import MemoryStore
from friday.os_adapters.types import OsAdapter
from friday.providers.types import VisionProvider, project_root
from friday.tools.actions import LegacyActions
from friday.tools.registry import FunctionTool, InvokePolicy, ToolRegistry
from friday.tools.types import (
    PermissionLevel,
    RiskLevel,
    ToolContext,
    ToolResult,
    ToolSpec,
)

APPS_OPEN = "apps.open"
MEDIA_YOUTUBE_PLAY = "media.youtube_play"
CONTACTS_LOOKUP = "contacts.lookup"
COMMS_WHATSAPP_MESSAGE = "comms.whatsapp_message"
COMMS_WHATSAPP_CALL = "comms.whatsapp_call"
LLM_CHAT = "llm.chat"
SESSION_STOP = "session.stop"

REGISTERED_TOOL_NAMES = (
    APPS_OPEN,
    MEDIA_YOUTUBE_PLAY,
    CONTACTS_LOOKUP,
    COMMS_WHATSAPP_MESSAGE,
    COMMS_WHATSAPP_CALL,
    LLM_CHAT,
    SESSION_STOP,
    *OS_TOOL_NAMES,
    *MEDIA_TOOL_NAMES,
    *BROWSER_TOOL_NAMES,
    *VISION_TOOL_NAMES,
    *MEMORY_TOOL_NAMES,
    *FILE_TOOL_NAMES,
    *CODE_TOOL_NAMES,
    *PRODUCTIVITY_TOOL_NAMES,
    *INTEGRATION_TOOL_NAMES,
    *WEATHER_TOOL_NAMES,
    *NEWS_TOOL_NAMES,
    *RESEARCH_TOOL_NAMES,
)


def _query_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
                "description": "Full user utterance for this command",
            }
        },
    }


def _ok_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
        },
    }


def build_legacy_registry(
    actions: LegacyActions,
    policy: InvokePolicy | None = None,
    os_adapter: OsAdapter | None = None,
    browser: BrowserDriver | None = None,
    vision: VisionProvider | None = None,
    memory: MemoryStore | None = None,
    integration_transport: Any = None,
    open_browser: Any = None,
) -> ToolRegistry:
    registry = ToolRegistry(policy=policy, memory=memory)
    registry.register(_open_tool(actions))
    registry.register(_youtube_tool(actions))
    registry.register(_contacts_tool(actions))
    registry.register(_whatsapp_message_tool(actions))
    registry.register(_whatsapp_call_tool(actions))
    registry.register(_chat_tool(actions))
    registry.register(_stop_tool())
    register_os_tools(registry, os_adapter)
    register_media_tools(registry, os_adapter)
    register_browser_tools(registry, browser)
    register_vision_tools(registry, os_adapter, vision)
    register_memory_tools(registry, memory)
    extra_allow = (Path(memory.db_path).parent,) if memory is not None else ()
    register_file_tools(registry, extra_allow=extra_allow)
    code_workspace = None
    if extra_allow:
        db_parent = extra_allow[0].resolve()
        if db_parent != project_root().resolve():
            code_workspace = db_parent
        else:
            code_workspace = workspace_root()
    register_code_tools(registry, workspace=code_workspace)
    register_productivity_tools(registry, memory)
    integrations = IntegrationStore(memory.db_path) if memory is not None else None
    register_integration_tools(
        registry,
        integrations,
        transport=integration_transport,
        open_browser=open_browser,
    )
    register_weather_tools(registry)
    register_news_tools(registry)
    register_research_tools(registry, browser=browser, memory=memory)
    return registry


def _open_tool(actions: LegacyActions) -> FunctionTool:
    spec = ToolSpec(
        name=APPS_OPEN,
        description="Open a local application, file, or bookmarked website.",
        agent="system",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema=_query_schema(),
        output_schema=_ok_schema(),
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        opened = actions.open_app(arguments["query"])
        if opened is False:
            return ToolResult(
                ok=False,
                data={"ok": False},
                observation="open_failed",
            )
        return ToolResult(ok=True, data={"ok": True})

    return FunctionTool(spec, execute)


def _youtube_tool(actions: LegacyActions) -> FunctionTool:
    spec = ToolSpec(
        name=MEDIA_YOUTUBE_PLAY,
        description="Play a YouTube search result from a 'play … on youtube' request.",
        agent="system",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema=_query_schema(),
        output_schema=_ok_schema(),
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        actions.play_youtube(arguments["query"])
        return ToolResult(ok=True, data={"ok": True})

    return FunctionTool(spec, execute)


def _contacts_tool(actions: LegacyActions) -> FunctionTool:
    spec = ToolSpec(
        name=CONTACTS_LOOKUP,
        description="Look up a contact name from the local Friday address book.",
        agent="communication",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema=_query_schema(),
        output_schema={
            "type": "object",
            "properties": {
                "found": {"type": "boolean"},
                "name": {"type": "string"},
                "mobile_no": {"type": "string"},
                "inline_message": {"type": "string"},
            },
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        query = arguments["query"]
        contact_no, name = actions.find_contact(query)
        if contact_no == 0:
            return ToolResult(
                ok=False,
                data={"found": False},
                observation="contact_not_found",
            )
        from engine.config import ASSISTANT_NAME
        from engine.helper import message_after_contact

        return ToolResult(
            ok=True,
            data={
                "found": True,
                "mobile_no": str(contact_no),
                "name": str(name),
                "inline_message": message_after_contact(
                    query, str(name), extra_words={ASSISTANT_NAME}
                ),
            },
        )

    return FunctionTool(spec, execute)


def _whatsapp_message_tool(actions: LegacyActions) -> FunctionTool:
    spec = ToolSpec(
        name=COMMS_WHATSAPP_MESSAGE,
        description="Send a WhatsApp message to a resolved phone number.",
        agent="communication",
        risk_level=RiskLevel.HIGH,
        permission_level=PermissionLevel.SEND,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["mobile_no", "name", "message"],
            "properties": {
                "mobile_no": {"type": "string", "minLength": 1},
                "name": {"type": "string", "minLength": 1},
                "message": {"type": "string", "minLength": 1},
            },
        },
        output_schema=_ok_schema(),
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        sent = actions.whatsapp(
            mobile_no=arguments["mobile_no"],
            message=arguments["message"],
            flag="message",
            name=arguments["name"],
        )
        return ToolResult(
            ok=bool(sent),
            data={"ok": bool(sent)},
            observation="ok" if sent else "whatsapp_failed",
        )

    return FunctionTool(spec, execute)


def _whatsapp_call_tool(actions: LegacyActions) -> FunctionTool:
    spec = ToolSpec(
        name=COMMS_WHATSAPP_CALL,
        description="Start a WhatsApp voice or video call to a resolved phone number.",
        agent="communication",
        risk_level=RiskLevel.HIGH,
        permission_level=PermissionLevel.SEND,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["mobile_no", "name", "mode"],
            "properties": {
                "mobile_no": {"type": "string", "minLength": 1},
                "name": {"type": "string", "minLength": 1},
                "mode": {"type": "string", "enum": ["voice", "video"]},
            },
        },
        output_schema=_ok_schema(),
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        flag = "video" if arguments["mode"] == "video" else "call"
        started = actions.whatsapp(
            mobile_no=arguments["mobile_no"],
            message="",
            flag=flag,
            name=arguments["name"],
        )
        return ToolResult(
            ok=bool(started),
            data={"ok": bool(started)},
            observation="ok" if started else "whatsapp_failed",
        )

    return FunctionTool(spec, execute)


def _chat_tool(actions: LegacyActions) -> FunctionTool:
    spec = ToolSpec(
        name=LLM_CHAT,
        description="Answer a general question with the configured chat model.",
        agent="conversation",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema=_query_schema(),
        output_schema={
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
            },
        },
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        reply = actions.chatbot(arguments["query"])
        return ToolResult(ok=True, data={"reply": reply})

    return FunctionTool(spec, execute)


def _stop_tool() -> FunctionTool:
    spec = ToolSpec(
        name=SESSION_STOP,
        description="Stop the continuous voice-control listening loop.",
        agent="system",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.SESSION,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
        output_schema={
            "type": "object",
            "properties": {
                "stopped": {"type": "boolean"},
            },
        },
    )

    def execute(_arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        return ToolResult(
            ok=True,
            data={"stopped": True},
            observation="stopped",
        )

    return FunctionTool(spec, execute)
