"""Compile and run simple source files Friday just wrote (Desktop, etc.)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from friday.memory.store import path_is_allowed
from friday.rag.extract import is_blocked

_RUNNABLE = {".cpp", ".cc", ".cxx", ".c", ".py"}
_TIMEOUT_SEC = 20.0
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_COMPILER_CANDIDATES = (
    Path(r"C:\MinGW\bin\g++.exe"),
    Path(r"C:\mingw64\bin\g++.exe"),
    Path(r"C:\msys64\mingw64\bin\g++.exe"),
    Path(r"C:\Program Files\mingw-w64\mingw64\bin\g++.exe"),
)


def find_cxx_compiler() -> str | None:
    for name in ("g++", "clang++", "c++"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in _COMPILER_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    return None


def run_source_file(
    path: Path,
    allow_paths: tuple[Path, ...],
) -> tuple[bool, str]:
    """Compile if needed, run, return ``(ok, spoken_reply)``."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return False, f"I couldn't find {path.name}."
    if is_blocked(resolved):
        return False, "That file type is blocked."
    if not path_is_allowed(resolved, allow_paths):
        return False, "That path is outside the allowed folders."
    suffix = resolved.suffix.lower()
    if suffix not in _RUNNABLE:
        return False, f"I can only compile and run .cpp, .c, or .py files, not {suffix or 'that'}."

    if suffix == ".py":
        return _run_python(resolved)
    return _compile_and_run_cxx(resolved)


def _run_python(path: Path) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(path.parent),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SEC,
            check=False,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return False, f"{path.name} timed out while running."
    except OSError as error:
        return False, f"I couldn't run {path.name}: {error}"
    return _format_run(path.name, completed.returncode, completed.stdout, completed.stderr)


def _compile_and_run_cxx(path: Path) -> tuple[bool, str]:
    compiler = find_cxx_compiler()
    if not compiler:
        return (
            False,
            "I couldn't find a C++ compiler. Install MinGW g++ and add it to PATH.",
        )
    exe = path.with_suffix(".exe")
    try:
        built = subprocess.run(
            [compiler, str(path), "-o", str(exe)],
            cwd=str(path.parent),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SEC,
            check=False,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return False, f"Compiling {path.name} timed out."
    except OSError as error:
        return False, f"I couldn't compile {path.name}: {error}"
    if built.returncode != 0:
        err = (built.stderr or built.stdout or "unknown error").strip()
        short = err.splitlines()[-1] if err else "unknown error"
        return False, f"Compile failed for {path.name}: {short}"

    try:
        completed = subprocess.run(
            [str(exe)],
            cwd=str(path.parent),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SEC,
            check=False,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return False, f"{path.name} compiled, but running it timed out."
    except OSError as error:
        return False, f"{path.name} compiled, but I couldn't run it: {error}"
    finally:
        try:
            if exe.is_file():
                exe.unlink()
        except OSError:
            pass
    return _format_run(path.name, completed.returncode, completed.stdout, completed.stderr)


def _format_run(
    name: str,
    returncode: int,
    stdout: str | None,
    stderr: str | None,
) -> tuple[bool, str]:
    out = (stdout or "").strip()
    err = (stderr or "").strip()
    if returncode != 0:
        detail = err or out or f"exit code {returncode}"
        short = detail.splitlines()[-1]
        return False, f"{name} exited with an error: {short}"
    if out:
        spoken = out if len(out) <= 240 else out[:237] + "..."
        return True, f"Ran {name}. Output: {spoken}"
    return True, f"Ran {name} successfully with no output."
