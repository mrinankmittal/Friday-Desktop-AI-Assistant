from __future__ import annotations

from friday.os_adapters.fake import FakeOsAdapter
from friday.os_adapters.types import OsAdapter, ProcessInfo, WindowInfo
from friday.os_adapters.windows import WindowsAdapter

_adapter: OsAdapter | None = None


def get_os_adapter() -> OsAdapter:
    global _adapter
    if _adapter is None:
        _adapter = WindowsAdapter()
    return _adapter


def set_os_adapter(adapter: OsAdapter | None) -> None:
    """Tests inject a fake adapter. Pass ``None`` to restore the default."""
    global _adapter
    _adapter = adapter
