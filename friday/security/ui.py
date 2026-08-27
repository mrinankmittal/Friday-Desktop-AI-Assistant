"""Best-effort confirm modal hooks. No-op when Eel is not running."""

from __future__ import annotations

import logging

logger = logging.getLogger("friday.security")


def show_confirm_prompt(prompt: str) -> None:
    message = str(prompt or "").strip()
    if not message:
        return
    try:
        import eel

        getattr(eel, "ShowConfirm")(message)
    except Exception:
        logger.debug("confirm UI unavailable", exc_info=True)


def hide_confirm_prompt() -> None:
    try:
        import eel

        getattr(eel, "HideConfirm")()
    except Exception:
        logger.debug("confirm UI unavailable", exc_info=True)
