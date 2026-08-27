"""File allowlist for Settings. Tools already enforce this in friday.files."""

from __future__ import annotations

from pathlib import Path

from friday.memory.settings import MemorySettings


def list_allow_paths(settings: MemorySettings | None = None) -> list[str]:
    config = settings or MemorySettings.from_env()
    seen: list[str] = []
    for path in config.allow_paths:
        text = str(Path(path).expanduser())
        if text not in seen:
            seen.append(text)
    return seen
