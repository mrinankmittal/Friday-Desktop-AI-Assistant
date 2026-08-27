from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    pid: int | None = None


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str


class OsAdapter(Protocol):
    """Laptop control surface. Windows implements this; tests use a fake."""

    def open_path(self, path: str) -> None: ...

    def open_url(self, url: str) -> bool: ...

    def list_windows(self) -> list[WindowInfo]: ...

    def focus_window(self, title: str) -> bool: ...

    def list_processes(self) -> list[ProcessInfo]: ...

    def screenshot(self, dest: Path | None = None) -> Path: ...

    def latest_screenshot(self) -> Path | None: ...

    def get_clipboard(self) -> str: ...

    def set_clipboard(self, text: str) -> None: ...

    def media_control(self, action: str) -> None: ...

    def press_hotkey(self, keys: tuple[str, ...]) -> None: ...

    def type_text(self, text: str) -> None: ...
