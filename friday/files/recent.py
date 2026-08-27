"""Remember the last file Friday wrote so 'show me the file' has a target."""

from __future__ import annotations

from pathlib import Path

_last: Path | None = None


def remember_file(path: Path | str) -> Path:
    global _last
    saved = Path(path)
    _last = saved
    return saved


def last_file() -> Path | None:
    return _last


def clear_last_file() -> None:
    global _last
    _last = None
