"""Resolve a spoken contact name to a stored email address.

WhatsApp stores contacts as name + phone; the ``contacts`` table also has an
``email`` column that the CSV importer now fills from Google's
``E-mail N - Value`` fields. Emailing someone by name reads that column here,
so "send email to Kabir" no longer demands a full address out loud.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from friday.integrations.address import looks_like_email

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "friday.db"

# Spoken family words → the name stored in the contacts table.
_NAME_ALIASES = {
    "mom": "mummy",
    "mum": "mummy",
    "mother": "mummy",
    "mama": "mummy",
    "maa": "mummy",
    "mommy": "mummy",
    "dad": "papa",
    "daddy": "papa",
    "father": "papa",
    "pa": "papa",
}


@dataclass(frozen=True)
class ContactEmail:
    """Outcome of a name lookup.

    ``matched`` is True when a contact with that name exists at all, so the
    caller can tell "no such person" apart from "I know them but have no email".
    """

    email: str | None
    name: str | None
    matched: bool

    @property
    def has_email(self) -> bool:
        return bool(self.email)


def _lookup_keys(raw_name: str) -> list[str]:
    query = " ".join(str(raw_name).strip().lower().split())
    if query.startswith("my ") and len(query) > 3:
        query = query[3:].strip()
    if not query:
        return []
    keys = [query]
    alias = _NAME_ALIASES.get(query)
    if alias and alias not in keys:
        keys.append(alias)
    return keys


def resolve_contact_email(
    raw_name: str,
    db_path: Path | str | None = None,
) -> ContactEmail:
    keys = _lookup_keys(raw_name)
    if not keys:
        return ContactEmail(email=None, name=None, matched=False)

    database = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    if not database.is_file():
        return ContactEmail(email=None, name=None, matched=False)

    last_miss: ContactEmail | None = None
    for query in keys:
        hit = _lookup_one(query, database)
        if hit.has_email:
            return hit
        if hit.matched:
            last_miss = hit
    if last_miss is not None:
        return last_miss
    return ContactEmail(email=None, name=None, matched=False)


def _lookup_one(query: str, database: Path) -> ContactEmail:
    first_token = query.split()[0]
    try:
        with sqlite3.connect(database) as connection:
            row = connection.execute(
                """
                SELECT name, email FROM contacts
                WHERE name IS NOT NULL
                  AND (name = ? COLLATE NOCASE OR name LIKE ? COLLATE NOCASE)
                ORDER BY
                    CASE WHEN name = ? COLLATE NOCASE THEN 0 ELSE 1 END,
                    LENGTH(name),
                    name
                LIMIT 1
                """,
                (query, f"{first_token}%", query),
            ).fetchone()
    except sqlite3.Error:
        return ContactEmail(email=None, name=None, matched=False)

    if row is None:
        return ContactEmail(email=None, name=None, matched=False)

    name = str(row[0]).strip()
    stored = str(row[1] or "").strip()
    email = stored if looks_like_email(stored) else None
    return ContactEmail(email=email, name=name, matched=True)
