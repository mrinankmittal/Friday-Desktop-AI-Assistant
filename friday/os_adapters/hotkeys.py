"""Parse spoken hotkeys into an allowlisted key sequence."""

from __future__ import annotations

_MODIFIERS = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "ctl": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
    "win": "win",
    "windows": "win",
    "window": "win",
    "super": "win",
}

_KEYS = {
    "tab": "tab",
    "enter": "enter",
    "return": "enter",
    "escape": "escape",
    "esc": "escape",
    "space": "space",
    "spacebar": "space",
    "backspace": "backspace",
    "delete": "delete",
    "del": "delete",
    "left": "left",
    "right": "right",
    "up": "up",
    "down": "down",
    "home": "home",
    "end": "end",
    "pageup": "pageup",
    "pagedown": "pagedown",
    "f1": "f1",
    "f2": "f2",
    "f3": "f3",
    "f4": "f4",
    "f5": "f5",
    "f6": "f6",
    "f7": "f7",
    "f8": "f8",
    "f9": "f9",
    "f10": "f10",
    "f11": "f11",
    "f12": "f12",
}

NAMED_TASKS = {
    "copy": ("ctrl", "c"),
    "paste": ("ctrl", "v"),
    "cut": ("ctrl", "x"),
    "undo": ("ctrl", "z"),
    "redo": ("ctrl", "y"),
    "select_all": ("ctrl", "a"),
    "save": ("ctrl", "s"),
    "find": ("ctrl", "f"),
    "print": ("ctrl", "p"),
    "new_tab": ("ctrl", "t"),
    "close_tab": ("ctrl", "w"),
    "close_window": ("alt", "f4"),
    "switch_window": ("alt", "tab"),
    "show_desktop": ("win", "d"),
    "lock": ("win", "l"),
    "snap_left": ("win", "left"),
    "snap_right": ("win", "right"),
    "refresh": ("f5",),
}

_TASK_REPLIES = {
    "copy": "Copying.",
    "paste": "Pasting.",
    "cut": "Cutting.",
    "undo": "Undoing.",
    "redo": "Redoing.",
    "select_all": "Selecting all.",
    "save": "Saving.",
    "find": "Opening find.",
    "print": "Opening print.",
    "new_tab": "Opening a new tab.",
    "close_tab": "Closing the tab.",
    "close_window": "Closing the window.",
    "switch_window": "Switching windows.",
    "show_desktop": "Showing the desktop.",
    "lock": "Locking the computer.",
    "snap_left": "Snapping left.",
    "snap_right": "Snapping right.",
    "refresh": "Refreshing.",
    "hotkey": "Pressing that.",
    "type": "Typing.",
}


def task_reply(task: str) -> str:
    return _TASK_REPLIES.get(task, "Done.")


def _token(raw: str) -> str | None:
    key = raw.strip().lower()
    if not key:
        return None
    if key in _MODIFIERS:
        return _MODIFIERS[key]
    if key in _KEYS:
        return _KEYS[key]
    if len(key) == 1 and (key.isalnum()):
        return key
    return None


def parse_hotkey(spoken: str) -> tuple[str, ...] | None:
    """Turn 'control s' or 'ctrl+alt+delete' into ('ctrl', 's')."""
    text = " ".join(spoken.lower().replace("plus", "+").split())
    text = text.replace(" + ", "+").replace("+", " ")
    parts = [_token(part) for part in text.split()]
    if not parts or any(part is None for part in parts):
        return None
    keys = tuple(part for part in parts if part)
    if not keys:
        return None
    return keys


def keys_for_task(task: str, spoken_keys: str = "") -> tuple[str, ...] | None:
    if task == "hotkey":
        return parse_hotkey(spoken_keys)
    return NAMED_TASKS.get(task)
