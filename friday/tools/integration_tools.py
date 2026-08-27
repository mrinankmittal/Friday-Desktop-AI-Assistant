"""Email / Slack / Discord tools. Sends are high-risk and must be confirmed."""

from __future__ import annotations

import webbrowser
from typing import Any

from friday.integrations.address import (
    gmail_app_password_reply,
    gmail_setup_reply,
    user_email,
)
from friday.integrations.oauth import (
    begin_oauth,
    client_id_for,
    client_secret_for,
    env_authorized_secrets,
)
from friday.integrations.send import list_gmail, send_discord, send_gmail, send_slack
from friday.integrations.settings import IntegrationSettings, is_gmail_app_password
from friday.integrations.store import PROVIDERS, IntegrationStore, canonical_provider
from friday.memory import get_memory_store
from friday.tools.registry import FunctionTool, ToolRegistry
from friday.tools.types import (
    PermissionLevel,
    RiskLevel,
    ToolContext,
    ToolResult,
    ToolSpec,
)

INTEGRATIONS_STATUS = "integrations.status"
INTEGRATIONS_CONNECT = "integrations.connect"
INTEGRATIONS_DISCONNECT = "integrations.disconnect"
EMAIL_SEND = "email.send"
EMAIL_LIST = "email.list"
SLACK_SEND = "slack.send"
DISCORD_SEND = "discord.send"

INTEGRATION_TOOL_NAMES = (
    INTEGRATIONS_STATUS,
    INTEGRATIONS_CONNECT,
    INTEGRATIONS_DISCONNECT,
    EMAIL_SEND,
    EMAIL_LIST,
    SLACK_SEND,
    DISCORD_SEND,
)


def register_integration_tools(
    registry: ToolRegistry,
    store: IntegrationStore | None = None,
    transport: Any = None,
    open_browser: Any = None,
) -> None:
    integrations = store
    if integrations is None:
        integrations = IntegrationStore(get_memory_store().db_path)
    registry.register(_status_tool(integrations))
    registry.register(_connect_tool(integrations, open_browser=open_browser))
    registry.register(_disconnect_tool(integrations))
    registry.register(_email_send_tool(integrations, transport))
    registry.register(_email_list_tool(integrations, transport))
    registry.register(_slack_send_tool(integrations, transport))
    registry.register(_discord_send_tool(integrations, transport))


def format_status(store: IntegrationStore) -> str:
    parts: list[str] = []
    for item in store.list():
        state = "connected" if store.is_connected(item.provider) else "not connected"
        parts.append(f"{item.provider} is {state}")
    return "Integrations: " + "; ".join(parts) + "."


def _status_tool(store: IntegrationStore) -> FunctionTool:
    spec = ToolSpec(
        name=INTEGRATIONS_STATUS,
        description="List whether Gmail, Slack, and Discord are connected.",
        agent="communication",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={"type": "object", "additionalProperties": False, "properties": {}},
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(_arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        reply = format_status(store)
        return ToolResult(ok=True, data={"reply": reply})

    return FunctionTool(spec, execute)


def _connect_tool(store: IntegrationStore, open_browser: Any = None) -> FunctionTool:
    spec = ToolSpec(
        name=INTEGRATIONS_CONNECT,
        description="Connect Gmail, Slack, or Discord with OAuth or an authorized token.",
        agent="communication",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["provider"],
            "properties": {"provider": {"type": "string", "minLength": 1}},
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        provider = canonical_provider(str(arguments["provider"]))
        if provider not in PROVIDERS:
            return ToolResult(
                ok=False,
                data={"reply": "I can connect gmail, slack, or discord."},
                observation="error",
            )
        settings = IntegrationSettings.from_env()
        env_secrets = env_authorized_secrets(provider, settings)
        if env_secrets:
            store.save(provider, env_secrets, label="env")
            reply = f"{provider} is connected."
            if provider == "gmail":
                reply = f"Gmail is connected as {settings.user_email or 'your account'}."
            return ToolResult(ok=True, data={"reply": reply})
        if provider == "gmail" and settings.gmail_app_password:
            return ToolResult(
                ok=False,
                data={"reply": gmail_app_password_reply()},
                observation="invalid_app_password",
            )
        has_oauth = bool(
            client_id_for(provider, settings) and client_secret_for(provider, settings)
        )
        if provider == "gmail" and not has_oauth:
            return ToolResult(
                ok=False,
                data={"reply": gmail_setup_reply(settings)},
                observation="missing_oauth",
            )
        if not has_oauth:
            env_name = {
                "gmail": "FRIDAY_GOOGLE_CLIENT_ID",
                "slack": "FRIDAY_SLACK_CLIENT_ID",
                "discord": "FRIDAY_DISCORD_CLIENT_ID",
            }[provider]
            reply = (
                f"{provider} is not configured. Add {env_name} and the matching secret "
                "to .env, then say connect "
                f"{provider} again."
            )
            return ToolResult(ok=False, data={"reply": reply}, observation="missing_oauth")
        try:
            opener = open_browser if open_browser is not None else webbrowser.open
            url = begin_oauth(
                provider,
                store,
                settings=settings,
                open_browser=opener,
            )
        except Exception as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        reply = (
            f"Sign in to {provider} in the browser. I'll finish connecting when you allow access. "
            f"Redirect is {url.split('?', 1)[0]}."
        )
        return ToolResult(ok=True, data={"reply": reply, "authorize_url": url})

    return FunctionTool(spec, execute)


def _disconnect_tool(store: IntegrationStore) -> FunctionTool:
    spec = ToolSpec(
        name=INTEGRATIONS_DISCONNECT,
        description="Forget stored OAuth tokens for Gmail, Slack, or Discord.",
        agent="communication",
        risk_level=RiskLevel.MEDIUM,
        permission_level=PermissionLevel.LOCAL_APP,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["provider"],
            "properties": {"provider": {"type": "string", "minLength": 1}},
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        provider = canonical_provider(str(arguments["provider"]))
        store.delete(provider)
        return ToolResult(ok=True, data={"reply": f"{provider} is disconnected."})

    return FunctionTool(spec, execute)


def _email_send_tool(store: IntegrationStore, transport: Any) -> FunctionTool:
    spec = ToolSpec(
        name=EMAIL_SEND,
        description="Send a Gmail message after the user confirms.",
        agent="communication",
        risk_level=RiskLevel.HIGH,
        permission_level=PermissionLevel.SEND,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["to", "body"],
            "properties": {
                "to": {"type": "string", "minLength": 1},
                "body": {"type": "string", "minLength": 1},
                "subject": {"type": "string"},
            },
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        if not context.confirmed:
            return ToolResult(
                ok=False,
                data={"reply": "I didn't send that email because it wasn't confirmed."},
                observation="confirm_required",
            )
        if not store.is_connected("gmail"):
            return ToolResult(
                ok=False,
                data={"reply": gmail_setup_reply()},
                observation="disconnected",
            )
        to = str(arguments["to"]).strip()
        if "@" not in to:
            return ToolResult(
                ok=False,
                data={
                    "reply": "I need a full email address, like name@example.com.",
                },
                observation="invalid_to",
            )
        secrets = dict(store.secrets_for("gmail"))
        env_secrets = env_authorized_secrets("gmail")
        if env_secrets:
            secrets.update(env_secrets)
        smtp_password = str(secrets.get("smtp_password") or "")
        if smtp_password and not is_gmail_app_password(smtp_password):
            return ToolResult(
                ok=False,
                data={"reply": gmail_app_password_reply()},
                observation="invalid_app_password",
            )
        try:
            reply = send_gmail(
                access_token=str(secrets.get("access_token") or ""),
                smtp_user=str(secrets.get("smtp_user") or secrets.get("from") or ""),
                smtp_password=smtp_password,
                to=to,
                subject=str(arguments.get("subject") or ""),
                body=str(arguments["body"]),
                transport=transport,
            )
        except (PermissionError, RuntimeError, OSError) as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        return ToolResult(ok=True, data={"reply": reply})

    return FunctionTool(spec, execute)


def _email_list_tool(store: IntegrationStore, transport: Any) -> FunctionTool:
    spec = ToolSpec(
        name=EMAIL_LIST,
        description="List recent Gmail subjects.",
        agent="communication",
        risk_level=RiskLevel.LOW,
        permission_level=PermissionLevel.READ,
        input_schema={"type": "object", "additionalProperties": False, "properties": {}},
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(_arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
        if not store.is_connected("gmail"):
            return ToolResult(
                ok=False,
                data={"reply": gmail_setup_reply()},
                observation="disconnected",
            )
        secrets = store.secrets_for("gmail")
        token = str(secrets.get("access_token") or "")
        if not token:
            email = str(secrets.get("from") or user_email() or "your Gmail")
            return ToolResult(
                ok=True,
                data={
                    "reply": (
                        f"I can send from {email}, but reading the inbox needs Gmail "
                        "OAuth. Say send me an email to send a message."
                    )
                },
            )
        try:
            reply = list_gmail(access_token=token, transport=transport)
        except (PermissionError, RuntimeError, OSError) as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        return ToolResult(ok=True, data={"reply": reply})

    return FunctionTool(spec, execute)


def _slack_send_tool(store: IntegrationStore, transport: Any) -> FunctionTool:
    spec = ToolSpec(
        name=SLACK_SEND,
        description="Send a Slack message after the user confirms.",
        agent="communication",
        risk_level=RiskLevel.HIGH,
        permission_level=PermissionLevel.SEND,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["channel", "body"],
            "properties": {
                "channel": {"type": "string", "minLength": 1},
                "body": {"type": "string", "minLength": 1},
            },
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        if not context.confirmed:
            return ToolResult(
                ok=False,
                data={"reply": "I didn't send that Slack message because it wasn't confirmed."},
                observation="confirm_required",
            )
        if not store.is_connected("slack"):
            return ToolResult(
                ok=False,
                data={"reply": "Slack is not connected. Say connect slack."},
                observation="disconnected",
            )
        token = str(store.secrets_for("slack").get("access_token") or "")
        try:
            reply = send_slack(
                access_token=token,
                channel=str(arguments["channel"]),
                body=str(arguments["body"]),
                transport=transport,
            )
        except (PermissionError, RuntimeError, OSError, ValueError) as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        return ToolResult(ok=True, data={"reply": reply})

    return FunctionTool(spec, execute)


def _discord_send_tool(store: IntegrationStore, transport: Any) -> FunctionTool:
    spec = ToolSpec(
        name=DISCORD_SEND,
        description="Send a Discord webhook message after the user confirms.",
        agent="communication",
        risk_level=RiskLevel.HIGH,
        permission_level=PermissionLevel.SEND,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["body"],
            "properties": {
                "body": {"type": "string", "minLength": 1},
                "target": {"type": "string"},
            },
        },
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}}},
    )

    def execute(arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        if not context.confirmed:
            return ToolResult(
                ok=False,
                data={"reply": "I didn't send that Discord message because it wasn't confirmed."},
                observation="confirm_required",
            )
        if not store.is_connected("discord"):
            return ToolResult(
                ok=False,
                data={"reply": "Discord is not connected. Say connect discord."},
                observation="disconnected",
            )
        webhook = str(store.secrets_for("discord").get("webhook_url") or "")
        if not webhook:
            return ToolResult(
                ok=False,
                data={"reply": "Discord has no webhook yet. Say connect discord."},
                observation="disconnected",
            )
        body = str(arguments["body"])
        target = str(arguments.get("target") or "").strip()
        if target:
            body = f"{target}: {body}"
        try:
            reply = send_discord(webhook_url=webhook, body=body, transport=transport)
        except (PermissionError, RuntimeError, OSError) as error:
            return ToolResult(
                ok=False,
                data={"reply": str(error)},
                observation="error",
                error=str(error),
            )
        return ToolResult(ok=True, data={"reply": reply})

    return FunctionTool(spec, execute)
