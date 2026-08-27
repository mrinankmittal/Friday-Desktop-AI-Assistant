"""Follow-up confirm for sends. Nested mic listen fights TTS and misses 'yes'."""

from __future__ import annotations

import time
from dataclasses import dataclass

from friday.security.ui import hide_confirm_prompt, show_confirm_prompt


@dataclass
class PendingSend:
    kind: str
    to: str = ""
    body: str = ""
    subject: str = ""
    channel: str = ""
    target: str = ""
    mobile_no: str = ""
    name: str = ""
    mode: str = ""
    created: float = 0.0


_TTL_SEC = 180.0
_pending: PendingSend | None = None


def set_pending(item: PendingSend, *, prompt: str = "") -> PendingSend:
    global _pending
    item.created = time.monotonic()
    _pending = item
    if prompt.strip():
        show_confirm_prompt(prompt)
    return item


def get_pending() -> PendingSend | None:
    global _pending
    if _pending is None:
        return None
    if time.monotonic() - _pending.created > _TTL_SEC:
        _pending = None
        hide_confirm_prompt()
        return None
    return _pending


def clear_pending() -> None:
    global _pending
    _pending = None
    hide_confirm_prompt()
