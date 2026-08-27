"""Discover every app Windows lists in "All apps" and make Friday open it.

``Get-StartApps`` returns the exact list the Start menu shows -- Win32 desktop
apps *and* Microsoft Store (UWP) apps -- as ``(Name, AppID)`` pairs. Store apps
like Spotify and WhatsApp have no Start Menu ``.lnk`` at all; they exist only
here as an AppID (AUMID). Every entry, Win32 or UWP, launches uniformly with
``os.startfile(r"shell:AppsFolder\\<AppID>")``, which is what ``execute_open``
already does, so the scanner just records that target string per app.

The sync is additive and re-runnable: new apps are inserted, names already in
the catalog are left untouched (so hand-curated rows and user edits survive),
and re-running after installing something new picks up only the new apps.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

APPS_FOLDER_PREFIX = "shell:AppsFolder\\"

# Start-menu entries that are not really apps you would say "open ..." to.
_NOISE_TERMS = (
    "uninstall",
    "read me",
    "readme",
    "release notes",
    "documentation",
    "user guide",
    "user's guide",
    "quick start",
    "getting started",
    "license",
    "licence",
    "website",
    "web site",
    "home page",
    "homepage",
    "on the web",
    "visit ",
    "modify ",
    "repair ",
    "change ",
)

_GET_START_APPS = (
    "Get-StartApps | "
    "Select-Object Name, AppID | "
    "ConvertTo-Json -Compress -Depth 2"
)

Runner = Callable[[], str]


@dataclass(frozen=True)
class AppEntry:
    """One launchable app: a spoken ``name`` and the shell target to open it."""

    name: str
    app_id: str

    @property
    def target(self) -> str:
        return f"{APPS_FOLDER_PREFIX}{self.app_id}"


@dataclass(frozen=True)
class SyncResult:
    discovered: int
    added: int
    skipped_existing: int
    skipped_noise: int

    @property
    def summary(self) -> str:
        return (
            f"{self.added} new app(s) added, "
            f"{self.skipped_existing} already known, "
            f"{self.skipped_noise} skipped as non-apps "
            f"({self.discovered} entries seen)."
        )


def is_noise_name(name: str) -> bool:
    """True for uninstallers, help links, and other non-app Start entries."""
    lowered = f" {name.strip().lower()} "
    return any(term in lowered for term in _NOISE_TERMS)


def parse_start_apps(raw_json: str) -> list[AppEntry]:
    """Turn ``Get-StartApps | ConvertTo-Json`` output into clean app entries.

    Drops entries without a name or AppID, drops obvious non-apps, and keeps
    the first spelling seen for any duplicated (case-insensitive) name.
    """
    text = (raw_json or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return []

    entries: list[AppEntry] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or "").strip()
        app_id = str(item.get("AppID") or "").strip()
        if not name or not app_id:
            continue
        if is_noise_name(name):
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        entries.append(AppEntry(name=name, app_id=app_id))
    return entries


def discover_apps(runner: Runner | None = None) -> list[AppEntry]:
    """Discover installed apps. ``runner`` is injectable for tests."""
    raw = (runner or _default_runner)()
    return parse_start_apps(raw)


def sync_app_catalog(
    db_path: Path | str,
    *,
    apps: Iterable[AppEntry] | None = None,
    runner: Runner | None = None,
) -> SyncResult:
    """Add discovered apps to ``sys_command`` without disturbing existing rows."""
    entries = list(apps) if apps is not None else discover_apps(runner)
    discovered = len(entries)

    database = Path(db_path)
    database.parent.mkdir(parents=True, exist_ok=True)
    added = skipped_existing = 0
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sys_command (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                path VARCHAR(1000) NOT NULL
            )
            """
        )
        # lookup_open_target reads both catalogs; keep a scan-only DB complete.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS web_command (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100),
                url VARCHAR(1000)
            )
            """
        )
        existing = {
            str(row[0]).casefold()
            for row in connection.execute("SELECT name FROM sys_command")
        }
        for entry in entries:
            if entry.name.casefold() in existing:
                skipped_existing += 1
                continue
            connection.execute(
                "INSERT INTO sys_command (name, path) VALUES (?, ?)",
                (entry.name, entry.target),
            )
            existing.add(entry.name.casefold())
            added += 1
        connection.commit()

    return SyncResult(
        discovered=discovered,
        added=added,
        skipped_existing=skipped_existing,
        skipped_noise=0,
    )


def _default_runner() -> str:
    """Ask PowerShell for the Start menu app list as JSON."""
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            _GET_START_APPS,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Get-StartApps failed: "
            + (completed.stderr.strip() or "unknown PowerShell error")
        )
    return completed.stdout


def _cli(argv: list[str]) -> int:
    from friday.os_adapters.apps import DEFAULT_DB_PATH

    db_path = Path(argv[0]) if argv else DEFAULT_DB_PATH
    print(f"Scanning installed apps into {db_path} ...")
    try:
        result = sync_app_catalog(db_path)
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"Scan failed: {error}")
        return 1
    print(result.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
