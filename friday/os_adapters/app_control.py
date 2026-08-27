"""Open an app, focus it, then type or press keys inside it."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Any

from friday.os_adapters.apps import execute_open, lookup_open_target
from friday.os_adapters.hotkeys import NAMED_TASKS, parse_hotkey, task_reply
from friday.os_adapters.types import OsAdapter

_PREFIX = r"^(?:please |friday |can you |i want you to |i would like you to )*"
_IN_APP = re.compile(
    _PREFIX + r"(?:in|on|inside) (?:the |my )?(?P<app>.+?) (?P<rest>.+)$"
)
_ON_APP = re.compile(
    _PREFIX + r"(?P<rest>.+?) (?:in|on|inside) (?:the |my )?(?P<app>.+)$"
)
_WHATSAPP_CHAT = re.compile(
    _PREFIX + r"(?:whatsapp|whats app) (?P<name>.+)$"
)
_OPEN_AND = re.compile(
    _PREFIX
    + r"open (?:up )?(?:the |my )?(?P<app>.+?) and(?: then)? (?P<rest>.+)$"
)
_NESTED_IN_APP = re.compile(
    r"^(?:in|on|inside) (?:the |my )?(?P<app>.+?) (?P<rest>.+)$"
)
_BARE_WRITE = re.compile(
    _PREFIX + r"(?:write|type out)\s+(?P<text>.+)$"
)
_TO_FILE = re.compile(r"\bto (?:the )?file\b")
_TYPE_VERBS = r"type|enter text|type out|write|right|put"

BLOCKED_SURFACES = frozenset(
    {
        "web",
        "the web",
        "internet",
        "the internet",
        "online",
        "google",
        "bing",
        "duckduckgo",
        "youtube",
        "file",
        "page",
        "window",
        "screen",
        "folder",
    }
)

_APP_ALIASES = {
    "whats app": "whatsapp",
    "whatsapp desktop": "whatsapp",
    "google chrome": "chrome",
    "microsoft edge": "edge",
    "ms edge": "edge",
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "microsoft word": "word",
    "winword": "word",
    "microsoft excel": "excel",
    "microsoft powerpoint": "powerpoint",
    "power point": "powerpoint",
    "ppt": "powerpoint",
    "microsoft outlook": "outlook",
    "microsoft teams": "teams",
}

WINDOW_NEEDLE = {
    "whatsapp": "whatsapp",
    "spotify": "spotify",
    "chrome": "chrome",
    "edge": "edge",
    "firefox": "firefox",
    "brave": "brave",
    "code": "visual studio code",
    "notepad": "notepad",
    "word": "word",
    "excel": "excel",
    "powerpoint": "powerpoint",
    "outlook": "outlook",
    "teams": "teams",
    "slack": "slack",
    "discord": "discord",
    "telegram": "telegram",
}

_FILE_COMMAND = re.compile(
    r"\bto (?:the )?file\b|"
    r"\b(?:cpp|c plus plus|c\+\+|python|javascript|markdown|java|html|source) file\b"
)

_last_type_app = ""


def clear_last_type_app() -> None:
    global _last_type_app
    _last_type_app = ""


def last_type_app() -> str:
    return _last_type_app


def remember_type_app(app: str) -> None:
    global _last_type_app
    _last_type_app = app.strip().lower()


def looks_like_file_command(text: str) -> bool:
    return bool(_FILE_COMMAND.search(" ".join(text.lower().split())))

SEARCH_HOTKEY = {
    "whatsapp": ("ctrl", "f"),
    "spotify": ("ctrl", "l"),
    "chrome": ("ctrl", "l"),
    "edge": ("ctrl", "l"),
    "firefox": ("ctrl", "l"),
    "brave": ("ctrl", "l"),
    "opera": ("ctrl", "l"),
}

PLAYER_APPS = frozenset({"spotify", "vlc", "groove"})

_NAMED_REST = {
    "copy": "copy",
    "copy that": "copy",
    "copy this": "copy",
    "paste": "paste",
    "paste that": "paste",
    "paste this": "paste",
    "cut": "cut",
    "undo": "undo",
    "redo": "redo",
    "select all": "select_all",
    "save": "save",
    "save this": "save",
    "find": "find",
    "new tab": "new_tab",
    "close tab": "close_tab",
    "close the window": "close_window",
    "refresh": "refresh",
    "print": "print",
}

_PLAY_RESUME = frozenset(
    {"music", "the music", "some music", "my music", "song", "the song", "spotify", "playback"}
)
_SETTLE_SEC = 0.35
_TYPE_PAUSE_SEC = 0.25


def warmup_for(app: str) -> float:
    env = (
        "FRIDAY_SPOTIFY_WARMUP_SEC"
        if app == "spotify"
        else "FRIDAY_APP_WARMUP_SEC"
    )
    default = 3.5 if app == "spotify" else 2.0
    raw = os.environ.get(env)
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def normalize_app(raw: str) -> str | None:
    text = " ".join(raw.lower().split())
    text = re.sub(r"^(the|my)\s+", "", text)
    text = re.sub(r"\s+(app|desktop|application)$", "", text)
    text = _APP_ALIASES.get(text, text)
    if not text or text in BLOCKED_SURFACES:
        return None
    if len(text) < 2:
        return None
    return text


def window_needle(app: str) -> str:
    return WINDOW_NEEDLE.get(app, app)


def app_is_open(adapter: OsAdapter, app: str) -> bool:
    needle = window_needle(app)
    return any(needle in window.title.casefold() for window in adapter.list_windows())


def prepare_app(
    adapter: OsAdapter,
    app: str,
    sleeper: Callable[[float], None],
) -> dict[str, bool]:
    """Launch the app if needed, then focus its window."""
    opened = False
    if not app_is_open(adapter, app):
        kind, target = lookup_open_target(app)
        if target:
            execute_open(kind, target, adapter)
            sleeper(warmup_for(app))
            opened = True
    focused = adapter.focus_window(window_needle(app))
    if not focused:
        sleeper(0.8)
        focused = adapter.focus_window(window_needle(app))
    sleeper(_SETTLE_SEC)
    return {"opened": opened, "focused": bool(focused)}


def parse_app_action(rest: str, app: str) -> dict[str, str] | None:
    text = " ".join(rest.lower().split())
    if not text:
        return None

    search = re.match(
        r"^(?:search(?: for)?|find|look up|open chat(?: with)?|chat with)\s+(.+)$",
        text,
    )
    if search:
        return {"task": "search", "text": search.group(1).strip()}

    play = re.match(r"^play(?: the)? (.+)$", text)
    if play:
        query = play.group(1).strip()
        if query in _PLAY_RESUME:
            return {"task": "play"}
        if query in {"next", "next song", "next track"}:
            return {"task": "next"}
        if query in {"previous", "previous song", "last song"}:
            return {"task": "previous"}
        if app in PLAYER_APPS:
            return {"task": "search", "text": query}
        return {"task": "search", "text": query}

    if text in {"play", "pause", "next", "previous", "stop"}:
        return {"task": text}
    if text in {"like", "like this", "like the song", "heart this"}:
        return {"task": "like"}
    if text in {"shuffle", "shuffle play"}:
        return {"task": "shuffle"}

    typed = re.match(rf"^(?:{_TYPE_VERBS})\s+(.+)$", text)
    if typed:
        return {"task": "type", "text": typed.group(1).strip().strip("\"'")}

    pressed = re.match(r"^(?:press|hit)\s+(.+)$", text)
    if pressed:
        keys = parse_hotkey(pressed.group(1))
        if keys:
            return {"task": "hotkey", "keys": "+".join(keys)}
        return None

    named = _NAMED_REST.get(text)
    if named:
        return {"task": named}

    if app == "whatsapp" and re.match(r"^[\w .'-]+$", text) and not text.startswith("send"):
        return {"task": "search", "text": text}
    return None


def parse_in_app_command(text: str) -> dict[str, str] | None:
    """Return automate extras, or None if this is not an in-app command."""
    spoken = " ".join(text.lower().split())
    if _TO_FILE.search(spoken):
        return None

    match = _IN_APP.match(spoken)
    if match is None:
        match = _ON_APP.match(spoken)
    if match is not None:
        app = normalize_app(match.group("app") or "")
        rest = (match.group("rest") or "").strip()
        if app and rest:
            parsed = parse_app_action(rest, app)
            if parsed:
                parsed["app"] = app
                return parsed

    opened = _OPEN_AND.match(spoken)
    if opened:
        app = normalize_app(opened.group("app") or "")
        rest = (opened.group("rest") or "").strip()
        nested = _NESTED_IN_APP.match(rest)
        if nested:
            nested_app = normalize_app(nested.group("app") or "")
            rest = (nested.group("rest") or "").strip()
            if nested_app:
                app = nested_app
        if app and rest:
            parsed = parse_app_action(rest, app)
            if parsed:
                parsed["app"] = app
                return parsed

    chat = _WHATSAPP_CHAT.match(spoken)
    if chat:
        name = (chat.group("name") or "").strip()
        if name and not re.match(r"^(message|call|video)\b", name):
            parsed = parse_app_action(f"search {name}", "whatsapp")
            if parsed:
                parsed["app"] = "whatsapp"
                return parsed

    if not looks_like_file_command(spoken):
        bare = _BARE_WRITE.match(spoken)
        if bare:
            payload = (bare.group("text") or "").strip()
            if payload:
                extras = {"task": "type", "text": payload}
                if _last_type_app:
                    extras["app"] = _last_type_app
                return extras
    return None


def paste_text(
    adapter: OsAdapter,
    text: str,
    sleeper: Callable[[float], None],
) -> None:
    """Paste into whichever window is focused. Works in any app that accepts Ctrl+V."""
    adapter.set_clipboard(text)
    sleeper(_TYPE_PAUSE_SEC)
    adapter.press_hotkey(("ctrl", "v"))


def _search_keys(app: str) -> tuple[str, ...]:
    return SEARCH_HOTKEY.get(app, ("ctrl", "f"))


def run_app_task(
    adapter: OsAdapter,
    *,
    app: str,
    task: str,
    text: str = "",
    keys: str = "",
    sleeper: Callable[[float], None],
) -> dict[str, Any]:
    remember_type_app(app)
    prepared = prepare_app(adapter, app, sleeper)
    label = app.replace("_", " ").title()

    if task in {"play", "pause", "next", "previous", "stop"} and app in PLAYER_APPS:
        media = {
            "play": "play_pause",
            "pause": "play_pause",
            "next": "next",
            "previous": "previous",
            "stop": "stop",
        }[task]
        adapter.media_control(media)
        reply = {
            "play": f"Playing in {label}.",
            "pause": f"Pausing {label}.",
            "next": f"Next track in {label}.",
            "previous": f"Previous track in {label}.",
            "stop": f"Stopping {label}.",
        }[task]
        if prepared["opened"]:
            reply = f"Opening {label}. {reply}"
        return {"ok": True, "reply": reply, "observation": "ok"}

    if task == "search":
        query = text.strip()
        if not query:
            return {
                "ok": False,
                "reply": f"What should I search in {label}?",
                "observation": "missing_text",
            }
        adapter.press_hotkey(_search_keys(app))
        sleeper(_TYPE_PAUSE_SEC)
        paste_text(adapter, query, sleeper)
        sleeper(_TYPE_PAUSE_SEC)
        adapter.press_hotkey(("enter",))
        reply = f"Searching {label} for {query}."
        if prepared["opened"]:
            reply = f"Opening {label} and searching for {query}."
        return {"ok": True, "reply": reply, "observation": "ok"}

    if task == "like":
        if app != "spotify":
            return {
                "ok": False,
                "reply": "I can like a song in Spotify.",
                "observation": "unsupported",
            }
        adapter.press_hotkey(("alt", "shift", "b"))
        return {"ok": True, "reply": "Liking this track.", "observation": "ok"}

    if task == "shuffle":
        if app != "spotify":
            return {
                "ok": False,
                "reply": "I can shuffle in Spotify.",
                "observation": "unsupported",
            }
        adapter.press_hotkey(("ctrl", "s"))
        return {"ok": True, "reply": "Toggling shuffle.", "observation": "ok"}

    if task == "type":
        if not text.strip():
            return {
                "ok": False,
                "reply": "I need something to type.",
                "observation": "missing_text",
            }
        paste_text(adapter, text, sleeper)
        reply = f"Typing in {label}."
        if prepared["opened"]:
            reply = f"Opening {label} and typing."
        return {"ok": True, "reply": reply, "observation": "ok"}

    if task == "hotkey":
        sequence = parse_hotkey(keys)
        if sequence is None:
            return {
                "ok": False,
                "reply": "I can't press that.",
                "observation": "unknown_hotkey",
            }
        adapter.press_hotkey(sequence)
        return {"ok": True, "reply": f"Pressing that in {label}.", "observation": "ok"}

    named = NAMED_TASKS.get(task)
    if named is None:
        return {
            "ok": False,
            "reply": f"I can't do that in {label}.",
            "observation": "unknown_hotkey",
        }
    adapter.press_hotkey(named)
    reply = f"{task_reply(task).rstrip('.')} in {label}."
    return {"ok": True, "reply": reply, "observation": "ok"}
