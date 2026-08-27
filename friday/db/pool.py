"""One writer at a time, per database file.

SQLite allows many readers but only one writer. Friday now touches the same
file from the Eel bridge thread, the voice worker, the reminder sweep, and the
separate hotword process, so every statement goes through a per-path lock.
WAL mode keeps readers from queueing behind that writer.

This module also stops the two costs that used to be paid on *every* call:
re-running the migration scan, and leaking the connection afterwards
(``with sqlite3.connect(...)`` commits but never closes).
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from friday.db.migrate import apply_migrations

BUSY_TIMEOUT_MS = 5000

_registry_lock = threading.Lock()
_guards: dict[str, threading.RLock] = {}
_prepared: set[str] = set()


def _key(db_path: Path) -> str:
    return str(Path(db_path).expanduser().resolve())


def _guard_for(key: str) -> threading.RLock:
    with _registry_lock:
        guard = _guards.get(key)
        if guard is None:
            guard = threading.RLock()
            _guards[key] = guard
        return guard


def _open(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        str(db_path),
        timeout=BUSY_TIMEOUT_MS / 1000,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return connection


def _prepare(db_path: Path, key: str, connection: sqlite3.Connection) -> None:
    """Apply migrations and durable pragmas once per path, not once per call."""
    if key in _prepared:
        return
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        # journal_mode is stored in the file header, so this survives reconnects.
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.DatabaseError:
        pass
    apply_migrations(connection)
    _prepared.add(key)


class Session:
    """Context manager that holds the write lock for the whole transaction.

    Entering yields a real ``sqlite3.Connection``, so every existing
    ``with connect(path) as connection:`` call site keeps working unchanged.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._key = _key(db_path)
        self._guard = _guard_for(self._key)
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        self._guard.acquire()
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = _open(self._db_path)
            _prepare(self._db_path, self._key, connection)
        except BaseException:
            self._guard.release()
            raise
        self._connection = connection
        return connection

    def __exit__(self, exc_type, exc, traceback) -> bool:
        connection = self._connection
        self._connection = None
        try:
            if connection is not None:
                try:
                    if exc_type is None:
                        connection.commit()
                    else:
                        connection.rollback()
                finally:
                    connection.close()
        finally:
            self._guard.release()
        return False


def session(db_path: Path) -> Session:
    return Session(db_path)


def forget(db_path: Path) -> None:
    """Drop cached migration state for one path. Used by tests."""
    key = _key(db_path)
    with _registry_lock:
        _prepared.discard(key)
        _guards.pop(key, None)


def reset() -> None:
    """Drop all cached state. Used by tests between temporary databases."""
    with _registry_lock:
        _prepared.clear()
        _guards.clear()
