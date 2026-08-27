"""Adapters that call Friday 1.0 ``engine.features`` functions.

Imports are lazy so this module can load without pulling Eel, HuggingChat,
or the ``command`` ↔ ``features`` cycle at import time.
"""

from __future__ import annotations

from typing import Any

from friday.tools.actions import LegacyActions

__all__ = ["EngineLegacyActions", "LegacyActions"]


class EngineLegacyActions:
    def play_youtube(self, query: str) -> None:
        from engine.features import PlayYoutube

        PlayYoutube(query)

    def open_app(self, query: str) -> bool:
        from engine.features import openCommand

        return bool(openCommand(query))

    def find_contact(self, query: str) -> tuple[Any, Any]:
        from engine.features import findContact

        return findContact(query)

    def whatsapp(
        self,
        mobile_no: object,
        message: object,
        flag: str,
        name: object,
    ) -> bool:
        from engine.features import whatsapp

        return bool(whatsapp(mobile_no=mobile_no, message=message, flag=flag, name=name))

    def chatbot(self, query: str) -> str:
        from engine.features import chatbot

        return chatbot(query)
