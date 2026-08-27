from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Side effect: load `.env` the same way voice providers do.
from friday.providers import settings as _voice_settings  # noqa: F401
from friday.providers.types import project_root

PROFILE_DIR_NAME = ".edge-profile"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _falsy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"0", "false", "no", "off"}


def default_profile_dir() -> Path:
    """Where the signed-in browser profile lives.

    Deliberately not under TEMP: the whole point is that a login survives a
    reboot, and Windows clears TEMP.
    """
    configured = os.environ.get("FRIDAY_BROWSER_PROFILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return project_root() / PROFILE_DIR_NAME


@dataclass(frozen=True)
class BrowserSettings:
    provider: str = "auto"
    headless: bool = False
    timeout_ms: int = 20000
    persist: bool = True
    profile_dir: Path | None = None

    @classmethod
    def from_env(cls) -> BrowserSettings:
        timeout_raw = os.environ.get("FRIDAY_BROWSER_TIMEOUT_MS", "20000").strip()
        try:
            timeout_ms = int(timeout_raw or "20000")
        except ValueError:
            timeout_ms = 20000
        return cls(
            provider=os.environ.get("FRIDAY_BROWSER_PROVIDER", "auto").strip().lower()
            or "auto",
            headless=_truthy(os.environ.get("FRIDAY_BROWSER_HEADLESS")),
            timeout_ms=max(5000, timeout_ms),
            persist=not _falsy(os.environ.get("FRIDAY_BROWSER_PERSIST")),
            profile_dir=default_profile_dir(),
        )
