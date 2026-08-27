from __future__ import annotations

import re
from collections.abc import Callable

from friday.browser.urls import looks_like_url, normalize_url
from friday.language.bilingual import normalize_command
from friday.memory.names import (
    normalize_name_content,
    parse_name_fact,
    parse_name_question,
    search_query_for,
)
from friday.orchestrator.models import Intent, IntentName
from friday.integrations.pending import get_pending

# Message is checked first so "send message to Papa call me later" stays a text.
_MESSAGE_PATTERN = re.compile(
    r"\b("
    r"send\s+a\s+message|"
    r"send\s+message|"
    r"whatsapp\s+message|"
    r"send\s+whatsapp|"
    r"message\s+to|"
    r"text\s+to|"
    r"send\s+text|"
    r"text\s+message"
    r")\b"
)

_VIDEO_PATTERN = re.compile(
    r"\b("
    r"video\s+call|"
    r"whatsapp\s+video|"
    r"make\s+a\s+video\s+call|"
    r"start\s+a\s+video\s+call"
    r")\b"
)

_CALL_PATTERN = re.compile(
    r"\b("
    r"phone\s+call|"
    r"voice\s+call|"
    r"audio\s+call|"
    r"whatsapp\s+call|"
    r"make\s+a\s+phone\s+call|"
    r"make\s+a\s+call|"
    r"call\s+to|"
    r"call"
    r")\b"
)

_SCREENSHOT_PATTERN = re.compile(
    r"^\s*(please\s+|friday\s+|can you\s+)*("
    r"take\s+(a\s+)?screenshot|"
    r"capture\s+(the\s+)?screen|"
    r"screenshot"
    r")"
    r"(?:\s+and\s+(?:then\s+)?(?:show|open|display)(?:\s+me)?(?:\s+(?:the\s+)?screenshot)?)?"
    r"\s*$"
)
_SHOW_SCREENSHOT_PATTERN = re.compile(
    r"^\s*(please\s+|friday\s+|can you\s+)*("
    r"(?:show|open|display|view)(?:\s+me)?\s+(?:the\s+)?(?:latest\s+|last\s+|saved\s+)?screenshot|"
    r"show\s+(?:me\s+)?(?:the\s+)?screenshot"
    r")\s*$"
)
_QUESTION_PREFIX = re.compile(
    r"^(what is\b|what's\b|whats\b(?!app)|tell me\b|where is\b|show the location\b)"
)
_LIST_WINDOWS_PATTERN = re.compile(
    r"\b(?:"
    r"(?:list|show)(?:\s+me)?\s+(?:(?:about|regarding)\s+)?"
    r"(?:the\s+)?(?:list\s+of\s+|of\s+)?(?:the\s+)?(?:open\s+)?windows"
    r"|tell(?:\s+me)?(?:\s+(?:about|regarding))?\s+"
    r"(?:the\s+)?(?:list\s+of\s+)?(?:the\s+)?(?:open\s+)?windows"
    r"|what windows are open"
    r"|which windows are open"
    r")\b"
)
_LIST_PROCESSES_PATTERN = re.compile(
    r"\b(?:"
    r"(?:list|show)(?:\s+me)?\s+(?:(?:about|regarding)\s+)?"
    r"(?:the\s+)?(?:list\s+of\s+|of\s+)?(?:the\s+)?(?:running\s+)?processes"
    r"|tell(?:\s+me)?(?:\s+(?:about|regarding))?\s+"
    r"(?:the\s+)?(?:list\s+of\s+)?(?:the\s+)?(?:running\s+)?processes"
    r"|running processes"
    r")\b"
)
_CLIPBOARD_GET_PATTERN = re.compile(
    r"\b((what('s| is)|read|show|get)\s+(on\s+)?(the\s+)?clipboard|clipboard)\s*$"
)
_CLIPBOARD_SET_PATTERNS = (
    re.compile(r"copy\s+to\s+clipboard\s+(.+)"),
    re.compile(r"set\s+clipboard\s+to\s+(.+)"),
    re.compile(r"copy\s+(.+)\s+to\s+clipboard"),
)
_FOCUS_PATTERN = re.compile(
    r"^(?:please\s+)?(?:switch\s+to|focus(?:\s+on)?|bring)\s+(.+?)(?:\s+to\s+front)?$"
)
_AUTO_PREFIX = r"^(?:please\s+|friday\s+|can you\s+)?"
_AUTO_NAMED = re.compile(
    _AUTO_PREFIX
    + r"(?:"
    r"copy(?:\s+(?:that|this|it|the selection))?|"
    r"paste(?:\s+(?:that|this|it))?|"
    r"cut(?:\s+(?:that|this|it))?|"
    r"undo(?:\s+(?:that|this))?|"
    r"redo(?:\s+(?:that|this))?|"
    r"select all|"
    r"(?:press\s+)?save(?:\s+(?:this|the file|it))?|"
    r"(?:press\s+)?find(?:\s+in(?:\s+the)?\s+page)?|"
    r"print(?:\s+(?:this|it))?|"
    r"new tab|"
    r"close(?: the)? tab|"
    r"close(?: this| the)? window|"
    r"(?:switch|next) window|"
    r"alt tab|"
    r"show(?: the)? desktop|"
    r"go to desktop|"
    r"lock(?: the)? (?:computer|pc|screen|windows)|"
    r"snap(?: it)? left|"
    r"snap(?: it)? right|"
    r"refresh(?: the(?: page|window)?)?"
    r")"
    + r"(?:\s+please)?\s*$"
)
_AUTO_TYPE = re.compile(
    _AUTO_PREFIX
    + r"(?:type|enter text|type out)\s+(?P<text>.+?)\s*$"
)
_AUTO_PRESS = re.compile(
    _AUTO_PREFIX
    + r"(?:press|hit)\s+(?P<keys>.+?)\s*$"
)
_AUTO_TASK = {
    "copy": "copy",
    "copy that": "copy",
    "copy this": "copy",
    "copy it": "copy",
    "copy the selection": "copy",
    "paste": "paste",
    "paste that": "paste",
    "paste this": "paste",
    "paste it": "paste",
    "cut": "cut",
    "cut that": "cut",
    "cut this": "cut",
    "cut it": "cut",
    "undo": "undo",
    "undo that": "undo",
    "undo this": "undo",
    "redo": "redo",
    "redo that": "redo",
    "redo this": "redo",
    "select all": "select_all",
    "save": "save",
    "press save": "save",
    "save this": "save",
    "save the file": "save",
    "save it": "save",
    "find": "find",
    "press find": "find",
    "find in page": "find",
    "find in the page": "find",
    "print": "print",
    "print this": "print",
    "print it": "print",
    "new tab": "new_tab",
    "close tab": "close_tab",
    "close the tab": "close_tab",
    "close window": "close_window",
    "close this window": "close_window",
    "close the window": "close_window",
    "switch window": "switch_window",
    "next window": "switch_window",
    "alt tab": "switch_window",
    "show desktop": "show_desktop",
    "show the desktop": "show_desktop",
    "go to desktop": "show_desktop",
    "lock computer": "lock",
    "lock the computer": "lock",
    "lock pc": "lock",
    "lock the pc": "lock",
    "lock screen": "lock",
    "lock the screen": "lock",
    "lock windows": "lock",
    "lock the windows": "lock",
    "snap left": "snap_left",
    "snap it left": "snap_left",
    "snap right": "snap_right",
    "snap it right": "snap_right",
    "refresh": "refresh",
    "refresh the page": "refresh",
    "refresh the window": "refresh",
}
_PREFIX = r"(?:please\s+|friday\s+|can you\s+)*"
_SEARCH_PATTERN = re.compile(
    r"^\s*"
    + _PREFIX
    + r"(?:"
    r"search\s+the\s+web\s+for|"
    r"search\s+the\s+internet\s+for|"
    r"search\s+online\s+for|"
    r"search\s+google\s+for|"
    r"search\s+bing\s+for|"
    r"search\s+duckduckgo\s+for|"
    r"web\s+search(?:\s+for)?|"
    r"google\s+search(?:\s+for)?|"
    r"google\s+for|"
    r"google"
    r")\s+(.+?)\s*$"
)
_SEARCH_ON_WEB = re.compile(
    r"^\s*"
    + _PREFIX
    + r"(?:search(?:\s+for)?|find|look\s+up)\s+(.+?)\s+on\s+(?:the\s+)?(?:web|internet|google|bing|duckduckgo)\s*$"
)
_OPEN_COMMAND = re.compile(
    r"^\s*"
    + r"(?:please\s+|friday\s+|can you\s+|i (?:would like|want)(?: you)? to\s+)*"
    + r"open\b(?:\s+(?P<target>.+))?\s*$"
)
_OPEN_FILE_TARGET = re.compile(
    r"^(?:a |the |that |this )?files?(?: named| called)?(?:\s+(?P<name>.+))?$"
)
_LOOKUP_ON_WEB = re.compile(
    r"^\s*"
    + _PREFIX
    + r"look\s+up\s+(.+?)\s+on\s+(?:the\s+)?(?:web|internet|google|duckduckgo)\s*$"
)
_LOOKUP_ONLINE = re.compile(
    r"^\s*" + _PREFIX + r"look\s+up\s+(.+?)\s+online\s*$"
)
_READ_PAGE_PATTERN = re.compile(
    r"^\s*"
    + _PREFIX
    + r"(?:"
    r"read\s+(?:this|the)\s+(?:web\s*)?page|"
    r"read\s+(?:the\s+)?(?:web)?site|"
    r"summarize\s+(?:this|the)\s+page|"
    r"what(?:'s| is) on (?:this|the) (?:web\s*)?page|"
    r"what does this page say"
    r")"
    r"\s*(?:please)?\s*$"
)
_GO_TO_PATTERN = re.compile(
    r"^\s*"
    + _PREFIX
    + r"(?:go\s+to|browse(?:\s+to)?|visit|navigate\s+to)\s+(.+?)\s*$"
)
_OPEN_WEBSITE_PATTERN = re.compile(
    r"^\s*"
    + _PREFIX
    + r"open\s+(?:the\s+)?(?:website|webpage|web\s+page|url|link)\s+(.+?)\s*$"
)
_BARE_URL_PATTERN = re.compile(r"^\s*(https?://\S+)\s*$", re.IGNORECASE)
_VPREFIX = r"(?:please\s+|friday\s+|tell\s+me\s+)*"
_DESCRIBE_SCREEN_PATTERN = re.compile(
    r"^\s*"
    + _VPREFIX
    + r"(?:"
    r"what(?:'s| is) on (?:my |the )?screen|"
    r"what do you see(?: on (?:my |the )?screen)?|"
    r"describe (?:my |the )?screen|"
    r"describe what(?:'s| is) on (?:my |the )?screen"
    r")\s*\??\s*$"
)
_OCR_SCREEN_PATTERN = re.compile(
    r"^\s*"
    + _VPREFIX
    + r"(?:"
    r"read (?:the )?text on (?:my |the )?screen|"
    r"read (?:the )?(?:text on )?(?:my |the )?screen|"
    r"ocr(?: the screen)?"
    r")\s*\??\s*$"
)
_MEMORY_PREFIX = r"(?:please\s+|friday\s+|can you\s+)*"
_INGEST_PATTERN = re.compile(
    r"^\s*"
    + _MEMORY_PREFIX
    + r"(?:"
    r"ingest|"
    r"index\s+(?:this\s+)?(?:file|document|note)|"
    r"remember\s+this\s+(?:file|document|note)"
    r")\s+(.+?)\s*$"
)
_REMEMBER_PATTERN = re.compile(
    r"^\s*"
    + _MEMORY_PREFIX
    + r"(?:"
    r"remember\s+that|"
    r"remember:|"
    r"note\s+that|"
    r"remember(?!\s+this\s+(?:file|document|note)\b)"
    r")\s+(.+?)\s*$"
)
_LIST_MEMORY_PATTERN = re.compile(
    r"^\s*"
    + _MEMORY_PREFIX
    + r"(?:"
    r"what do you remember|"
    r"tell me what you remember|"
    r"list(?:\s+my)?\s+memories|"
    r"show(?:\s+me)?(?:\s+my)?\s+memories|"
    r"what do you know about me|"
    r"do you remember"
    r")\s*\??\s*$"
)
_FORGET_ID_PATTERN = re.compile(
    r"^\s*"
    + _MEMORY_PREFIX
    + r"(?:forget|delete)\s+memory\s+(\d+)\s*$"
)
_FORGET_PATTERN = re.compile(
    r"^\s*"
    + _MEMORY_PREFIX
    + r"forget\s+that\s+(.+?)\s*$"
)
_SEARCH_FOR_PATTERN = re.compile(
    r"^\s*"
    + _MEMORY_PREFIX
    + r"search\s+my\s+(?:documents|notes|files|memories|memory)\s+for\s+(.+?)\s*$"
)
_NOTES_SAY_PATTERN = re.compile(
    r"^\s*"
    + _MEMORY_PREFIX
    + r"what do my\s+(?:notes|documents)\s+say about\s+(.+?)\s*$"
)
_LOOKUP_NOTES_PATTERN = re.compile(
    r"^\s*"
    + _MEMORY_PREFIX
    + r"look\s+up\s+(.+?)\s+in my\s+(?:notes|documents|files)\s*$"
)
_DO_YOU_REMEMBER_PATTERN = re.compile(
    r"^\s*"
    + _MEMORY_PREFIX
    + r"do you remember\s+(.+?)\s*$"
)
_KNOW_MY_PATTERN = re.compile(
    r"^\s*"
    + _MEMORY_PREFIX
    + r"do you know (?:what )?my (.+?)(?:\s+is)?\s*\??\s*$"
)
_WHAT_IS_MY_PATTERN = re.compile(
    r"^\s*"
    + _MEMORY_PREFIX
    + r"what(?:'s|s| is) my (.+?)\s*\??\s*$"
)
_TELL_ME_MY_PATTERN = re.compile(
    r"^\s*"
    + _MEMORY_PREFIX
    + r"tell me my (.+?)\s*\??\s*$"
)
_MY_NAME_IS_PATTERN = re.compile(
    r"^\s*"
    + _MEMORY_PREFIX
    + r"(?:my name is|i am|i'm)\s+(.+?)\s*$"
)
_REMEMBER_TRAILING_PATTERN = re.compile(
    r"^\s*(.+?)\s+remember(?:ed)?(?:\s+(?:it|this|that))?\s*$"
)
_VERIFY_SCREEN_PATTERN = re.compile(
    r"^\s*"
    + _VPREFIX
    + r"(?:"
    r"is (?P<a>.+?) on (?:my |the )?screen|"
    r"can you see (?P<b>.+?)(?: on (?:my |the )?screen)?|"
    r"do you see (?P<c>.+?)(?: on (?:my |the )?screen)?|"
    r"check (?:if |whether )(?P<d>.+?) is on (?:my |the )?screen"
    r")\s*\??\s*$"
)

STOP_PHRASES = frozenset({"exit", "quit", "stop listening"})

LlmClassify = Callable[[str], Intent | None]


def classify_whatsapp_action(query: str) -> str:
    if _MESSAGE_PATTERN.search(query):
        return "message"
    if _VIDEO_PATTERN.search(query):
        return "video"
    if _CALL_PATTERN.search(query):
        return "call"
    return "message"


def _is_whatsapp_request(text: str) -> bool:
    if _QUESTION_PREFIX.match(text) and not _MESSAGE_PATTERN.search(text):
        return False
    if classify_productivity(text) is not None:
        return False
    if re.search(r"\b(email|gmail|slack|discord)\b", text):
        return False
    return bool(
        _MESSAGE_PATTERN.search(text)
        or _VIDEO_PATTERN.search(text)
        or _CALL_PATTERN.search(text)
    )


def classify_os(query: str) -> Intent | None:
    text = query.strip().lower()

    set_match = next(
        (match for pattern in _CLIPBOARD_SET_PATTERNS if (match := pattern.search(text))),
        None,
    )
    if set_match:
        copied = set_match.group(1).strip()
        if copied:
            return Intent(
                name=IntentName.OS,
                query=text,
                extra={"action": "clipboard_set", "text": copied},
            )

    if _SHOW_SCREENSHOT_PATTERN.search(text):
        return Intent(
            name=IntentName.OS, query=text, extra={"action": "screenshot_show"}
        )

    if _SCREENSHOT_PATTERN.search(text):
        return Intent(name=IntentName.OS, query=text, extra={"action": "screenshot"})

    if _LIST_WINDOWS_PATTERN.search(text):
        return Intent(name=IntentName.OS, query=text, extra={"action": "windows"})

    if _LIST_PROCESSES_PATTERN.search(text):
        return Intent(name=IntentName.OS, query=text, extra={"action": "processes"})

    if _CLIPBOARD_GET_PATTERN.search(text):
        return Intent(name=IntentName.OS, query=text, extra={"action": "clipboard_get"})

    if _OS_INFO.match(text):
        return Intent(name=IntentName.OS, query=text, extra={"action": "info"})

    if _OS_NETWORK.match(text):
        return Intent(name=IntentName.OS, query=text, extra={"action": "network"})

    focus = _FOCUS_PATTERN.match(text)
    if focus:
        title = focus.group(1).strip()
        if title:
            return Intent(
                name=IntentName.OS,
                query=text,
                extra={"action": "focus", "title": title},
            )

    named = _AUTO_NAMED.match(text)
    if named:
        spoken = " ".join(named.group(0).split())
        spoken = re.sub(r"^(please|friday|can you)\s+", "", spoken)
        spoken = re.sub(r"\s+please$", "", spoken).strip()
        task = _AUTO_TASK.get(spoken)
        if task:
            return Intent(
                name=IntentName.OS,
                query=text,
                extra={"action": "automate", "task": task},
            )

    from friday.os_adapters.app_control import looks_like_file_command, parse_in_app_command

    # Research / browser fill phrases look like "write … on …" or "type X with Y".
    if _RESEARCH_REPORT.match(text) and not (
        _LOOKUP_ON_WEB.match(text) or _LOOKUP_ONLINE.match(text)
    ):
        return None
    if _LOOKUP_NOTES_PATTERN.match(text) or _SEARCH_FOR_PATTERN.match(text):
        return None
    if _BROWSER_FILL.match(text):
        return None

    in_app = parse_in_app_command(text)
    if in_app:
        extra = {"action": "automate", **in_app}
        return Intent(name=IntentName.OS, query=text, extra=extra)

    typed = _AUTO_TYPE.match(text)
    if typed and not looks_like_file_command(text) and not _BROWSER_FILL.match(text):
        payload = (typed.group("text") or "").strip().strip("\"'")
        if payload:
            return Intent(
                name=IntentName.OS,
                query=text,
                extra={"action": "automate", "task": "type", "text": payload},
            )

    pressed = _AUTO_PRESS.match(text)
    if pressed:
        from friday.os_adapters.hotkeys import parse_hotkey

        keys = parse_hotkey(pressed.group("keys") or "")
        if keys:
            return Intent(
                name=IntentName.OS,
                query=text,
                extra={
                    "action": "automate",
                    "task": "hotkey",
                    "keys": "+".join(keys),
                },
            )

    return None


_MEDIA_PREFIX = r"^(?:friday\s+)?(?:can you\s+)?(?:please\s+)?"
_MEDIA_TAIL = r"(?:\s+please)?\s*$"
# "play music", "resume", "start the song", "play spotify" -> resume playback.
_MEDIA_PLAY = re.compile(
    _MEDIA_PREFIX
    + r"(?:"
    r"(?:play|start|resume|continue)(?:\s+(?:the|some|my))?\s+"
    r"(?:music|song|songs|track|playback|spotify)|"
    r"resume|unpause|continue\s+playing|start\s+playing|keep\s+playing"
    r")" + _MEDIA_TAIL
)
# Bare "pause" is safe: it is not used anywhere else as a command.
_MEDIA_PAUSE = re.compile(
    _MEDIA_PREFIX
    + r"pause(?:\s+(?:the|my))?(?:\s+(?:music|song|track|playback|spotify))?"
    + _MEDIA_TAIL
)
_MEDIA_NEXT = re.compile(
    _MEDIA_PREFIX
    + r"(?:(?:play\s+)?next|skip)(?:\s+(?:this|the))?(?:\s+(?:song|track|music|one))?"
    + _MEDIA_TAIL
)
_MEDIA_PREVIOUS = re.compile(
    _MEDIA_PREFIX
    + r"(?:(?:play\s+)?previous|prev|go\s+back|last)(?:\s+(?:a|one|the))?"
    r"(?:\s+(?:song|track))?" + _MEDIA_TAIL
)
# "stop" needs a media object so bare "stop" still stops voice control.
_MEDIA_STOP = re.compile(
    _MEDIA_PREFIX
    + r"stop(?:\s+(?:the|my))?\s+(?:music|song|track|playback|playing|spotify)"
    + _MEDIA_TAIL
)


def classify_media(query: str) -> Intent | None:
    """Media transport control. Deliberately narrow so it never steals
    "play ... on youtube", bare "stop", or an ordinary chat message.
    """
    text = " ".join(query.strip().lower().split())
    if not text or "youtube" in text:
        return None
    for action, pattern in (
        ("play", _MEDIA_PLAY),
        ("pause", _MEDIA_PAUSE),
        ("next", _MEDIA_NEXT),
        ("previous", _MEDIA_PREVIOUS),
        ("stop", _MEDIA_STOP),
    ):
        if pattern.match(text):
            return Intent(name=IntentName.MEDIA, query=text, extra={"action": action})
    return None


def classify_browser(query: str) -> Intent | None:
    text = query.strip().lower()

    if _READ_PAGE_PATTERN.search(text):
        return Intent(name=IntentName.BROWSER, query=text, extra={"action": "read"})

    bare = _BARE_URL_PATTERN.match(text)
    if bare:
        url = normalize_url(bare.group(1))
        if url:
            return Intent(
                name=IntentName.BROWSER,
                query=text,
                extra={"action": "open", "url": url},
            )

    go = _GO_TO_PATTERN.match(text)
    if go:
        target = go.group(1).strip()
        if looks_like_url(target):
            url = normalize_url(target)
            if url:
                return Intent(
                    name=IntentName.BROWSER,
                    query=text,
                    extra={"action": "open", "url": url},
                )

    site = _OPEN_WEBSITE_PATTERN.match(text)
    if site:
        target = site.group(1).strip()
        if looks_like_url(target):
            url = normalize_url(target)
            if url:
                return Intent(
                    name=IntentName.BROWSER,
                    query=text,
                    extra={"action": "open", "url": url},
                )
        if target:
            return Intent(
                name=IntentName.BROWSER,
                query=text,
                extra={"action": "search", "search_query": target},
            )

    search = _SEARCH_PATTERN.match(text)
    if search:
        terms = search.group(1).strip()
        if terms:
            return Intent(
                name=IntentName.BROWSER,
                query=text,
                extra={"action": "search", "search_query": terms},
            )

    lookup = (
        _LOOKUP_ON_WEB.match(text)
        or _LOOKUP_ONLINE.match(text)
        or _SEARCH_ON_WEB.match(text)
    )
    if lookup:
        terms = lookup.group(1).strip()
        if terms:
            return Intent(
                name=IntentName.BROWSER,
                query=text,
                extra={"action": "search", "search_query": terms},
            )

    filled = _BROWSER_FILL.match(text)
    if filled:
        return Intent(
            name=IntentName.BROWSER,
            query=text,
            extra={
                "action": "fill",
                "target": filled.group(1).strip(),
                "value": filled.group(2).strip(),
            },
        )

    downloaded = _BROWSER_DOWNLOAD.match(text)
    if downloaded:
        extra = {"action": "download", "target": downloaded.group(1).strip()}
        folder = (downloaded.group(2) or "").strip()
        if folder:
            extra["folder"] = folder
        return Intent(name=IntentName.BROWSER, query=text, extra=extra)

    tabs = _BROWSER_TABS.match(text)
    if tabs:
        extra: dict[str, str] = {"action": "tabs"}
        url = (tabs.group(1) or "").strip()
        if url:
            extra["url"] = url
        return Intent(name=IntentName.BROWSER, query=text, extra=extra)

    clicked = _BROWSER_CLICK.match(text)
    if clicked:
        target = clicked.group(1).strip()
        # Don't steal OS automate "click" that isn't browser-ish; require page context
        # only when already browsing — still allow explicit "click the login button".
        if target and target not in {"me", "that", "it"}:
            return Intent(
                name=IntentName.BROWSER,
                query=text,
                extra={"action": "click", "target": target},
            )

    return None


def classify_vision(query: str) -> Intent | None:
    text = query.strip().lower()

    if _DESCRIBE_SCREEN_PATTERN.search(text):
        return Intent(name=IntentName.VISION, query=text, extra={"action": "describe"})

    if _OCR_SCREEN_PATTERN.search(text):
        return Intent(name=IntentName.VISION, query=text, extra={"action": "ocr"})

    find = _FIND_ON_SCREEN.match(text)
    if find:
        needle = find.group(1).strip()
        if needle:
            return Intent(
                name=IntentName.VISION,
                query=text,
                extra={"action": "verify", "needle": needle},
            )

    verify = _VERIFY_SCREEN_PATTERN.match(text)
    if verify:
        needle = next(
            (value.strip() for value in verify.groupdict().values() if value),
            "",
        )
        if needle:
            return Intent(
                name=IntentName.VISION,
                query=text,
                extra={"action": "verify", "needle": needle},
            )

    return None


def _normalize_memory_content(content: str, original: str = "") -> str:
    return normalize_name_content(content, original)


def _other_command_stem(fact: str) -> bool:
    lowered = fact.strip().lower()
    if not lowered:
        return True
    if "play" in lowered and "youtube" in lowered:
        return True
    if "open" in lowered:
        return True
    if lowered in STOP_PHRASES:
        return True
    return (
        classify_os(lowered) is not None
        or classify_vision(lowered) is not None
        or classify_browser(lowered) is not None
        or classify_files(lowered) is not None
        or classify_code(lowered) is not None
        or classify_productivity(lowered) is not None
        or classify_research(lowered) is not None
        or classify_integrations(lowered) is not None
        or classify_weather(lowered) is not None
        or classify_media(lowered) is not None
        or classify_news(lowered) is not None
    )


def classify_memory(query: str) -> Intent | None:
    original = query.strip()
    text = original.lower()
    if re.search(r"\b(don't|dont|do not)\s+remember\b", text):
        return None

    ingest = _INGEST_PATTERN.match(text)
    if ingest:
        path = ingest.group(1).strip().strip('"').strip("'")
        if path:
            return Intent(
                name=IntentName.MEMORY,
                query=text,
                extra={"action": "ingest", "path": path},
            )

    forget_id = _FORGET_ID_PATTERN.match(text)
    if forget_id:
        return Intent(
            name=IntentName.MEMORY,
            query=text,
            extra={"action": "forget", "id": int(forget_id.group(1))},
        )

    forget = _FORGET_PATTERN.match(text)
    if forget:
        target = forget.group(1).strip()
        if target:
            return Intent(
                name=IntentName.MEMORY,
                query=text,
                extra={"action": "forget", "text": target},
            )

    if _LIST_MEMORY_PATTERN.match(text):
        return Intent(
            name=IntentName.MEMORY, query=text, extra={"action": "list"}
        )

    stripped = re.sub(r"^\s*(please\s+|friday\s+|can you\s+)*", "", text).strip()
    trailing = _REMEMBER_TRAILING_PATTERN.match(stripped)
    if trailing:
        fact = trailing.group(1).strip()
        if fact and not _other_command_stem(fact):
            return Intent(
                name=IntentName.MEMORY,
                query=text,
                extra={
                    "action": "remember",
                    "content": _normalize_memory_content(fact, original),
                },
            )

    parsed_name = parse_name_fact(stripped)
    if parsed_name and parsed_name[1]:
        return Intent(
            name=IntentName.MEMORY,
            query=text,
            extra={
                "action": "remember",
                "content": _normalize_memory_content(stripped, original),
            },
        )

    named = _MY_NAME_IS_PATTERN.match(text)
    if named:
        person = named.group(1).strip()
        if person:
            content = (
                person
                if person.startswith("my name is")
                else f"my name is {person}"
            )
            return Intent(
                name=IntentName.MEMORY,
                query=text,
                extra={
                    "action": "remember",
                    "content": _normalize_memory_content(content, original),
                },
            )

    asked = parse_name_question(text)
    if asked is not None:
        return Intent(
            name=IntentName.MEMORY,
            query=text,
            extra={"action": "search", "search_query": search_query_for(asked)},
        )

    personal = (
        _KNOW_MY_PATTERN.match(text)
        or _WHAT_IS_MY_PATTERN.match(text)
        or _TELL_ME_MY_PATTERN.match(text)
    )
    if personal:
        needle = personal.group(1).strip()
        if needle:
            topic = needle if needle.startswith("my ") else f"my {needle}"
            return Intent(
                name=IntentName.MEMORY,
                query=text,
                extra={"action": "search", "search_query": topic},
            )

    for pattern in (
        _SEARCH_FOR_PATTERN,
        _NOTES_SAY_PATTERN,
        _LOOKUP_NOTES_PATTERN,
        _DO_YOU_REMEMBER_PATTERN,
    ):
        match = pattern.match(text)
        if match:
            needle = match.group(1).strip()
            if needle:
                return Intent(
                    name=IntentName.MEMORY,
                    query=text,
                    extra={"action": "search", "search_query": needle},
                )

    remember = _REMEMBER_PATTERN.match(text)
    if remember:
        content = remember.group(1).strip()
        if content:
            return Intent(
                name=IntentName.MEMORY,
                query=text,
                extra={
                    "action": "remember",
                    "content": _normalize_memory_content(content, original),
                },
            )

    return None


_P9 = r"(?:please\s+|friday\s+|can you\s+)*"
_WANT_TO = r"(?:i (?:would like|want)(?: you)? to\s+)?"
# Trailing \b so "my" cannot steal "mummy" / "myself" cannot steal a name.
_SELF_MAIL = r"(?:me|myself|self|my(?:self)?|my email|my gmail|my mail)\b"
_SAYING = r"(?:by saying|saying|that|:)"
_EMAIL_SEND = re.compile(
    r"^\s*"
    + _P9
    + r"(?:send (?:an |a )?e?-?mails? to|e?-?mails? to|e?-?mails?)\s+(.+?)\s+"
    + _SAYING
    + r"\s+(.+?)\s*$"
)
_EMAIL_ABOUT = re.compile(
    r"^\s*"
    + _P9
    + r"(?:send (?:an |a )?e?-?mails? to|e?-?mails? to|e?-?mails?)\s+(.+?)\s+about\s+(.+?)\s*$"
)
_EMAIL_TO_SELF = re.compile(
    r"^\s*"
    + _P9
    + _WANT_TO
    + r"(?:"
    r"send (?:me )?(?:an |a )?e?-?mails?|"
    r"e?-?mails? (?:me|myself|self)|"
    r"e?-?mails? to "
    + _SELF_MAIL
    + r"|"
    r"send (?:an |a )?e?-?mails? to "
    + _SELF_MAIL
    + r")"
    r"(?:\s+"
    + _SAYING
    + r"\s+(.+?))?\s*$"
)
# Spoken leftovers after "connect gmail": "myself by saying hi" / "self saying hi"
_SELF_BODY_ONLY = re.compile(
    r"^\s*"
    + _P9
    + r"(?:to )?(?:me|myself|self)\s+"
    + _SAYING
    + r"\s+(.+?)\s*$"
)


def _clean_email_recipient(raw: str) -> str:
    """Strip STT leftovers like leading 'to' / trailing 'by' from a recipient."""
    text = " ".join(raw.strip().lower().split())
    text = re.sub(r"^to\s+", "", text)
    text = re.sub(r"\s+by$", "", text).strip()
    if text in {"me", "myself", "self", "my", "my email", "my gmail", "my mail"}:
        return "me"
    return text
_FIND_NAMED_FILE = re.compile(
    r"^\s*"
    + _P9
    + r"find (?:a |the )?files? (?:named |called )?(.+?)\s*$"
)
_FOLDER_NAME = r"downloads|download|documents|docs|desktop|pictures|photos"
_SEARCH_FOLDER_FOR = re.compile(
    r"^\s*"
    + _P9
    + r"search (?:in |from |inside )?(?:the |my )?("
    + _FOLDER_NAME
    + r") for (.+?)\s*$"
)
_FIND_IN_FOLDER = re.compile(
    r"^\s*"
    + _P9
    + r"find (?:a |the )?files? (?:named |called )?(.+?) in (?:the |my )?("
    + _FOLDER_NAME
    + r")\s*$"
)
_FIND_DOWNLOADED = re.compile(
    r"^\s*"
    + _P9
    + r"(?:find (?:a |the )?files? downloaded|list files (?:i )?downloaded) (yesterday|today)\s*$"
)
_LIST_FILES_IN = re.compile(
    r"^\s*"
    + _P9
    + r"(?:list|show) files (?:in |from )?(?:the |my )?("
    + _FOLDER_NAME
    + r")\s*$"
)
_SHOW_ME_FILES_IN = re.compile(
    r"^\s*"
    + _P9
    + r"show(?: me)? (?:the |a )?files? (?:in |from )(?:the |my )?("
    + _FOLDER_NAME
    + r")\s*$"
)
_MAKE_KIND_FILE = re.compile(
    r"^\s*"
    + _P9
    + _WANT_TO
    + r"(?:make|create|write)(?: me)?(?: a| an| the)?"
    r" (?P<kind>c plus plus|c\+\+|cpp|python|javascript|markdown|java|html|css|text|txt|py|js|md|c)"
    r"(?: source)? file"
    # Trailing "of" / "named" with no stem still matches so Friday can ask.
    r"(?: (?:of|named|called|for|about)(?: (?P<name>.+?))?)?"
    r"(?: (?:that |which |where it )?(?:shows|prints|says|displays) (?P<says>.+?))?"
    r"(?: and(?: then)?(?: also)? (?:show|open)(?: it| me the file)?)?"
    r"(?: and(?: then)?(?: also)? (?:compile(?: it)?(?: and run(?: it)?)?|run(?: it)?))?"
    r"\s*$"
)
_RUN_LAST_FILE = re.compile(
    r"^\s*"
    + _P9
    + r"(?:"
    r"compile(?: and)?(?: then)?(?: run)?(?: (?:the |that |this )?(?:file|it|code|program))?|"
    r"run(?: (?:the |that |this )?(?:file|it|code|program|cpp|c plus plus))?(?: (?:for me))?|"
    r"(?:build|execute)(?: (?:the |that |this )?(?:file|it|code|program))?"
    r")\s*$"
)
_WEATHER = re.compile(
    r"^\s*"
    + _P9
    + r"(?:"
    r"(?:(?:what'?s|whats|how'?s|hows|tell me|give me|check|what|how)\s+)?"
    r"(?:(?:regarding|about|for)\s+)?"
    r"(?:(?:is|are)\s+)?"
    r"(?:the\s+|today'?s\s+|today\s+|current\s+|indian?\s+)?"
    r"(?:weather(?:\s+forecast)?|forecast|temperature)"
    r"(?:\s+(?:forecast|report|update|outlook))?"
    r"(?:\s+today|\s+now)?"
    r"(?:\s+(?:like\s+)?(?:in|for|at|of)\s+(?P<place>.+?))?"
    r"|"
    # STT scraps: "in the weather", "the weather forecast"
    r"(?:in\s+)?(?:the\s+)?(?:weather(?:\s+forecast)?|forecast)"
    r"(?:\s+(?:like\s+)?(?:in|for|at|of)\s+(?P<place2>.+?))?"
    r")"
    r"(?:\s+today|\s+now|\s+please)?"
    r"\s*$"
)
_NEWS = re.compile(
    r"^\s*"
    + _P9
    + r"(?:(?:what'?s|whats|what is|tell me|give me|read|check)\s+)?"
    r"(?:the\s+|latest\s+|today'?s\s+|today\s+|top\s+|any\s+|breaking\s+)?"
    r"(?:(?P<topic>india(?:n)?|world|international|national|"
    r"tech(?:nology)?|sports?|business|market(?:s)?|economy|"
    r"entertainment|bollywood|science|health)\s+)?"
    r"(?:news|headlines)"
    r"(?:\s+(?:in|from|about|on|regarding|for)\s+(?P<about>.+?))?"
    r"(?:\s+please)?"
    r"\s*$"
)
_NEWS_QUERY = re.compile(
    r"^\s*"
    + _P9
    + r"(?P<query>(?!open\b|google\b|search\b|find\b|play\b|make\b|send\b).+?)"
    r"\s+(?:news|headlines)\s*$"
)
_MAKE_NAMED_FILE = re.compile(
    r"^\s*"
    + _P9
    + _WANT_TO
    + r"(?:make|create)(?: me)?(?: a| an| the)?(?: new)?(?: file )?"
    r"(?:named |called )?(?P<name>\S+\.[a-z0-9]{1,8})"
    r"(?: and(?: then)?(?: also)? (?:show|open)(?: it| me the file)?)?"
    r"\s*$"
)
_SHOW_LAST_FILE = re.compile(
    r"^\s*"
    + _P9
    + r"(?:"
    r"show(?: me)? (?:the |that |this )?(?:last |latest |saved )?(?:file|it)|"
    r"open (?:the |that |this )?(?:last |latest )?file|"
    r"open it|"
    r"(?:sure|yes|yeah|ok|okay)(?:\s+and)?(?:\s+also)?\s+(?:show|open)(?:\s+it)?"
    r")\s*$"
)
_SHOW_ME_THE_FILE = re.compile(
    r"^\s*"
    + _P9
    + r"(?:show(?: me)? (?:the |a )?files?(?: named| called)?|"
    r"open (?:the |a )?files?(?: named| called)?)"
    r"(?:\s+(.+?))?\s*$"
)
_SEARCH_OR_SHOW_FOLDER = re.compile(
    r"^\s*"
    + _P9
    + r"(?:search|list|show) (?:in |from |inside )?(?:the |my )?("
    + _FOLDER_NAME
    + r")(?:\s+folder)?\s*$"
)
_WHATS_IN_FOLDER = re.compile(
    r"^\s*"
    + _P9
    + r"what(?:'s|s| is) in (?:my |the )?("
    + _FOLDER_NAME
    + r")\s*\??\s*$"
)
_FILE_WEB_HINT = re.compile(r"\b(web|google|internet|online|youtube|browser)\b")
_FILE_ACTION_HINT = re.compile(r"\b(search|find|list|show|files?)\b")
_DOWNLOADED_HINT = re.compile(r"\bdownloaded\b")
_FOLDER_HINT = re.compile(rf"\b({_FOLDER_NAME})\b")
_FILE_STOPWORDS = frozenset(
    {
        "please",
        "friday",
        "can",
        "you",
        "the",
        "a",
        "an",
        "my",
        "me",
        "and",
        "search",
        "find",
        "list",
        "show",
        "in",
        "from",
        "for",
        "of",
        "to",
        "file",
        "files",
        "folder",
        "regarding",
        "about",
        "which",
        "that",
        "i",
        "have",
        "had",
        "downloaded",
        "download",
        "downloads",
        "document",
        "documents",
        "docs",
        "desktop",
        "pictures",
        "photos",
        "what",
        "whats",
        "is",
        "are",
        "there",
        "any",
        "yesterday",
        "today",
        "on",
        "inside",
    }
)
_READ_FILE = re.compile(
    r"^\s*"
    + _P9
    + r"(?:read (?:the )?file|what(?:'s| is) in (?:the )?file|show (?:me )?(?:the )?contents? of (?:the )?file)\s+(.+?)\s*$"
)
_WRITE_FILE = re.compile(
    r"^\s*"
    + _P9
    + r"(?:write|save)\s+(.+?)\s+to (?:the )?file\s+(.+?)(?:\s+on (?:the )?(desktop|downloads|documents))?\s*$"
)
_MOVE_FILE = re.compile(
    r"^\s*"
    + _P9
    + r"move (?:the )?file\s+(.+?)\s+to\s+(.+?)\s*$"
)
_COPY_FILE = re.compile(
    r"^\s*"
    + _P9
    + r"copy (?:the )?file\s+(.+?)\s+to\s+(.+?)\s*$"
)
_MKDIR = re.compile(
    r"^\s*"
    + _P9
    + r"(?:make|create)(?: me)?(?: a| an| the)?(?: new)? folder(?: named| called)?\s+(.+?)"
    r"(?: (?:on|in) (?:the |my )?(desktop|downloads|documents))?\s*$"
)
_OS_INFO = re.compile(
    r"^\s*"
    + _P9
    + r"(?:system info(?:rmation)?|what(?:'s| is) (?:my )?(?:system|os|operating system)(?: info(?:rmation)?)?|"
    r"tell me (?:about )?(?:my )?(?:system|computer|laptop)|about this (?:pc|computer|laptop))"
    r"\s*\??\s*$"
)
_OS_NETWORK = re.compile(
    r"^\s*"
    + _P9
    + r"(?:(?:what(?:'s| is) )?(?:my )?(?:ip(?: address)?|local ip)|"
    r"am i online|network status|are we online|check (?:the )?network)"
    r"\s*\??\s*$"
)
_RENAME_FILE = re.compile(
    r"^\s*"
    + _P9
    + r"rename (?:the )?file\s+(.+?)\s+to\s+(.+?)\s*$"
)
_READ_SOURCE = re.compile(
    r"^\s*"
    + _P9
    + r"(?:read (?:the )?source file|show (?:me )?(?:the )?code (?:in|for)|read)\s+(.+?)\s+in (?:this )?(?:repo|project|workspace)\s*$"
)
_RUN_TESTS = re.compile(
    r"^\s*"
    + _P9
    + r"run (?:the )?(?:unit )?tests(?:\s+for\s+(.+?))?\s*$"
)
_REPLACE_IN_FILE = re.compile(
    r"^\s*"
    + _P9
    + r"replace\s+(.+?)\s+with\s+(.+?)\s+in\s+(.+?)\s*$"
)
_ADD_NOTE = re.compile(
    r"^\s*"
    + _P9
    + r"(?:add a note|make a note|jot down)\s+(.+?)\s*$"
)
_LIST_NOTES = re.compile(
    r"^\s*"
    + _P9
    + r"(?:list (?:my )?notes|what notes do i have|show (?:me )?(?:my )?notes)\s*\??\s*$"
)
_REMIND_ME = re.compile(
    r"^\s*"
    + _P9
    + r"(?:remind me to|set a reminder to|set a reminder|add a reminder)\s+(.+?)\s*$"
)
_LIST_REMINDERS = re.compile(
    r"^\s*"
    + _P9
    + r"(?:list (?:my )?reminders|what(?:'s|s| is| are) my reminders|show (?:me )?(?:my )?reminders)\s*\??\s*$"
)
_ADD_TASK = re.compile(
    r"^\s*"
    + _P9
    + r"(?:add (?:a |an )?task|create (?:a |an )?task|new task)\s+(.+?)\s*$"
)
_LIST_TASKS = re.compile(
    r"^\s*"
    + _P9
    + r"(?:list (?:my )?tasks|what(?:'s|s| are) my tasks|show (?:me )?(?:my )?tasks|"
    r"what do i (?:need|have) to do)\s*\??\s*$"
)
_DONE_TASK = re.compile(
    r"^\s*"
    + _P9
    + r"(?:mark(?: task)?|complete(?: task)?|finish(?: task)?|done(?: with)?(?: task)?)\s+(.+?)"
    r"(?:\s+done|\s+as done)?\s*$"
)
_EXPLAIN_CODE = re.compile(
    r"^\s*"
    + _P9
    + r"(?:explain(?: the)?(?: code(?: in| for)?| error(?: in| for)?)?|what does(?: the)?(?: code(?: in)?)?)\s+(.+?)"
    r"(?:\s+in (?:this )?(?:repo|project|workspace))?\s*$"
)
_RESEARCH_REPORT = re.compile(
    r"^\s*"
    + _P9
    + r"(?:research|look up|write (?:a |me a )?report on|brief me on|investigate)\s+(.+?)\s*$"
)
_RESEARCH_DOCS = re.compile(
    r"^\s*"
    + _P9
    + r"(?:search (?:my )?(?:documents|docs|files) for|research (?:in |from )?(?:my )?documents)\s+(.+?)\s*$"
)
_BROWSER_CLICK = re.compile(
    r"^\s*"
    + _P9
    + r"(?:click|press|tap)\s+(?:on\s+)?(?:the\s+)?(.+?)\s*$"
)
_BROWSER_FILL = re.compile(
    r"^\s*"
    + _P9
    + r"(?:fill|type(?: in)?|enter)\s+(.+?)\s+(?:with|as)\s+(.+?)\s*$"
)
_BROWSER_DOWNLOAD = re.compile(
    r"^\s*"
    + _P9
    + r"download\s+(.+?)(?:\s+to (?:the |my )?(downloads|desktop|documents))?\s*$"
)
_BROWSER_TABS = re.compile(
    r"^\s*"
    + _P9
    + r"(?:(?:what|which) tabs(?: are open)?|list(?: my)?(?: browser)? tabs|"
    r"open(?: a)?(?: new)? tab(?: (?:to|at|for)\s+(.+))?)\s*\??\s*$"
)
_FIND_ON_SCREEN = re.compile(
    r"^\s*"
    + _P9
    + r"(?:find|is|locate)\s+(.+?)\s+on (?:the |my )?screen\s*\??\s*$"
)
_CONNECT_INTEGRATION = re.compile(
    r"^\s*"
    + _P9
    + r"(?:connect|link) (?:to )?(?:my )?(gmail|google|email|mail|slack|discord)"
    r"(?: account)?\s*$"
)
_DISCONNECT_INTEGRATION = re.compile(
    r"^\s*"
    + _P9
    + r"disconnect (?:from )?(?:my )?(gmail|google|email|mail|slack|discord)"
    r"(?: account)?\s*$"
)
_CONNECT_AGAIN = re.compile(
    r"^\s*"
    + _P9
    + r"(?:now )?(?:connect(?: it| that| again)|reconnect(?: it| again)?)\s*$"
)
_INTEGRATION_STATUS = re.compile(
    r"^\s*"
    + _P9
    + r"(?:what (?:integrations|accounts)(?: do i have| are connected)?|"
    r"list (?:my )?integrations|"
    r"is (?:it|that|this|my email|(?:my )?(?:gmail|google|email|slack|discord)) connected)"
    r"\s*\??\s*$"
)
_EMAIL_LIST = re.compile(
    r"^\s*"
    + _P9
    + r"(?:check (?:my )?(?:email|emails|gmail|inbox)|"
    r"(?:read|list) (?:my )?(?:emails?|gmail|inbox)|"
    r"what(?:'s|s| is) in my (?:inbox|emails?|gmail))\s*\??\s*$"
)
_SEND_IT_TO_ME = re.compile(
    r"^\s*"
    + _P9
    + r"(?:no\s+)?send it to "
    + _SELF_MAIL
    + r"\s*$"
)
_SEND_EMAIL_NOW = re.compile(
    r"^\s*"
    + _P9
    + r"(?:send (?:the |that )?email(?: now)?|send it now)\s*$"
)
_CONFIRM_PENDING = re.compile(
    r"^\s*"
    + _P9
    + r"(?:"
    r"(?:yes|yeah|yep|yup|ok|okay|sure|haan|han|ya|y)"
    r"(?:\s+(?:yes|yeah|yep|yup|ok|okay|sure|please))*"
    r"(?:\s+send(?:\s+it)?(?:\s+now)?)?|"
    r"send(?:\s+it)?(?:\s+now)?|"
    r"send it to (?:me|myself)|"
    r"send (?:the |that )?email(?:\s+now)?|"
    r"do it|"
    r"go ahead|"
    r"confirm(?:ed)?"
    r")(?:\s+please)?\s*$"
)
_CANCEL_PENDING = re.compile(
    r"^\s*"
    + _P9
    + r"(?:no|nope|nah|cancel(?: it)?|don't send|do not send|never mind|nevermind)"
    r"(?:\s+(?:no|nope|nah|thanks|thank you))*\s*$"
)
_EMAIL_TO_ADDRESS = re.compile(
    r"^\s*"
    + _P9
    + r"(?:send (?:an |a )?email to|email)\s+(\S+@\S+)\s*$"
)
# "send email to mummy" with no body yet. Kept last among the email rules so
# the self ("to me") and "saying ..." forms win first. Without this the phrase
# fell through to chat, where the LLM would invent a fake "sent to <you>" reply.
_EMAIL_TO_NAME = re.compile(
    r"^\s*"
    + _P9
    + r"(?:send (?:an |a )?e?-?mail(?:\s+to)?|e?-?mail(?:\s+to)?)\s+(.+?)\s*$"
)
# A dangling connector left over when the person trails off ("...to mummy that").
_EMAIL_NAME_TAIL = re.compile(r"\s+(?:saying|that|about|to say|:)\s*$")
_SLACK_SEND = re.compile(
    r"^\s*"
    + _P9
    + r"(?:send (?:a )?slack (?:message|dm) to|post (?:to |on )?slack(?: in)?)\s+"
    r"(.+?)\s+(?:saying|that|:)\s+(.+?)\s*$"
)
_DISCORD_SEND = re.compile(
    r"^\s*"
    + _P9
    + r"send (?:a )?discord (?:message )?to\s+(.+?)\s+(?:saying|that|:)\s+(.+?)\s*$"
)
_DISCORD_POST = re.compile(
    r"^\s*"
    + _P9
    + r"post (?:to |on )?discord(?: in (.+?))?\s+(?:saying|that|:)\s+(.+?)\s*$"
)


def classify_weather(query: str) -> Intent | None:
    """Live India forecast. Browser search phrases stay with classify_browser."""
    text = " ".join(query.strip().lower().split())
    found = _WEATHER.match(text)
    if found is None:
        return None
    place = re.sub(
        r"\s+(today|now|please)$",
        "",
        (found.group("place") or found.group("place2") or "").strip(),
    )
    extra: dict[str, str] = {"action": "forecast"}
    if place:
        extra["place"] = place
    return Intent(name=IntentName.WEATHER, query=text, extra=extra)


def classify_news(query: str) -> Intent | None:
    """Live headlines. Browser search phrases stay with classify_browser."""
    text = " ".join(query.strip().lower().split())
    found = _NEWS.match(text)
    about = ""
    if found is not None:
        about = (found.group("topic") or found.group("about") or "").strip()
    else:
        found = _NEWS_QUERY.match(text)
        if found is None:
            return None
        about = (found.group("query") or "").strip()
    extra: dict[str, str] = {"action": "headlines"}
    if about:
        from friday.news.headlines import normalize_topic

        mapped = normalize_topic(about)
        if mapped:
            extra["topic"] = mapped
        else:
            extra["query"] = about
    return Intent(name=IntentName.NEWS, query=text, extra=extra)


def classify_files(query: str) -> Intent | None:
    text = query.strip().lower()
    from friday.files.create import normalize_make_utterance, plan_new_file

    made = _MAKE_KIND_FILE.match(normalize_make_utterance(text))
    if made:
        path, body = plan_new_file(
            kind=made.group("kind") or "",
            name=made.group("name") or "",
            says=made.group("says") or "",
        )
        extra = {
            "action": "write",
            "path": path,
            "text": body,
            "folder": "desktop",
            "kind": made.group("kind") or "",
            "says": made.group("says") or "",
            # Always open the editor so they see the file they asked for.
            "open": True,
        }
        if re.search(r"\b(compile|run|build|execute)\b", text):
            extra["run"] = True
        return Intent(name=IntentName.FILE, query=text, extra=extra)

    named_new = _MAKE_NAMED_FILE.match(text)
    if named_new:
        from friday.files.create import plan_new_file

        path, body = plan_new_file(name=named_new.group("name") or "")
        extra = {
            "action": "write",
            "path": path,
            "text": body,
            "folder": "desktop",
            "open": True,
        }
        if re.search(r"\b(show|open)\b", text):
            extra["open"] = True
        if re.search(r"\b(compile|run|build|execute)\b", text):
            extra["run"] = True
        return Intent(name=IntentName.FILE, query=text, extra=extra)

    if _RUN_LAST_FILE.match(text):
        return Intent(name=IntentName.FILE, query=text, extra={"action": "run"})

    if _SHOW_LAST_FILE.match(text):
        return Intent(
            name=IntentName.FILE, query=text, extra={"action": "show_last"}
        )

    downloaded = _FIND_DOWNLOADED.match(text)
    if downloaded:
        return Intent(
            name=IntentName.FILE,
            query=text,
            extra={
                "action": "search",
                "folder": "downloads",
                "when": downloaded.group(1),
            },
        )

    listed = _LIST_FILES_IN.match(text)
    if listed:
        return Intent(
            name=IntentName.FILE,
            query=text,
            extra={"action": "search", "folder": listed.group(1)},
        )

    shown_in = _SHOW_ME_FILES_IN.match(text)
    if shown_in:
        return Intent(
            name=IntentName.FILE,
            query=text,
            extra={"action": "search", "folder": shown_in.group(1)},
        )

    shown_file = _SHOW_ME_THE_FILE.match(text)
    if shown_file:
        return _file_intent_from_name(text, (shown_file.group(1) or "").strip())

    folder_search = _SEARCH_FOLDER_FOR.match(text)
    if folder_search:
        return Intent(
            name=IntentName.FILE,
            query=text,
            extra={
                "action": "search",
                "folder": folder_search.group(1),
                "needle": folder_search.group(2).strip(),
            },
        )

    in_folder = _FIND_IN_FOLDER.match(text)
    if in_folder:
        return Intent(
            name=IntentName.FILE,
            query=text,
            extra={
                "action": "search",
                "needle": in_folder.group(1).strip(),
                "folder": in_folder.group(2),
            },
        )

    named = _FIND_NAMED_FILE.match(text)
    if named:
        needle = named.group(1).strip()
        if needle:
            return Intent(
                name=IntentName.FILE,
                query=text,
                extra={"action": "search", "needle": needle},
            )

    read = _READ_FILE.match(text)
    if read:
        path = read.group(1).strip()
        if path:
            return Intent(
                name=IntentName.FILE,
                query=text,
                extra={"action": "read", "path": path},
            )

    written = _WRITE_FILE.match(text)
    if written:
        body = written.group(1).strip()
        path = written.group(2).strip()
        folder = (written.group(3) or "").strip()
        if body and path:
            extra = {"action": "write", "text": body, "path": path}
            if folder:
                extra["folder"] = folder
            return Intent(name=IntentName.FILE, query=text, extra=extra)

    moved = _MOVE_FILE.match(text)
    if moved:
        return Intent(
            name=IntentName.FILE,
            query=text,
            extra={
                "action": "move",
                "source": moved.group(1).strip(),
                "destination": moved.group(2).strip(),
            },
        )

    copied = _COPY_FILE.match(text)
    if copied:
        return Intent(
            name=IntentName.FILE,
            query=text,
            extra={
                "action": "copy",
                "source": copied.group(1).strip(),
                "destination": copied.group(2).strip(),
            },
        )

    mkdir = _MKDIR.match(text)
    if mkdir:
        extra = {
            "action": "mkdir",
            "path": mkdir.group(1).strip(),
            "folder": (mkdir.group(2) or "desktop").strip(),
        }
        return Intent(name=IntentName.FILE, query=text, extra=extra)

    renamed = _RENAME_FILE.match(text)
    if renamed:
        return Intent(
            name=IntentName.FILE,
            query=text,
            extra={
                "action": "move",
                "source": renamed.group(1).strip(),
                "destination": renamed.group(2).strip(),
            },
        )

    shown = _SEARCH_OR_SHOW_FOLDER.match(text)
    if shown:
        return Intent(
            name=IntentName.FILE,
            query=text,
            extra={"action": "search", "folder": shown.group(1)},
        )

    inside = _WHATS_IN_FOLDER.match(text)
    if inside:
        return Intent(
            name=IntentName.FILE,
            query=text,
            extra={"action": "search", "folder": inside.group(1)},
        )

    return _loose_file_search(text)


def _file_intent_from_name(query: str, name: str) -> Intent:
    cleaned = name.strip()
    if cleaned and re.search(r"\.[a-z0-9]{1,8}$", cleaned):
        return Intent(
            name=IntentName.FILE,
            query=query,
            extra={"action": "read", "path": cleaned},
        )
    extra: dict[str, str] = {"action": "search"}
    if cleaned:
        extra["needle"] = cleaned
    return Intent(name=IntentName.FILE, query=query, extra=extra)


def classify_open(query: str) -> Intent | None:
    """Command-shaped open only. Does not match 'opened' or 'don't open'."""
    text = query.strip().lower()
    matched = _OPEN_COMMAND.match(text)
    if matched is None:
        return None
    target = (matched.group("target") or "").strip()
    file_target = _OPEN_FILE_TARGET.match(target)
    if file_target is not None:
        return _file_intent_from_name(text, (file_target.group("name") or "").strip())
    if target and looks_like_url(target):
        url = normalize_url(target)
        if url:
            return Intent(
                name=IntentName.BROWSER,
                query=text,
                extra={"action": "open", "url": url},
            )
    return Intent(name=IntentName.OPEN, query=text)


def _file_search_needle(text: str) -> str:
    tokens = [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9._-]*", text.lower())
        if token not in _FILE_STOPWORDS
    ]
    return " ".join(tokens)


def _loose_file_search(text: str) -> Intent | None:
    if _FILE_WEB_HINT.search(text):
        return None
    downloaded = bool(_DOWNLOADED_HINT.search(text))
    folder_match = _FOLDER_HINT.search(text)
    if not downloaded and folder_match is None:
        return None
    if not _FILE_ACTION_HINT.search(text):
        return None
    extra: dict[str, str] = {"action": "search"}
    if downloaded or (
        folder_match is not None and folder_match.group(1).startswith("download")
    ):
        extra["folder"] = "downloads"
    elif folder_match is not None:
        extra["folder"] = folder_match.group(1)
    if "yesterday" in text:
        extra["when"] = "yesterday"
    elif "today" in text:
        extra["when"] = "today"
    needle = _file_search_needle(text)
    if needle:
        extra["needle"] = needle
    return Intent(name=IntentName.FILE, query=text, extra=extra)


def classify_code(query: str) -> Intent | None:
    text = query.strip().lower()

    tests = _RUN_TESTS.match(text)
    if tests:
        target = (tests.group(1) or "").strip()
        extra = {"action": "test"}
        if target:
            extra["target"] = target
        return Intent(name=IntentName.CODE, query=text, extra=extra)

    patched = _REPLACE_IN_FILE.match(text)
    if patched:
        return Intent(
            name=IntentName.CODE,
            query=text,
            extra={
                "action": "patch",
                "old": patched.group(1).strip().strip('"').strip("'"),
                "new": patched.group(2).strip().strip('"').strip("'"),
                "path": patched.group(3).strip(),
            },
        )

    source = _READ_SOURCE.match(text)
    if source:
        path = source.group(1).strip()
        if path and path not in {"the screen", "this page", "the clipboard"}:
            return Intent(
                name=IntentName.CODE,
                query=text,
                extra={"action": "read", "path": path},
            )

    explained = _EXPLAIN_CODE.match(text)
    if explained:
        path = explained.group(1).strip()
        if path:
            focus = "error" if "error" in text else ""
            extra = {"action": "explain", "path": path}
            if focus:
                extra["focus"] = focus
            return Intent(name=IntentName.CODE, query=text, extra=extra)

    return None


def classify_productivity(query: str) -> Intent | None:
    text = query.strip().lower()

    if _LIST_NOTES.match(text):
        return Intent(
            name=IntentName.PRODUCTIVITY, query=text, extra={"action": "notes_list"}
        )
    if _LIST_REMINDERS.match(text):
        return Intent(
            name=IntentName.PRODUCTIVITY,
            query=text,
            extra={"action": "reminders_list"},
        )
    if _LIST_TASKS.match(text):
        return Intent(
            name=IntentName.PRODUCTIVITY, query=text, extra={"action": "tasks_list"}
        )

    note = _ADD_NOTE.match(text)
    if note:
        content = note.group(1).strip()
        if content:
            return Intent(
                name=IntentName.PRODUCTIVITY,
                query=text,
                extra={"action": "notes_add", "content": content},
            )

    reminder = _REMIND_ME.match(text)
    if reminder:
        content = reminder.group(1).strip()
        if content:
            return Intent(
                name=IntentName.PRODUCTIVITY,
                query=text,
                extra={"action": "reminders_add", "content": content},
            )

    task = _ADD_TASK.match(text)
    if task:
        content = task.group(1).strip()
        if content:
            return Intent(
                name=IntentName.PRODUCTIVITY,
                query=text,
                extra={"action": "tasks_add", "content": content},
            )

    done = _DONE_TASK.match(text)
    if done:
        needle = done.group(1).strip()
        if needle:
            return Intent(
                name=IntentName.PRODUCTIVITY,
                query=text,
                extra={"action": "tasks_done", "needle": needle},
            )

    return None


def classify_research(query: str) -> Intent | None:
    text = query.strip().lower()
    docs = _RESEARCH_DOCS.match(text)
    if docs:
        topic = docs.group(1).strip()
        if topic:
            return Intent(
                name=IntentName.RESEARCH,
                query=text,
                extra={"action": "docs", "query": topic},
            )
    report = _RESEARCH_REPORT.match(text)
    if report:
        # Defer browser "look up X on the web" and memory "look up X in my notes".
        if (
            _LOOKUP_ON_WEB.match(text)
            or _LOOKUP_ONLINE.match(text)
            or _SEARCH_ON_WEB.match(text)
            or _LOOKUP_NOTES_PATTERN.match(text)
        ):
            return None
        topic = report.group(1).strip()
        if topic and not topic.startswith("my document"):
            return Intent(
                name=IntentName.RESEARCH,
                query=text,
                extra={"action": "report", "query": topic},
            )
    return None


def _normalize_utterance(query: str) -> str:
    cleaned = re.sub(r"[,.!?]+", " ", query.strip().lower())
    return " ".join(cleaned.split())


_SELF_EMAIL_BLOCK = re.compile(
    r"\b(remind|reminder|note that|search my|what is my email|check my email|"
    r"read my email|connect|disconnect)\b"
)


def _looks_like_self_email(text: str) -> bool:
    """Catch STT cutoffs like 'send a email to my' without stealing other commands."""
    if _SELF_EMAIL_BLOCK.search(text):
        return False
    if not re.search(r"\b(e-?mails?|gmail)\b", text):
        return False
    if not re.search(r"\b(send|mail|email|draft|draught|compose)\b", text):
        return False
    if re.search(r"\b(myself|send me|to me|to myself)\b", text):
        return True
    if re.search(r"\b(?:e-?mail|gmail)s? to my\s*$", text):
        return True
    if re.search(r"^(?:please |friday |can you )*(?:draft|draught|compose) (?:an |a )?e?-?mail\s*$", text):
        return True
    return False


def classify_pending(query: str) -> Intent | None:
    """Yes / send it only when a high-risk send is waiting. Does not steal WhatsApp."""
    if get_pending() is None:
        return None
    pending_text = _normalize_utterance(query)
    if _CONFIRM_PENDING.match(pending_text):
        return Intent(
            name=IntentName.INTEGRATION,
            query=pending_text,
            extra={"action": "confirm_pending"},
        )
    if _CANCEL_PENDING.match(pending_text):
        return Intent(
            name=IntentName.INTEGRATION,
            query=pending_text,
            extra={"action": "cancel_pending"},
        )
    return None


def classify_integrations(query: str) -> Intent | None:
    text = query.strip().lower()
    text = re.sub(r"\bby saying\b", "saying", text)
    text = " ".join(text.split())

    connected = _CONNECT_INTEGRATION.match(text)
    if connected:
        return Intent(
            name=IntentName.INTEGRATION,
            query=text,
            extra={"action": "connect", "provider": connected.group(1)},
        )
    disconnected = _DISCONNECT_INTEGRATION.match(text)
    if disconnected:
        return Intent(
            name=IntentName.INTEGRATION,
            query=text,
            extra={"action": "disconnect", "provider": disconnected.group(1)},
        )
    if _CONNECT_AGAIN.match(text):
        return Intent(
            name=IntentName.INTEGRATION,
            query=text,
            extra={"action": "connect", "provider": "gmail"},
        )
    if _INTEGRATION_STATUS.match(text):
        return Intent(
            name=IntentName.INTEGRATION, query=text, extra={"action": "status"}
        )
    if _EMAIL_LIST.match(text):
        return Intent(
            name=IntentName.INTEGRATION, query=text, extra={"action": "email_list"}
        )
    self_body = _SELF_BODY_ONLY.match(text)
    if self_body:
        return Intent(
            name=IntentName.INTEGRATION,
            query=text,
            extra={
                "action": "email_send",
                "to": "me",
                "body": self_body.group(1).strip(),
            },
        )
    self_send = _EMAIL_TO_SELF.match(text)
    if self_send:
        return Intent(
            name=IntentName.INTEGRATION,
            query=text,
            extra={
                "action": "email_send",
                "to": "me",
                "body": (self_send.group(1) or "").strip(),
            },
        )
    emailed = _EMAIL_SEND.match(text)
    if emailed:
        return Intent(
            name=IntentName.INTEGRATION,
            query=text,
            extra={
                "action": "email_send",
                "to": _clean_email_recipient(emailed.group(1)),
                "body": emailed.group(2).strip(),
            },
        )
    about = _EMAIL_ABOUT.match(text)
    if about:
        subject = about.group(2).strip()
        return Intent(
            name=IntentName.INTEGRATION,
            query=text,
            extra={
                "action": "email_send",
                "to": _clean_email_recipient(about.group(1)),
                "subject": subject,
                "body": subject,
            },
        )
    addressed = _EMAIL_TO_ADDRESS.match(text)
    if addressed:
        return Intent(
            name=IntentName.INTEGRATION,
            query=text,
            extra={
                "action": "email_send",
                "to": addressed.group(1).strip(),
                "body": "",
            },
        )
    if _SEND_EMAIL_NOW.match(text):
        return Intent(
            name=IntentName.INTEGRATION,
            query=text,
            extra={"action": "email_send", "to": "me", "body": ""},
        )
    if _SEND_IT_TO_ME.match(text):
        return Intent(
            name=IntentName.INTEGRATION,
            query=text,
            extra={"action": "email_send", "to": "me", "body": ""},
        )
    if _looks_like_self_email(text):
        return Intent(
            name=IntentName.INTEGRATION,
            query=text,
            extra={"action": "email_send", "to": "me", "body": ""},
        )
    to_name = _EMAIL_TO_NAME.match(text)
    if to_name:
        recipient = _EMAIL_NAME_TAIL.sub("", to_name.group(1).strip()).strip()
        if recipient:
            return Intent(
                name=IntentName.INTEGRATION,
                query=text,
                extra={
                    "action": "email_send",
                    "to": _clean_email_recipient(recipient),
                    "body": "",
                },
            )
    slack = _SLACK_SEND.match(text)
    if slack:
        return Intent(
            name=IntentName.INTEGRATION,
            query=text,
            extra={
                "action": "slack_send",
                "channel": slack.group(1).strip().lstrip("#"),
                "body": slack.group(2).strip(),
            },
        )
    discord = _DISCORD_SEND.match(text)
    if discord:
        return Intent(
            name=IntentName.INTEGRATION,
            query=text,
            extra={
                "action": "discord_send",
                "target": discord.group(1).strip(),
                "body": discord.group(2).strip(),
            },
        )
    posted = _DISCORD_POST.match(text)
    if posted:
        extra = {"action": "discord_send", "body": posted.group(2).strip()}
        target = (posted.group(1) or "").strip()
        if target:
            extra["target"] = target
        return Intent(name=IntentName.INTEGRATION, query=text, extra=extra)

    return None


def classify_rules(query: str) -> Intent:
    """Keyword fast path. WhatsApp, laptop, vision, memory, files, then open."""
    original = query.strip()
    text = normalize_command(original).strip().lower()

    pending_intent = classify_pending(text)
    if pending_intent is not None:
        return pending_intent

    if "play" in text and "youtube" in text:
        return Intent(name=IntentName.YOUTUBE, query=text)

    media_intent = classify_media(text)
    if media_intent is not None:
        return media_intent

    if _is_whatsapp_request(text):
        return Intent(
            name=IntentName.WHATSAPP,
            query=text,
            extra={"action": classify_whatsapp_action(text)},
        )

    os_intent = classify_os(text)
    if os_intent is not None:
        return os_intent

    vision_intent = classify_vision(text)
    if vision_intent is not None:
        return vision_intent

    productivity_intent = classify_productivity(text)
    if productivity_intent is not None:
        return productivity_intent

    research_intent = classify_research(text)
    if research_intent is not None:
        return research_intent

    memory_intent = classify_memory(original)
    if memory_intent is not None:
        return memory_intent

    file_intent = classify_files(text)
    if file_intent is not None:
        return file_intent

    code_intent = classify_code(text)
    if code_intent is not None:
        return code_intent

    integration_intent = classify_integrations(text)
    if integration_intent is not None:
        return integration_intent

    browser_intent = classify_browser(text)
    if browser_intent is not None:
        return browser_intent

    weather_intent = classify_weather(text)
    if weather_intent is not None:
        return weather_intent

    news_intent = classify_news(text)
    if news_intent is not None:
        return news_intent

    open_intent = classify_open(text)
    if open_intent is not None:
        return open_intent

    if text in STOP_PHRASES:
        return Intent(name=IntentName.STOP, query=text)

    return Intent(name=IntentName.CHAT, query=original.lower())


def classify(query: str, llm_classify: LlmClassify | None = None) -> Intent:
    """Rules first; optional LLM only if rules fall through to chat.

    Production does not pass ``llm_classify`` yet, so unmatched utterances
    still go to the existing HuggingChat path.
    """
    intent = classify_rules(query)
    if intent.name is not IntentName.CHAT or llm_classify is None:
        return intent

    llm_intent = llm_classify(query)
    return llm_intent if llm_intent is not None else intent
