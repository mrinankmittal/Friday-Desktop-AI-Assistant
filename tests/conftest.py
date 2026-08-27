"""Shared pytest fixtures for the Friday 2.0 suite.

Every fixture here keeps a test off the real desktop: no browser launches, no
WhatsApp window, no microphone, no LLM call, and a throwaway SQLite file.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from friday.browser.fake import FakeBrowser
from friday.integrations.pending import clear_pending
from friday.language.bilingual import reset_user_language
from friday.memory.store import MemoryStore
from friday.observability import clear_events
from friday.orchestrator.orchestrator import handle_user_request
from friday.os_adapters.fake import FakeOsAdapter
from friday.providers.fake import FakeVision
from friday.tools.builtin import build_legacy_registry
from friday.tools.registry import InvokePolicy

CONFIRM_ENV = "FRIDAY_REQUIRE_CONFIRM_SEND"


class RecordingActions:
    """Stands in for ``engine.features`` and records what was asked of it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.contact: tuple = ("919999999999", "Papa")
        self.chat_reply = "chat reply"

    def play_youtube(self, query: str) -> None:
        self.calls.append(("play_youtube", (query,), {}))

    def open_app(self, query: str) -> None:
        self.calls.append(("open_app", (query,), {}))

    def find_contact(self, query: str) -> tuple:
        self.calls.append(("find_contact", (query,), {}))
        return self.contact

    def whatsapp(self, mobile_no, message, flag, name) -> bool:
        self.calls.append(
            (
                "whatsapp",
                (),
                {
                    "mobile_no": mobile_no,
                    "message": message,
                    "flag": flag,
                    "name": name,
                },
            )
        )
        return True

    def chatbot(self, query: str) -> str:
        self.calls.append(("chatbot", (query,), {}))
        return self.chat_reply

    def called(self, name: str) -> bool:
        return any(call[0] == name for call in self.calls)

    def last(self, name: str) -> tuple:
        return next(call for call in reversed(self.calls) if call[0] == name)


class Session:
    """One conversation. ``say`` is a full turn through the orchestrator."""

    def __init__(
        self,
        memory: MemoryStore,
        actions: RecordingActions,
        os_adapter: FakeOsAdapter,
        browser: FakeBrowser,
        vision: FakeVision,
    ) -> None:
        self.memory = memory
        self.actions = actions
        self.os_adapter = os_adapter
        self.browser = browser
        self.vision = vision
        self.spoken: list[str] = []
        self.heard: list[str] = []
        self.results: list[Any] = []

    def hears(self, *replies: str) -> None:
        """Queue what the microphone will return on the next nested listen."""
        self.heard.extend(replies)

    def _listen(self) -> str:
        return self.heard.pop(0) if self.heard else ""

    def say(self, query: str):
        result = handle_user_request(
            query,
            speak=self.spoken.append,
            listen=self._listen,
            actions=self.actions,
            os_adapter=self.os_adapter,
            browser=self.browser,
            vision=self.vision,
            memory=self.memory,
        )
        self.results.append(result)
        return result

    @property
    def task_ids(self) -> list[str]:
        return [result.task.task_id for result in self.results]


@pytest.fixture(autouse=True)
def isolate_process_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pending sends and the event buffer are module globals; reset both.

    WhatsApp confirm defaults off in the user's .env for speed; tests that
    exercise the confirm flow need it on unless they opt out explicitly.
    """
    monkeypatch.setenv("FRIDAY_WHATSAPP_CONFIRM", "true")
    clear_pending()
    clear_events()
    reset_user_language()
    yield
    clear_pending()
    clear_events()
    reset_user_language()


@pytest.fixture(autouse=True)
def confirm_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """Match the shipped default so a test never sends without asking."""
    monkeypatch.setenv(CONFIRM_ENV, "true")


@pytest.fixture
def confirm_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt a test out of the confirm gate to exercise the send path itself."""
    monkeypatch.setenv(CONFIRM_ENV, "false")


@pytest.fixture
def data_dir() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        yield Path(folder)


@pytest.fixture
def memory(data_dir: Path) -> MemoryStore:
    return MemoryStore(data_dir / "friday.db")


@pytest.fixture
def actions() -> RecordingActions:
    return RecordingActions()


@pytest.fixture
def os_adapter() -> FakeOsAdapter:
    return FakeOsAdapter()


@pytest.fixture
def registry(actions: RecordingActions, memory: MemoryStore, os_adapter: FakeOsAdapter):
    """Registry with the confirm gate on, which is the shipped default."""
    return build_legacy_registry(
        actions,
        policy=InvokePolicy(require_confirm_for_high_risk=True),
        os_adapter=os_adapter,
        browser=FakeBrowser(),
        vision=FakeVision(),
        memory=memory,
    )


@pytest.fixture
def open_registry(
    actions: RecordingActions, memory: MemoryStore, os_adapter: FakeOsAdapter
):
    """Registry with the confirm gate off, for asserting on the send itself."""
    return build_legacy_registry(
        actions,
        policy=InvokePolicy(require_confirm_for_high_risk=False),
        os_adapter=os_adapter,
        browser=FakeBrowser(),
        vision=FakeVision(),
        memory=memory,
    )


@pytest.fixture
def session(
    memory: MemoryStore, actions: RecordingActions, os_adapter: FakeOsAdapter
) -> Session:
    return Session(memory, actions, os_adapter, FakeBrowser(), FakeVision())
