from __future__ import annotations

from typing import Any, Protocol


class LegacyActions(Protocol):
    """I/O surface used by registered tools. Implemented by EngineLegacyActions."""

    def play_youtube(self, query: str) -> None: ...

    def open_app(self, query: str) -> bool | None: ...

    def find_contact(self, query: str) -> tuple[Any, Any]: ...

    def whatsapp(
        self,
        mobile_no: object,
        message: object,
        flag: str,
        name: object,
    ) -> bool: ...

    def chatbot(self, query: str) -> str: ...
