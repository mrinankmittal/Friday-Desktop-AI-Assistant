from __future__ import annotations

import tempfile
from pathlib import Path

from friday.memory.store import MemoryStore


def make_memory_store() -> tuple[tempfile.TemporaryDirectory, MemoryStore, Path]:
    folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    root = Path(folder.name)
    store = MemoryStore(root / "friday.db")
    return folder, store, root
