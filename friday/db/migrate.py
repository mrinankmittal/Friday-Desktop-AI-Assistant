from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def apply_migrations(
    connection: sqlite3.Connection,
    migrations_dir: Path | None = None,
) -> list[str]:
    """Apply numbered ``*.sql`` files once. Safe to call on every connect."""
    folder = migrations_dir or MIGRATIONS_DIR
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied = {
        str(row[0])
        for row in connection.execute("SELECT version FROM schema_migrations")
    }
    newly: list[str] = []
    for path in sorted(folder.glob("*.sql")):
        version = path.stem
        if version in applied:
            continue
        connection.executescript(path.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, _utc_now()),
        )
        newly.append(version)
    connection.commit()
    return newly
