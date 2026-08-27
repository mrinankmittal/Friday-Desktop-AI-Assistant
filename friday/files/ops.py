"""Allowlisted file search / read / write / move. No shell."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from friday.memory.store import path_is_allowed
from friday.rag.extract import MAX_BYTES, extract_text, is_blocked

_SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "envfriday",
    "node_modules",
    "__pycache__",
    ".cursor",
    ".edge-test",
    "appdata",
    "windows",
}
_WRITE_SUFFIXES = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".py",
    ".log",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".ts",
    ".html",
    ".css",
}
_FOLDER_ALIASES = {
    "downloads": "Downloads",
    "download": "Downloads",
    "documents": "Documents",
    "docs": "Documents",
    "desktop": "Desktop",
    "pictures": "Pictures",
    "photos": "Pictures",
}
MAX_WALK = 4000
MAX_HITS = 12
MAX_DEPTH = 6
READ_SPEAK_CHARS = 500


def folder_alias(name: str, home: Path | None = None) -> Path | None:
    key = name.strip().lower().rstrip("\\/")
    if key in {"repo", "the repo", "this repo", "workspace", "project", "this project"}:
        from friday.providers.types import project_root

        return project_root()
    mapped = _FOLDER_ALIASES.get(key)
    if mapped is None:
        return None
    root = home or Path.home()
    return root / mapped


def day_window(label: str, *, now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or datetime.now().astimezone()
    start_today = current.replace(hour=0, minute=0, second=0, microsecond=0)
    if label == "yesterday":
        start = start_today - timedelta(days=1)
        return start, start_today
    if label == "today":
        return start_today, start_today + timedelta(days=1)
    raise ValueError(f"Unknown day window: {label}")


def resolve_user_path(
    raw: str,
    *,
    allow_paths: tuple[Path, ...],
    extra_roots: tuple[Path, ...] = (),
) -> Path:
    cleaned = raw.strip().strip('"').strip("'")
    if not cleaned:
        raise FileNotFoundError("I need a file path.")
    candidate = Path(cleaned).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
        _assert_readable(resolved, allow_paths)
        return resolved

    roots = extra_roots + allow_paths
    name = candidate.name
    for root in roots:
        direct = (root / candidate).resolve()
        if direct.is_file() and path_is_allowed(direct, allow_paths):
            return direct
        for found in _walk(root, allow_paths):
            if found.name.lower() == name.lower():
                return found
    raise FileNotFoundError(f"I couldn't find {cleaned}")


def search_files(
    *,
    needle: str = "",
    folder: Path | None = None,
    allow_paths: tuple[Path, ...],
    after: datetime | None = None,
    before: datetime | None = None,
    limit: int = MAX_HITS,
) -> list[Path]:
    roots = (folder,) if folder is not None else allow_paths
    needle_l = needle.strip().lower()
    hits: list[tuple[float, Path]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in _walk(root, allow_paths):
            if needle_l and needle_l not in path.name.lower():
                continue
            mtime = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
            if after is not None and mtime < after:
                continue
            if before is not None and mtime >= before:
                continue
            hits.append((mtime.timestamp(), path))
    hits.sort(key=lambda item: item[0], reverse=True)
    return [path for _mtime, path in hits[:limit]]


def read_file(path: Path, allow_paths: tuple[Path, ...]) -> str:
    resolved = path.expanduser().resolve()
    _assert_readable(resolved, allow_paths)
    if resolved.stat().st_size > MAX_BYTES:
        raise ValueError("That file is too large to read.")
    return extract_text(resolved)


def write_file(
    path: Path,
    text: str,
    allow_paths: tuple[Path, ...],
) -> Path:
    resolved = path.expanduser().resolve()
    if is_blocked(resolved):
        raise PermissionError("That file type is blocked.")
    if resolved.suffix.lower() not in _WRITE_SUFFIXES:
        raise PermissionError("I can only write text files like .txt or .md.")
    if not path_is_allowed(resolved, allow_paths):
        raise PermissionError("That path is outside the allowed folders.")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(text, encoding="utf-8")
    return resolved


def move_file(
    source: Path,
    destination: Path,
    allow_paths: tuple[Path, ...],
) -> Path:
    src = source.expanduser().resolve()
    dest = destination.expanduser().resolve()
    _assert_readable(src, allow_paths)
    if is_blocked(dest) or is_blocked(src):
        raise PermissionError("That file type is blocked.")
    if not path_is_allowed(dest, allow_paths):
        raise PermissionError("That path is outside the allowed folders.")
    if dest.is_dir():
        dest = dest / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return dest


def copy_file(
    source: Path,
    destination: Path,
    allow_paths: tuple[Path, ...],
) -> Path:
    src = source.expanduser().resolve()
    dest = destination.expanduser()
    _assert_readable(src, allow_paths)
    if is_blocked(src):
        raise PermissionError("That file type is blocked.")
    if dest.exists() and dest.is_dir():
        dest = dest / src.name
    elif not dest.suffix:
        dest.mkdir(parents=True, exist_ok=True)
        dest = dest / src.name
    dest = dest.resolve()
    if is_blocked(dest):
        raise PermissionError("That file type is blocked.")
    if not path_is_allowed(dest, allow_paths):
        raise PermissionError("That path is outside the allowed folders.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dest))
    return dest


def make_directory(
    path: Path,
    allow_paths: tuple[Path, ...],
) -> Path:
    resolved = path.expanduser().resolve()
    if not path_is_allowed(resolved, allow_paths):
        raise PermissionError("That path is outside the allowed folders.")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def format_search_hits(paths: list[Path], *, needle: str = "") -> str:
    if not paths:
        topic = f" matching {needle}" if needle else ""
        return f"I didn't find any files{topic}."
    parts = [f"{path.name} in {path.parent}" for path in paths[:MAX_HITS]]
    spoken = f"I found {len(paths)} file{'s' if len(paths) != 1 else ''}. "
    return spoken + " ".join(parts)


def format_read(path: Path, text: str) -> str:
    snippet = text.strip() or "(empty file)"
    if len(snippet) > READ_SPEAK_CHARS:
        snippet = snippet[: READ_SPEAK_CHARS - 3] + "..."
    return f"From {path.name}: {snippet}"


def _assert_readable(path: Path, allow_paths: tuple[Path, ...]) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"I couldn't find {path}")
    if is_blocked(path):
        raise PermissionError("That file type is blocked.")
    if not path_is_allowed(path, allow_paths):
        raise PermissionError("That path is outside the allowed folders.")


def _walk(root: Path, allow_paths: tuple[Path, ...]):
    try:
        resolved_root = root.expanduser().resolve()
    except OSError:
        return
    if not resolved_root.exists():
        return
    scanned = [0]
    yield from _walk_inner(resolved_root, allow_paths, 0, scanned)


def _walk_inner(
    folder: Path,
    allow_paths: tuple[Path, ...],
    depth: int,
    scanned: list[int],
):
    if depth > MAX_DEPTH or scanned[0] >= MAX_WALK:
        return
    try:
        entries = list(folder.iterdir())
    except OSError:
        return
    for entry in entries:
        if scanned[0] >= MAX_WALK:
            return
        try:
            if entry.is_dir():
                if entry.name.lower() in _SKIP_DIR_NAMES:
                    continue
                if not path_is_allowed(entry, allow_paths) and not _contains_allow(
                    entry, allow_paths
                ):
                    continue
                yield from _walk_inner(entry, allow_paths, depth + 1, scanned)
            elif entry.is_file():
                scanned[0] += 1
                if path_is_allowed(entry, allow_paths) and not is_blocked(entry):
                    yield entry
        except OSError:
            continue


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.expanduser().resolve())
        return True
    except ValueError:
        return False


def _contains_allow(folder: Path, allow_paths: tuple[Path, ...]) -> bool:
    return any(_is_under(allowed, folder) for allowed in allow_paths)
