from __future__ import annotations

import hashlib
import json
from typing import Any

_REDACT_KEYS = frozenset(
    {
        "mobile_no",
        "phone",
        "message",
        "token",
        "cookie",
        "password",
        "secret",
        "authorization",
        "text",
        "clipboard",
        "content",
        "old",
        "new",
        "access_token",
        "refresh_token",
        "webhook",
        "webhook_url",
        "body",
        "to",
        "channel",
        "client_secret",
        "smtp_password",
        "smtp_user",
    }
)


def redact_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Copy tool arguments with secrets and message bodies removed."""
    redacted: dict[str, Any] = {}
    for key, value in arguments.items():
        if str(key).lower() in _REDACT_KEYS:
            redacted[key] = "<redacted>"
        else:
            redacted[key] = value
    return redacted


def hash_arguments(arguments: dict[str, Any]) -> str:
    """Stable digest of the real arguments. The hash is not logged with plaintext."""
    payload = json.dumps(arguments, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
