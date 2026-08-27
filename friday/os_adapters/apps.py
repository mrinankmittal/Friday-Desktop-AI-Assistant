from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from friday.os_adapters.types import OsAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "friday.db"

# Spoken leftovers after stripping "open". Not real app names.
INCOMPLETE_OPEN_TARGETS = frozenset({"", "the", "a", "an", "my", "that", "this"})

_OPEN_ALIASES = {
    "task manager": "taskmgr",
    "the task manager": "taskmgr",
    "taskmgr": "taskmgr",
    "the task": "taskmgr",
    "task": "taskmgr",
}

_CALENDAR_NAMES = frozenset(
    {
        "calendar",
        "the calendar",
        "my calendar",
        "windows calendar",
        "one calendar",
    }
)
_OUTLOOK_CALENDAR_NAMES = frozenset({"outlook calendar", "outlook cal"})
# BlueEdge One Calendar (Microsoft Store) — preferred for "open calendar".
_ONE_CALENDAR_AUMID = "64885BlueEdge.OneCalendar_8kea50m9krsh2!App"
_CLASSIC_CALENDAR_AUMID = (
    "microsoft.windowscommunicationsapps_8wekyb3d8bbwe!"
    "microsoft.windowslive.calendar"
)


def lookup_open_target(
    app_name: str,
    db_path: Path | None = None,
) -> tuple[str, str]:
    """Resolve a spoken app/site name to a launch kind and target.

    Returns ``("path", filesystem_path)``, ``("url", url)``, or
    ``("name", original_name)`` so the adapter can ``startfile`` it.
    """
    name = app_name.strip()
    if not name or name.lower() in INCOMPLETE_OPEN_TARGETS:
        return ("name", "")

    cleaned = " ".join(name.lower().split())
    if cleaned in _OUTLOOK_CALENDAR_NAMES:
        resolved = _resolve_outlook_calendar(db_path)
        if resolved is not None:
            return resolved
    if cleaned in _CALENDAR_NAMES:
        resolved = _resolve_calendar(db_path)
        if resolved is not None:
            return resolved

    resolved = _lookup_catalog(name, db_path)
    if resolved is not None:
        return resolved

    alias = _OPEN_ALIASES.get(cleaned)
    if alias:
        resolved = _lookup_catalog(alias, db_path)
        if resolved is not None:
            return resolved
        taskmgr = _taskmgr_path()
        if taskmgr is not None:
            return ("path", str(taskmgr))
        return ("name", alias)

    fuzzy = _fuzzy_catalog_match(name, db_path)
    if fuzzy is not None:
        return fuzzy
    return ("name", name)


def _one_calendar_target() -> tuple[str, str]:
    return ("path", f"shell:AppsFolder\\{_ONE_CALENDAR_AUMID}")


def _resolve_calendar(db_path: Path | None) -> tuple[str, str] | None:
    """Prefer One Calendar, then other calendar catalog entries."""
    for label in ("One Calendar", "Calendar", "Windows Calendar"):
        hit = _lookup_catalog(label, db_path)
        if hit is not None:
            return hit
    # Store app AUMID so "open calendar" works even before scan-apps.
    return _one_calendar_target()


def _resolve_outlook_calendar(db_path: Path | None) -> tuple[str, str] | None:
    outlook = _lookup_catalog("Outlook", db_path)
    if outlook is not None:
        return outlook
    return (
        "path",
        f"shell:AppsFolder\\{_CLASSIC_CALENDAR_AUMID}",
    )


def _lookup_catalog(
    name: str,
    db_path: Path | None,
) -> tuple[str, str] | None:
    database = db_path or DEFAULT_DB_PATH
    if not database.is_file():
        return None
    with sqlite3.connect(database) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT path FROM sys_command WHERE name = ? COLLATE NOCASE LIMIT 1",
            (name,),
        )
        path_row = cursor.fetchone()
        cursor.execute(
            "SELECT url FROM web_command WHERE name = ? COLLATE NOCASE LIMIT 1",
            (name,),
        )
        url_row = cursor.fetchone()
    if path_row and str(path_row[0]).strip():
        return ("path", str(path_row[0]).strip())
    if url_row and str(url_row[0]).strip():
        return ("url", str(url_row[0]).strip())
    return None


def _fuzzy_catalog_match(
    name: str,
    db_path: Path | None,
) -> tuple[str, str] | None:
    """Resolve a short spoken name to a catalog entry when there is no exact hit.

    The scanner stores full names like "Google Chrome" and "Visual Studio Code",
    but people say "chrome" and "vs code". This scores every catalog name against
    the spoken words and returns the best confident match, preferring the
    shortest (most specific) name on ties so "word" beats "wordpad".
    """
    query = " ".join(name.lower().split())
    if len(query) < 3:
        return None

    database = db_path or DEFAULT_DB_PATH
    if not database.is_file():
        return None

    with sqlite3.connect(database) as connection:
        sys_rows = connection.execute(
            "SELECT name, path FROM sys_command WHERE name != '' AND path != ''"
        ).fetchall()
        web_rows = connection.execute(
            "SELECT name, url FROM web_command WHERE name != '' AND url != ''"
        ).fetchall()

    best: tuple[int, int, str] | None = None
    best_hit: tuple[str, str] | None = None
    for kind, rows in (("path", sys_rows), ("url", web_rows)):
        for raw_name, target in rows:
            candidate = str(raw_name)
            score = _match_score(query, candidate.lower())
            if score <= 0:
                continue
            rank = (score, -len(candidate), candidate.lower())
            if best is None or rank > best:
                best = rank
                best_hit = (kind, str(target).strip())

    return best_hit


def _match_score(query: str, candidate: str) -> int:
    """Confidence that a spoken ``query`` means catalog ``candidate``.

    Higher is better; ``0`` means no match. Word-level hits beat loose
    substrings so "edge" prefers "Microsoft Edge" over "Edge WebView".
    """
    if not candidate:
        return 0
    if query == candidate:
        return 100
    words = candidate.split()
    if candidate.startswith(query + " "):
        return 90
    if query in words:
        return 80
    query_words = query.split()
    if len(query_words) > 1 and all(word in words for word in query_words):
        return 70
    if any(word.startswith(query) for word in words):
        return 60
    if len(query) >= 4 and query in candidate:
        return 40
    if len(candidate) >= 4 and candidate in query:
        return 30
    return 0


def _taskmgr_path() -> Path | None:
    root = Path(os.environ.get("SystemRoot") or r"C:\Windows")
    candidate = root / "System32" / "taskmgr.exe"
    if candidate.is_file():
        return candidate
    return None


def execute_open(kind: str, target: str, adapter: OsAdapter) -> bool:
    if kind == "url":
        return adapter.open_url(target)
    adapter.open_path(target)
    return True
