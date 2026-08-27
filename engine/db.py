import csv
import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "friday.db"
CONTACTS_CSV_PATH = PROJECT_ROOT / "contacts (1).csv"

_EMAIL_COLUMN = re.compile(r"^E-?mail\s*\d+\s*-\s*Value$", re.IGNORECASE)
_EMAIL_PATTERN = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.IGNORECASE)


@dataclass(frozen=True)
class ImportResult:
    inserted: int
    updated: int
    skipped: int
    with_email: int

    def as_tuple(self) -> tuple[int, int]:
        # Backwards-compatible (inserted, skipped) pair for older callers.
        return self.inserted, self.skipped

    @property
    def summary(self) -> str:
        return (
            f"{self.inserted} added, {self.updated} updated with an email, "
            f"{self.skipped} skipped; {self.with_email} contact(s) now have an email."
        )


def _email_columns(fieldnames: list[str]) -> list[str]:
    return [name for name in fieldnames if _EMAIL_COLUMN.match(name.strip())]


def _first_email(row: dict[str, str], columns: list[str]) -> str:
    """First syntactically valid address across the E-mail N columns.

    Google sometimes packs several addresses into one cell separated by
    " ::: ", so scan each cell for the first that looks like an email.
    """
    for column in columns:
        raw = (row.get(column) or "").strip()
        if not raw:
            continue
        for part in re.split(r"\s*:::\s*|\s*,\s*|\s+", raw):
            match = _EMAIL_PATTERN.search(part)
            if match:
                return match.group(0).lower()
    return ""


def import_contacts() -> ImportResult:
    """Import named contacts (and their email) from a Google-style CSV.

    New contacts are inserted; contacts already present get their email
    filled in when the CSV has one and the database does not.
    """
    if not CONTACTS_CSV_PATH.is_file():
        raise FileNotFoundError(f"Contacts CSV not found: {CONTACTS_CSV_PATH}")

    inserted = 0
    updated = 0
    skipped = 0

    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY,
                name VARCHAR(200),
                mobile_no VARCHAR(255),
                email VARCHAR(255) NULL
            )
            """
        )

        with CONTACTS_CSV_PATH.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as csv_file:
            reader = csv.DictReader(csv_file)
            fieldnames = list(reader.fieldnames or [])
            required_columns = {"First Name", "Phone 1 - Value"}
            missing_columns = required_columns.difference(fieldnames)

            if missing_columns:
                missing = ", ".join(sorted(missing_columns))
                raise ValueError(f"Contacts CSV is missing columns: {missing}")

            email_columns = _email_columns(fieldnames)

            for row_number, row in enumerate(reader, start=2):
                name = " ".join(
                    part.strip()
                    for part in (
                        row.get("First Name", ""),
                        row.get("Middle Name", ""),
                        row.get("Last Name", ""),
                    )
                    if part and part.strip()
                )
                mobile_no = (row.get("Phone 1 - Value") or "").strip()
                email = _first_email(row, email_columns)

                if not name or not mobile_no:
                    logging.warning(
                        "Skipping incomplete contact on CSV row %s",
                        row_number,
                    )
                    skipped += 1
                    continue

                existing = cursor.execute(
                    """
                    SELECT id, email FROM contacts
                    WHERE name = ? COLLATE NOCASE AND mobile_no = ?
                    LIMIT 1
                    """,
                    (name, mobile_no),
                ).fetchone()

                if existing:
                    contact_id, stored_email = existing
                    if email and not (stored_email or "").strip():
                        cursor.execute(
                            "UPDATE contacts SET email = ? WHERE id = ?",
                            (email, contact_id),
                        )
                        updated += 1
                    else:
                        skipped += 1
                    continue

                cursor.execute(
                    "INSERT INTO contacts (name, mobile_no, email) VALUES (?, ?, ?)",
                    (name, mobile_no, email or None),
                )
                inserted += 1

        with_email = cursor.execute(
            "SELECT COUNT(*) FROM contacts WHERE email IS NOT NULL AND TRIM(email) != ''"
        ).fetchone()[0]

    return ImportResult(
        inserted=inserted,
        updated=updated,
        skipped=skipped,
        with_email=int(with_email),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    result = import_contacts()
    logging.info("Contact import complete: %s", result.summary)
    if result.with_email == 0:
        logging.warning(
            "No contact has an email yet. Re-export from Google Contacts with the "
            "'E-mail 1 - Value' column included, replace %s, and run this again.",
            CONTACTS_CSV_PATH.name,
        )


if __name__ == "__main__":
    main()
