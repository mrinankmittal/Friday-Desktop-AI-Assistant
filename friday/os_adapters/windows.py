from __future__ import annotations

import csv
import ctypes
import io
import os
import subprocess
import sys
import webbrowser
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from friday.os_adapters.types import ProcessInfo, WindowInfo

_CREATE_NO_WINDOW = 0x08000000
_SW_RESTORE = 9
_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
_SKIP_WINDOW_TITLES = frozenset({"", "program manager"})

# Virtual-key codes for the keyboard's media transport keys. Windows routes
# these to whichever app owns the current media session (Spotify, a browser
# playing YouTube, etc.), which is exactly what "play/pause/next" should do.
_KEYEVENTF_EXTENDEDKEY = 0x0001
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_INPUT_KEYBOARD = 1
_MEDIA_VK = {
    "play_pause": 0xB3,
    "next": 0xB0,
    "previous": 0xB1,
    "stop": 0xB2,
}
_HOTKEY_VK = {
    "ctrl": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "win": 0x5B,
    "tab": 0x09,
    "enter": 0x0D,
    "escape": 0x1B,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}


class _KeyBdInput(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    )


class _MouseInput(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    )


class _HardwareInput(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class _InputUnion(ctypes.Union):
    _fields_ = (("ki", _KeyBdInput), ("mi", _MouseInput), ("hi", _HardwareInput))


class _Input(ctypes.Structure):
    _anonymous_ = ("i",)
    _fields_ = (("type", wintypes.DWORD), ("i", _InputUnion))


def _vk_for(key: str) -> int:
    token = key.strip().lower()
    if token in _HOTKEY_VK:
        return _HOTKEY_VK[token]
    if len(token) == 1 and token.isalnum():
        return ord(token.upper())
    raise ValueError(f"Unknown key: {key!r}")


def _send_unicode(text: str) -> None:
    events: list[_Input] = []
    extra = ctypes.c_void_p(0)
    for char in text.replace("\r\n", "\n"):
        code = ord(char)
        if char == "\n":
            code = 0x0D
            for flags in (0, _KEYEVENTF_KEYUP):
                events.append(
                    _Input(
                        type=_INPUT_KEYBOARD,
                        ki=_KeyBdInput(wVk=code, wScan=0, dwFlags=flags, time=0, dwExtraInfo=extra),
                    )
                )
            continue
        for flags in (_KEYEVENTF_UNICODE, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP):
            events.append(
                _Input(
                    type=_INPUT_KEYBOARD,
                    ki=_KeyBdInput(wVk=0, wScan=code, dwFlags=flags, time=0, dwExtraInfo=extra),
                )
            )
    if not events:
        return
    array = (_Input * len(events))(*events)
    sent = _user32.SendInput(len(events), array, ctypes.sizeof(_Input))
    if sent != len(events):
        raise OSError("Could not type that text.")

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_user32.OpenClipboard.argtypes = [wintypes.HWND]
_user32.OpenClipboard.restype = wintypes.BOOL
_user32.EmptyClipboard.argtypes = []
_user32.EmptyClipboard.restype = wintypes.BOOL
_user32.CloseClipboard.argtypes = []
_user32.CloseClipboard.restype = wintypes.BOOL
_user32.GetClipboardData.argtypes = [wintypes.UINT]
_user32.GetClipboardData.restype = ctypes.c_void_p
_user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
_user32.SetClipboardData.restype = ctypes.c_void_p
_kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_kernel32.GlobalAlloc.restype = ctypes.c_void_p
_kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
_kernel32.GlobalUnlock.restype = wintypes.BOOL
_kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
_kernel32.GlobalFree.restype = ctypes.c_void_p
_user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int]
_user32.SendInput.restype = wintypes.UINT
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_user32.AttachThreadInput.restype = wintypes.BOOL
_user32.BringWindowToTop.argtypes = [wintypes.HWND]
_user32.BringWindowToTop.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL


def _bring_to_front(hwnd: int) -> bool:
    """Focus a window even when Windows blocks a normal SetForegroundWindow."""
    foreground = _user32.GetForegroundWindow()
    current = _kernel32.GetCurrentThreadId()
    ignored = wintypes.DWORD()
    other = _user32.GetWindowThreadProcessId(foreground, ctypes.byref(ignored))
    target = _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(ignored))
    attached_other = bool(other and other != current and _user32.AttachThreadInput(current, other, True))
    attached_target = bool(
        target and target != current and target != other
        and _user32.AttachThreadInput(current, target, True)
    )
    try:
        _user32.ShowWindow(hwnd, _SW_RESTORE)
        _user32.keybd_event(0x12, 0, 0, 0)
        _user32.keybd_event(0x12, 0, _KEYEVENTF_KEYUP, 0)
        _user32.BringWindowToTop(hwnd)
        ok = bool(_user32.SetForegroundWindow(hwnd))
        return ok or int(_user32.GetForegroundWindow()) == int(hwnd)
    finally:
        if attached_target:
            _user32.AttachThreadInput(current, target, False)
        if attached_other:
            _user32.AttachThreadInput(current, other, False)


def screenshot_directory() -> Path:
    folder = Path.home() / "Pictures" / "Friday"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


class WindowsAdapter:
    """Win32 laptop control: open, windows, processes, screenshot, clipboard."""

    def open_path(self, path: str) -> None:
        os.startfile(path)  # type: ignore[attr-defined]

    def media_control(self, action: str) -> None:
        virtual_key = _MEDIA_VK.get(action)
        if virtual_key is None:
            raise ValueError(f"Unknown media action: {action!r}")
        _user32.keybd_event(virtual_key, 0, _KEYEVENTF_EXTENDEDKEY, 0)
        _user32.keybd_event(
            virtual_key, 0, _KEYEVENTF_EXTENDEDKEY | _KEYEVENTF_KEYUP, 0
        )

    def press_hotkey(self, keys: tuple[str, ...]) -> None:
        codes = [_vk_for(key) for key in keys]
        if not codes:
            raise ValueError("No keys to press.")
        for code in codes:
            _user32.keybd_event(code, 0, 0, 0)
        for code in reversed(codes):
            _user32.keybd_event(code, 0, _KEYEVENTF_KEYUP, 0)

    def type_text(self, text: str) -> None:
        payload = str(text)
        if not payload:
            raise ValueError("Nothing to type.")
        _send_unicode(payload)

    def open_url(self, url: str) -> bool:
        return bool(webbrowser.open(url))

    def list_windows(self) -> list[WindowInfo]:
        user32 = ctypes.windll.user32
        windows: list[WindowInfo] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = int(user32.GetWindowTextLengthW(hwnd))
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            if title.lower() in _SKIP_WINDOW_TITLES:
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            windows.append(WindowInfo(handle=int(hwnd), title=title, pid=int(pid.value)))
            return True

        user32.EnumWindows(callback, 0)
        return windows

    def focus_window(self, title: str) -> bool:
        needle = title.strip().casefold()
        if not needle:
            return False
        for window in self.list_windows():
            if needle in window.title.casefold():
                return _bring_to_front(window.handle)
        return False

    def list_processes(self) -> list[ProcessInfo]:
        output = subprocess.check_output(
            ["tasklist", "/fo", "csv", "/nh"],
            creationflags=_CREATE_NO_WINDOW,
            stderr=subprocess.DEVNULL,
        )
        text = output.decode(sys.getfilesystemencoding(), errors="replace")
        processes: list[ProcessInfo] = []
        reader = csv.reader(io.StringIO(text))
        for row in reader:
            if len(row) < 2:
                continue
            name = row[0].strip()
            pid_text = row[1].strip()
            if not name or not pid_text.isdigit():
                continue
            processes.append(ProcessInfo(pid=int(pid_text), name=name))
        return processes

    def screenshot(self, dest: Path | None = None) -> Path:
        path = dest or screenshot_directory() / (
            f"friday-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from PIL import ImageGrab
        except ImportError as error:
            raise RuntimeError(
                "Screenshot needs Pillow (PIL). It is already used by pywhatkit."
            ) from error
        image = ImageGrab.grab()
        image.save(path)
        return path

    def latest_screenshot(self) -> Path | None:
        folder = screenshot_directory()
        files = [
            path
            for path in folder.glob("friday-*.png")
            if path.is_file()
        ]
        if not files:
            return None
        return max(files, key=lambda path: path.stat().st_mtime)

    def get_clipboard(self) -> str:
        if not _user32.OpenClipboard(None):
            return ""
        try:
            handle = _user32.GetClipboardData(_CF_UNICODETEXT)
            if not handle:
                return ""
            locked = _kernel32.GlobalLock(handle)
            if not locked:
                return ""
            try:
                return ctypes.wstring_at(locked)
            finally:
                _kernel32.GlobalUnlock(handle)
        finally:
            _user32.CloseClipboard()

    def set_clipboard(self, text: str) -> None:
        payload = str(text)
        encoded = payload.encode("utf-16-le") + b"\x00\x00"
        handle = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(encoded))
        if not handle:
            raise OSError("Could not allocate clipboard memory.")
        locked = _kernel32.GlobalLock(handle)
        if not locked:
            _kernel32.GlobalFree(handle)
            raise OSError("Could not lock clipboard memory.")
        try:
            ctypes.memmove(locked, encoded, len(encoded))
        finally:
            _kernel32.GlobalUnlock(handle)

        if not _user32.OpenClipboard(None):
            _kernel32.GlobalFree(handle)
            raise OSError("Could not open the clipboard.")
        try:
            _user32.EmptyClipboard()
            if not _user32.SetClipboardData(_CF_UNICODETEXT, handle):
                _kernel32.GlobalFree(handle)
                raise OSError("Could not set clipboard text.")
        finally:
            _user32.CloseClipboard()
