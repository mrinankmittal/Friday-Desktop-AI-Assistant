from __future__ import annotations

from pathlib import Path

from friday.os_adapters.types import OsAdapter, ProcessInfo, WindowInfo


class FakeOsAdapter:
    """In-memory adapter for tests. Does not touch the real desktop."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.windows: list[WindowInfo] = [
            WindowInfo(handle=1, title="Google Chrome", pid=100),
            WindowInfo(handle=2, title="Notepad", pid=101),
        ]
        self.processes: list[ProcessInfo] = [
            ProcessInfo(pid=100, name="chrome.exe"),
            ProcessInfo(pid=101, name="notepad.exe"),
            ProcessInfo(pid=102, name="chrome.exe"),
        ]
        self.clipboard = "copied text"
        self.open_url_ok = True
        self.focus_ok = True
        self.screenshot_path = Path("friday-test-screenshot.png")
        self.last_saved: Path | None = None

    def open_path(self, path: str) -> None:
        self.calls.append(("open_path", path))

    def open_url(self, url: str) -> bool:
        self.calls.append(("open_url", url))
        return self.open_url_ok

    def list_windows(self) -> list[WindowInfo]:
        self.calls.append(("list_windows",))
        return list(self.windows)

    def focus_window(self, title: str) -> bool:
        self.calls.append(("focus_window", title))
        return self.focus_ok

    def list_processes(self) -> list[ProcessInfo]:
        self.calls.append(("list_processes",))
        return list(self.processes)

    def screenshot(self, dest: Path | None = None) -> Path:
        path = dest or self.screenshot_path
        self.calls.append(("screenshot", str(path)))
        self.last_saved = path
        return path

    def latest_screenshot(self) -> Path | None:
        self.calls.append(("latest_screenshot",))
        return self.last_saved

    def get_clipboard(self) -> str:
        self.calls.append(("get_clipboard",))
        return self.clipboard

    def set_clipboard(self, text: str) -> None:
        self.calls.append(("set_clipboard", text))
        self.clipboard = text

    def media_control(self, action: str) -> None:
        self.calls.append(("media_control", action))

    def press_hotkey(self, keys: tuple[str, ...]) -> None:
        self.calls.append(("press_hotkey", keys))

    def type_text(self, text: str) -> None:
        self.calls.append(("type_text", text))
