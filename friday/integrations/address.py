"""Resolve spoken recipients like 'me' to a stored Gmail address."""

from __future__ import annotations

import re

from friday.integrations.settings import IntegrationSettings

_SELF = frozenset(
    {
        "me",
        "myself",
        "self",
        "my email",
        "my gmail",
        "my address",
        "my mail",
        "i",
    }
)
_EMAIL = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.IGNORECASE)
_LEADING_TO = re.compile(r"^to\s+")
_TRAILING_BY = re.compile(r"\s+by$")


def looks_like_email(value: str) -> bool:
    text = value.strip()
    if " " in text or "@" not in text:
        return False
    return bool(_EMAIL.fullmatch(text))


def parse_spoken_email(text: str) -> str:
    lowered = f" {text.strip().lower()} "
    lowered = lowered.replace(" at the rate ", "@")
    lowered = re.sub(r"\s+at\s+", "@", lowered)
    lowered = lowered.replace(" dot ", ".")
    compact = re.sub(r"\s+", "", lowered)
    match = _EMAIL.search(compact)
    return match.group(0).lower() if match else ""


def user_email(settings: IntegrationSettings | None = None) -> str:
    config = settings or IntegrationSettings.from_env()
    if looks_like_email(config.user_email):
        return config.user_email.strip()
    if looks_like_email(config.google_client_id):
        return config.google_client_id.strip()
    return ""


def is_self_recipient(raw: str) -> bool:
    """True for me / myself / to myself / to myself by (STT leftovers)."""
    text = " ".join(raw.strip().lower().split())
    text = _LEADING_TO.sub("", text)
    text = _TRAILING_BY.sub("", text).strip()
    return text in _SELF or text in {"to me", "to myself", "to self"}


def resolve_recipient(raw: str, *, default: str = "") -> str:
    text = " ".join(raw.strip().lower().split())
    text = _LEADING_TO.sub("", text)
    text = _TRAILING_BY.sub("", text).strip()
    fallback = default or user_email()
    if is_self_recipient(text) or text in _SELF:
        return fallback
    if looks_like_email(raw.strip()):
        return raw.strip()
    spoken = parse_spoken_email(raw)
    if spoken:
        return spoken
    return fallback if not text else raw.strip()


def gmail_app_password_reply() -> str:
    return (
        "That is not a Gmail app password. Google app passwords are 16 letters, "
        "no symbols, and they are not your normal Gmail password. Open Google Account, "
        "Security, 2-step verification, App passwords, create one named Friday, put it "
        "in .env as FRIDAY_GMAIL_APP_PASSWORD, restart Friday, then say connect gmail."
    )


def gmail_setup_reply(settings: IntegrationSettings | None = None) -> str:
    email = user_email(settings)
    if email:
        return (
            f"I know your address is {email}. To send mail, create a Gmail app password "
            "(Google Account, Security, 2-step verification, App passwords). It is 16 "
            "letters, not your normal password. Put it in .env as FRIDAY_GMAIL_APP_PASSWORD, "
            "then say connect gmail."
        )
    return (
        "Put your Gmail address in .env as FRIDAY_USER_EMAIL, then add a 16-letter Gmail "
        "app password as FRIDAY_GMAIL_APP_PASSWORD and say connect gmail. "
        "FRIDAY_GOOGLE_CLIENT_ID is a Google Cloud value, not your email address."
    )
