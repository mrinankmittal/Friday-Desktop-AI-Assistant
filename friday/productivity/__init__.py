"""Due-time helpers for spoken reminders."""

from __future__ import annotations

import re
from datetime import datetime, timedelta


_RELATIVE = re.compile(
    r"\s+(?:in\s+(?P<count>\d+)\s+(?P<unit>minutes?|hours?|days?)|"
    r"(?P<when>tomorrow|today|tonight))$",
    flags=re.IGNORECASE,
)
_AT_CLOCK = re.compile(
    r"\s+at\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)?$",
    flags=re.IGNORECASE,
)


def split_reminder(text: str, *, now: datetime | None = None) -> tuple[str, str | None]:
    """Return (content, due_at ISO or None) from a spoken reminder body."""
    current = now or datetime.now().astimezone()
    cleaned = text.strip().rstrip(".")
    clock = _AT_CLOCK.search(cleaned)
    relative = _RELATIVE.search(cleaned)
    due: datetime | None = None
    if clock:
        cleaned = cleaned[: clock.start()].strip()
        hour = int(clock.group("hour"))
        minute = int(clock.group("minute") or 0)
        ampm = (clock.group("ampm") or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        due = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due < current:
            due += timedelta(days=1)
    elif relative:
        cleaned = cleaned[: relative.start()].strip()
        when = (relative.group("when") or "").lower()
        if when == "tomorrow":
            due = (current + timedelta(days=1)).replace(
                hour=9, minute=0, second=0, microsecond=0
            )
        elif when in {"today", "tonight"}:
            due = current.replace(hour=21 if when == "tonight" else 18, minute=0, second=0, microsecond=0)
            if due < current:
                due = current + timedelta(minutes=30)
        else:
            count = int(relative.group("count") or 0)
            unit = (relative.group("unit") or "minutes").lower()
            if unit.startswith("day"):
                due = current + timedelta(days=count)
            elif unit.startswith("hour"):
                due = current + timedelta(hours=count)
            else:
                due = current + timedelta(minutes=count)
    due_iso = due.replace(microsecond=0).isoformat() if due is not None else None
    return cleaned, due_iso
