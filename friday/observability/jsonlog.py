"""Structured JSON events with task_id. No tokens or message bodies."""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("friday.events")

_MAX_BUFFER = 150
_MAX_REQUEST = 120
_MAX_OBS = 200
_buffer: deque[dict[str, Any]] = deque(maxlen=_MAX_BUFFER)

_DROP_KEYS = frozenset(
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
        "arguments",
    }
)

_REDACTED = "<redacted>"
_PHONE_RUN = re.compile(r"\d{7,}")

# "send message to papa hello from friday" keeps the command and the contact,
# and drops the sentence the user actually wanted delivered.
_BODY_AFTER_TARGET = re.compile(
    r"^(?P<head>.*?\b(?:message|msg|text|whatsapp|whats\s?app|dm|mail|email)"
    r"\s+to\s+\S+)\s+(?P<body>.+)$",
    re.IGNORECASE,
)
_BODY_AFTER_MARKER = re.compile(
    r"^(?P<head>.*?\b(?:saying|that says|with the message)\b)\s+(?P<body>.+)$",
    re.IGNORECASE,
)
_BODY_AFTER_CLIPBOARD = re.compile(
    r"^(?P<head>.*?\bclipboard\b)\s+(?P<body>.+)$",
    re.IGNORECASE,
)
_BODY_PATTERNS = (_BODY_AFTER_TARGET, _BODY_AFTER_MARKER, _BODY_AFTER_CLIPBOARD)


def scrub_request(value: Any) -> Any:
    """Keep the shape of an utterance for tracing, drop what reads like a body.

    The developer log needs to show which command ran. It must not become a
    transcript of the messages that command sent.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return text
    for pattern in _BODY_PATTERNS:
        match = pattern.match(text)
        if match:
            text = f"{match.group('head')} {_REDACTED}"
            break
    return _PHONE_RUN.sub(_REDACTED, text)


def emit(
    event: str,
    *,
    task_id: str = "",
    store: Any = None,
    log: bool = True,
    **fields: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ts": _utc_now(),
        "event": str(event or "event"),
        "task_id": str(task_id or ""),
    }
    for key, value in fields.items():
        lowered = str(key).lower()
        if lowered in _DROP_KEYS:
            continue
        if lowered == "observation" and isinstance(value, str) and len(value) > _MAX_OBS:
            payload[key] = value[:_MAX_OBS]
            continue
        if lowered == "request":
            payload[key] = _clip(scrub_request(value))
            continue
        payload[key] = _clip(value)
    if log:
        logger.info(json.dumps(payload, default=str, sort_keys=True))
    _buffer.appendleft(payload)
    if store is not None:
        try:
            store.record_event(
                event=str(payload["event"]),
                task_id=str(payload.get("task_id") or ""),
                intent=str(payload.get("intent") or ""),
                tool=str(payload.get("tool") or ""),
                tools=_tools_text(payload.get("tools")),
                status=str(payload.get("status") or ""),
                observation=str(payload.get("observation") or "")[:_MAX_OBS],
                error=str(payload.get("error") or "")[:300],
                duration_ms=_int_or_none(payload.get("duration_ms")),
                request=str(payload.get("request") or "")[:_MAX_REQUEST],
            )
        except Exception:
            logger.exception("event persist failed")
    return payload


def recent_events(limit: int = 50) -> list[dict[str, Any]]:
    capped = max(1, min(int(limit), _MAX_BUFFER))
    return list(_buffer)[:capped]


def clear_events() -> None:
    _buffer.clear()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_REQUEST:
        return value[:_MAX_REQUEST]
    if isinstance(value, list):
        return [str(item) for item in value[:12]]
    return value


def _tools_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ",".join(str(item) for item in value[:12])
    return str(value)


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
