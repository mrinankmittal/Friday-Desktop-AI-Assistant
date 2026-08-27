from __future__ import annotations

import os
from dataclasses import dataclass

from friday.providers.settings import VoiceSettings

_ = VoiceSettings  # load .env


def normalize_gmail_app_password(raw: str) -> str:
    return (raw or "").strip().replace(" ", "")


def is_gmail_app_password(raw: str) -> bool:
    """Google app passwords are 16 letters or digits, never account passwords."""
    cleaned = normalize_gmail_app_password(raw)
    return len(cleaned) == 16 and cleaned.isalnum()


@dataclass(frozen=True)
class IntegrationSettings:
    google_client_id: str = ""
    google_client_secret: str = ""
    user_email: str = ""
    gmail_app_password: str = ""
    slack_client_id: str = ""
    slack_client_secret: str = ""
    slack_bot_token: str = ""
    discord_client_id: str = ""
    discord_client_secret: str = ""
    discord_webhook_url: str = ""
    oauth_redirect: str = "http://127.0.0.1:8765/oauth/callback"

    @classmethod
    def from_env(cls) -> IntegrationSettings:
        client_id = os.environ.get("FRIDAY_GOOGLE_CLIENT_ID", "").strip()
        user_email = os.environ.get("FRIDAY_USER_EMAIL", "").strip()
        if "@" in client_id:
            if not user_email:
                user_email = client_id
            client_id = ""
        password = normalize_gmail_app_password(
            os.environ.get("FRIDAY_GMAIL_APP_PASSWORD", "")
        )
        return cls(
            google_client_id=client_id,
            google_client_secret=os.environ.get("FRIDAY_GOOGLE_CLIENT_SECRET", "").strip(),
            user_email=user_email,
            gmail_app_password=password,
            slack_client_id=os.environ.get("FRIDAY_SLACK_CLIENT_ID", "").strip(),
            slack_client_secret=os.environ.get("FRIDAY_SLACK_CLIENT_SECRET", "").strip(),
            slack_bot_token=os.environ.get("FRIDAY_SLACK_BOT_TOKEN", "").strip(),
            discord_client_id=os.environ.get("FRIDAY_DISCORD_CLIENT_ID", "").strip(),
            discord_client_secret=os.environ.get("FRIDAY_DISCORD_CLIENT_SECRET", "").strip(),
            discord_webhook_url=os.environ.get("FRIDAY_DISCORD_WEBHOOK_URL", "").strip(),
            oauth_redirect=os.environ.get(
                "FRIDAY_OAUTH_REDIRECT",
                "http://127.0.0.1:8765/oauth/callback",
            ).strip()
            or "http://127.0.0.1:8765/oauth/callback",
        )
