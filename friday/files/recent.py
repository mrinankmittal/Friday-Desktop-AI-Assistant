"""Remember the last file or folder Friday created for follow-up commands."""

from __future__ import annotations

from pathlib import Path

_last: Path | None = None


def remember_file(path: Path | str) -> Path:
    global _last
    saved = Path(path)
    _last = saved
    return saved


def remember_folder(path: Path | str) -> Path:
    """Remember a created folder for a later ``open it`` command."""
    return remember_file(path)


def last_file() -> Path | None:
    return _last


def clear_last_file() -> None:
    global _last
    _last = None
