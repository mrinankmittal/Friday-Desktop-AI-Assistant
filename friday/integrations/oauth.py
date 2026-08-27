"""OAuth2 authorization-code helpers. Browser loopback is optional."""

from __future__ import annotations

import logging
import secrets
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from friday.integrations.settings import IntegrationSettings, is_gmail_app_password
from friday.integrations.store import IntegrationStore

logger = logging.getLogger("friday.integrations")

OpenBrowser = Callable[[str], bool]


@dataclass(frozen=True)
class OAuthSpec:
    authorize_url: str
    token_url: str
    scopes: str
    extra_authorize: dict[str, str]


SPECS = {
    "gmail": OAuthSpec(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes="https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly",
        extra_authorize={"access_type": "offline", "prompt": "consent"},
    ),
    "slack": OAuthSpec(
        authorize_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        scopes="chat:write,channels:read",
        extra_authorize={},
    ),
    "discord": OAuthSpec(
        authorize_url="https://discord.com/api/oauth2/authorize",
        token_url="https://discord.com/api/oauth2/token",
        scopes="webhook.incoming",
        extra_authorize={},
    ),
}


def client_id_for(provider: str, settings: IntegrationSettings | None = None) -> str:
    config = settings or IntegrationSettings.from_env()
    if provider == "gmail":
        return config.google_client_id
    if provider == "slack":
        return config.slack_client_id
    if provider == "discord":
        return config.discord_client_id
    return ""


def client_secret_for(provider: str, settings: IntegrationSettings | None = None) -> str:
    config = settings or IntegrationSettings.from_env()
    if provider == "gmail":
        return config.google_client_secret
    if provider == "slack":
        return config.slack_client_secret
    if provider == "discord":
        return config.discord_client_secret
    return ""


def authorize_url(
    provider: str,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
) -> str:
    spec = SPECS[provider]
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
        "scope": spec.scopes,
    }
    if provider == "slack":
        params["user_scope"] = ""
        params["scope"] = spec.scopes
    params.update(spec.extra_authorize)
    return f"{spec.authorize_url}?{urlencode(params)}"


def exchange_code(
    provider: str,
    *,
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
    session: Any = None,
) -> dict[str, Any]:
    spec = SPECS[provider]
    http = session or requests
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    response = http.post(spec.token_url, data=payload, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("OAuth token response was not JSON.")
    if data.get("ok") is False:
        raise ValueError(str(data.get("error") or "OAuth token exchange failed."))
    return data


def secrets_from_token_response(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
    if provider == "gmail":
        return {
            "access_token": payload.get("access_token") or "",
            "refresh_token": payload.get("refresh_token") or "",
            "token_type": payload.get("token_type") or "Bearer",
        }
    if provider == "slack":
        authed = payload.get("authed_user") if isinstance(payload.get("authed_user"), dict) else {}
        return {
            "access_token": payload.get("access_token") or authed.get("access_token") or "",
            "team": (payload.get("team") or {}).get("name")
            if isinstance(payload.get("team"), dict)
            else "",
        }
    webhook = payload.get("webhook") if isinstance(payload.get("webhook"), dict) else {}
    return {
        "access_token": payload.get("access_token") or "",
        "webhook_url": webhook.get("url") or "",
        "channel": webhook.get("channel") or "",
    }


def env_authorized_secrets(
    provider: str,
    settings: IntegrationSettings | None = None,
) -> dict[str, str]:
    config = settings or IntegrationSettings.from_env()
    if provider == "gmail" and config.user_email and is_gmail_app_password(
        config.gmail_app_password
    ):
        return {
            "smtp_user": config.user_email,
            "smtp_password": config.gmail_app_password,
            "from": config.user_email,
        }
    if provider == "slack" and config.slack_bot_token:
        return {"access_token": config.slack_bot_token}
    if provider == "discord" and config.discord_webhook_url:
        return {"webhook_url": config.discord_webhook_url}
    return {}


def begin_oauth(
    provider: str,
    store: IntegrationStore,
    *,
    settings: IntegrationSettings | None = None,
    open_browser: OpenBrowser | None = webbrowser.open,
) -> str:
    """Open the provider consent page and collect the callback on localhost."""
    config = settings or IntegrationSettings.from_env()
    client_id = client_id_for(provider, config)
    client_secret = client_secret_for(provider, config)
    if not client_id or not client_secret:
        raise ValueError("OAuth client id and secret are missing.")
    state = secrets.token_urlsafe(16)
    parsed = urlparse(config.oauth_redirect)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765
    path = parsed.path or "/oauth/callback"
    url = authorize_url(
        provider,
        client_id=client_id,
        redirect_uri=config.oauth_redirect,
        state=state,
    )
    holder: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = parse_qs(urlparse(self.path).query)
            if self.path.split("?", 1)[0] != path:
                self.send_response(404)
                self.end_headers()
                return
            holder["code"] = (query.get("code") or [""])[0]
            holder["state"] = (query.get("state") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body>Friday is connected. You can close this tab.</body></html>")

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return None

    server = HTTPServer((host, port), Handler)

    def _serve() -> None:
        try:
            server.handle_request()
            if holder.get("code") and holder.get("state") == state:
                payload = exchange_code(
                    provider,
                    code=holder["code"],
                    redirect_uri=config.oauth_redirect,
                    client_id=client_id,
                    client_secret=client_secret,
                )
                store.save(provider, secrets_from_token_response(provider, payload))
            else:
                logger.warning("OAuth callback for %s did not return a code", provider)
        except Exception:
            logger.exception("OAuth loopback failed for %s", provider)
        finally:
            server.server_close()

    thread = threading.Thread(target=_serve, name=f"friday-oauth-{provider}", daemon=True)
    thread.start()
    if open_browser is not None:
        open_browser(url)
    return url
