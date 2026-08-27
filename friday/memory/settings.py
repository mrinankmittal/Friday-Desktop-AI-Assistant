from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from friday.providers.types import project_root


def _split_paths(raw: str) -> tuple[Path, ...]:
    if not raw.strip():
        return ()
    return tuple(Path(part.strip()) for part in raw.split(os.pathsep) if part.strip())


def default_allow_paths() -> tuple[Path, ...]:
    home = Path.home()
    return (
        home / "Documents",
        home / "Desktop",
        home / "Downloads",
        home / "Pictures",
        home / "Friday",
        project_root(),
        home,
    )


@dataclass(frozen=True)
class MemorySettings:
    db_path: Path
    allow_paths: tuple[Path, ...]

    @classmethod
    def from_env(cls) -> MemorySettings:
        data_dir = os.environ.get("FRIDAY_DATA_DIR", "").strip()
        if data_dir:
            db_path = Path(data_dir) / "friday.db"
        else:
            db_path = project_root() / "friday.db"
        configured = _split_paths(os.environ.get("FRIDAY_ALLOW_PATHS", ""))
        allow = configured or default_allow_paths()
        return cls(db_path=db_path, allow_paths=allow)
