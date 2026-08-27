"""Confirm-on-send policy from env."""

from __future__ import annotations

import os


def require_confirm_send() -> bool:
    """High-risk sends wait for yes / send it. Default on for Phase 11."""
    raw = os.environ.get("FRIDAY_REQUIRE_CONFIRM_SEND", "true").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def require_confirm_whatsapp() -> bool:
    """WhatsApp confirm. ``FRIDAY_WHATSAPP_CONFIRM`` overrides the global flag.

    Set ``FRIDAY_WHATSAPP_CONFIRM=false`` to send as soon as the message is known
    (no extra "say send it"). Unset falls back to ``FRIDAY_REQUIRE_CONFIRM_SEND``.
    """
    raw = os.environ.get("FRIDAY_WHATSAPP_CONFIRM", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return require_confirm_send()
