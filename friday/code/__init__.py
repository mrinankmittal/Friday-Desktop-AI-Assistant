"""Workspace-scoped code read / patch / unittest. No arbitrary shell."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from friday.memory.store import path_is_allowed
from friday.providers.types import project_root
from friday.rag.extract import MAX_BYTES, is_blocked

_MODULE_NAME = re.compile(r"^[A-Za-z_][\w.]*$")
_SKIP_DIR_NAMES = {".git", ".venv", "envfriday", "node_modules", "__pycache__"}
READ_SPEAK_CHARS = 700
TEST_TIMEOUT_SEC = 90


def workspace_root() -> Path:
    configured = os.environ.get("FRIDAY_WORKSPACE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return project_root()


def resolve_workspace_file(raw: str, workspace: Path) -> Path:
    cleaned = raw.strip().strip('"').strip("'").replace("\\", "/")
    if not cleaned:
        raise FileNotFoundError("I need a file in this project.")
    candidate = Path(cleaned)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        direct = (workspace / candidate).resolve()
        if direct.is_file():
            resolved = direct
        else:
            resolved = _find_by_name(workspace, candidate.name)
    if resolved is None or not resolved.is_file():
        raise FileNotFoundError(f"I couldn't find {cleaned} in this project.")
    if not path_is_allowed(resolved, (workspace,)):
        raise PermissionError("That file is outside the project workspace.")
    if is_blocked(resolved):
        raise PermissionError("That file type is blocked.")
    return resolved


def read_workspace_file(path: Path, workspace: Path) -> str:
    resolved = resolve_workspace_file(str(path), workspace)
    if resolved.stat().st_size > MAX_BYTES:
        raise ValueError("That file is too large to read.")
    return resolved.read_text(encoding="utf-8", errors="replace")


def patch_workspace_file(
    path: Path,
    old: str,
    new: str,
    workspace: Path,
) -> Path:
    resolved = resolve_workspace_file(str(path), workspace)
    if is_blocked(resolved):
        raise PermissionError("That file type is blocked.")
    text = resolved.read_text(encoding="utf-8", errors="replace")
    count = text.count(old)
    if count == 0:
        raise ValueError("I didn't find that text in the file.")
    if count > 1:
        raise ValueError("That text appears more than once. Be more specific.")
    resolved.write_text(text.replace(old, new, 1), encoding="utf-8")
    return resolved


def unittest_argv(target: str = "") -> list[str]:
    cleaned = target.strip()
    if not cleaned:
        return [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
    if not _MODULE_NAME.match(cleaned) or ".." in cleaned:
        raise ValueError("I can only run a unittest module name.")
    module = cleaned
    if module != "tests" and not module.startswith("tests."):
        module = f"tests.{module}"
    if module == "tests":
        return [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
    return [sys.executable, "-m", "unittest", module]


def run_unittests(workspace: Path, target: str = "") -> tuple[int, str]:
    tests_dir = workspace / "tests"
    if not tests_dir.is_dir():
        raise FileNotFoundError("I didn't find a tests folder in this project.")
    argv = unittest_argv(target)
    try:
        completed = subprocess.run(
            argv,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SEC,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError("The tests timed out.") from error
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode, output.strip()


def format_code_read(path: Path, text: str) -> str:
    snippet = text.strip() or "(empty file)"
    if len(snippet) > READ_SPEAK_CHARS:
        snippet = snippet[: READ_SPEAK_CHARS - 3] + "..."
    return f"From {path.as_posix()}: {snippet}"


def format_test_output(returncode: int, output: str) -> str:
    lines = [line for line in output.splitlines() if line.strip()]
    tail = " ".join(lines[-4:]) if lines else "No test output."
    if returncode == 0:
        return f"Tests passed. {tail}"
    return f"Tests failed. {tail}"


def explain_workspace_file(path: Path, workspace: Path, *, focus: str = "") -> str:
    """Short spoken explanation of a workspace file via the local LLM."""
    from friday.providers.llm import complete_chat

    text = read_workspace_file(path, workspace)
    snippet = text.strip()
    if len(snippet) > 3500:
        snippet = snippet[:3500] + "\n..."
    hint = focus.strip() or "what this file does"
    prompt = (
        f"Explain briefly for a voice assistant ({hint}). "
        f"Keep it under 4 short sentences. File {path.name}:\n\n{snippet}"
    )
    return complete_chat(prompt).strip() or f"I read {path.name}, but had nothing to say."


def _find_by_name(workspace: Path, name: str) -> Path | None:
    lowered = name.lower()
    for folder, _dirs, files in os.walk(workspace):
        folder_path = Path(folder)
        if folder_path.name.lower() in _SKIP_DIR_NAMES:
            _dirs[:] = []
            continue
        _dirs[:] = [item for item in _dirs if item.lower() not in _SKIP_DIR_NAMES]
        for filename in files:
            if filename.lower() == lowered:
                return folder_path / filename
    return None
