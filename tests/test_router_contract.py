"""Router contract: a spoken phrase must keep reaching the same tool.

Friday 1.0's keyword router is still the fast path. These tables are the
regression net for it: if a new feature widens a pattern and swallows a phrase
that used to belong to another intent, one of these rows fails.
"""

from __future__ import annotations

import pytest

from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName
from friday.tools.builtin import (
    APPS_OPEN,
    LLM_CHAT,
    MEDIA_YOUTUBE_PLAY,
    REGISTERED_TOOL_NAMES,
    SESSION_STOP,
)
from friday.tools.browser_tools import BROWSER_OPEN, BROWSER_SEARCH
from friday.tools.memory_tools import MEMORY_REMEMBER, RAG_SEARCH
from friday.tools.os_tools import (
    OS_CLIPBOARD_GET,
    OS_PROCESSES_LIST,
    OS_SCREENSHOT,
    OS_WINDOWS_LIST,
)
from friday.tools.productivity_tools import NOTES_ADD, NOTES_LIST
from friday.tools.vision_tools import VISION_DESCRIBE

pytestmark = pytest.mark.router


INTENT_TABLE = [
    ("open chrome", IntentName.OPEN),
    ("open the task", IntentName.OPEN),
    ("play despacito on youtube", IntentName.YOUTUBE),
    ("exit", IntentName.STOP),
    ("stop listening", IntentName.STOP),
    ("list windows", IntentName.OS),
    ("list of windows", IntentName.OS),
    ("show me the windows", IntentName.OS),
    ("now tell me regarding the list of processes", IntentName.OS),
    ("take a screenshot", IntentName.OS),
    ("read the clipboard", IntentName.OS),
    ("search the web for python", IntentName.BROWSER),
    ("go to python.org", IntentName.BROWSER),
    ("describe the screen", IntentName.VISION),
    ("what's on my screen", IntentName.VISION),
    ("remember that I prefer tea", IntentName.MEMORY),
    ("search my documents for goa", IntentName.RESEARCH),
    ("find a file downloaded yesterday", IntentName.FILE),
    ("run the tests", IntentName.CODE),
    ("remind me to call papa tomorrow", IntentName.PRODUCTIVITY),
    ("list my notes", IntentName.PRODUCTIVITY),
    ("send me an email saying hello", IntentName.INTEGRATION),
    ("send message to papa", IntentName.WHATSAPP),
    ("call papa", IntentName.WHATSAPP),
    ("what is python", IntentName.CHAT),
    ("what is the weather", IntentName.WEATHER),
    ("weather in mumbai", IntentName.WEATHER),
    ("what is the news", IntentName.NEWS),
    ("sports news", IntentName.NEWS),
    ("copy that", IntentName.OS),
    ("paste", IntentName.OS),
    ("play despacito on spotify", IntentName.OS),
    ("search mummy on whatsapp", IntentName.OS),
]

# Phrases that a later phase must not quietly take over. Each one previously
# belonged to a different feature, or is deliberately too vague to act on.
STEAL_GUARD_TABLE = [
    ("don't open chrome", IntentName.CHAT),
    ("list the", IntentName.CHAT),
    ("forget it", IntentName.CHAT),
    ("I don't remember", IntentName.CHAT),
    ("remind me later", IntentName.CHAT),
    ("yes", IntentName.CHAT),
    ("send", IntentName.CHAT),
    ("note that I prefer tea", IntentName.MEMORY),
    ("list files in downloads", IntentName.FILE),
    ("list my notes", IntentName.PRODUCTIVITY),
    ("send message to papa", IntentName.WHATSAPP),
    ("google for weather in delhi", IntentName.BROWSER),
    ("find weather on google", IntentName.BROWSER),
    ("google for cricket news", IntentName.BROWSER),
    ("search the web for headlines", IntentName.BROWSER),
    ("open chrome", IntentName.OPEN),
    ("play despacito on youtube", IntentName.YOUTUBE),
    ("open spotify", IntentName.OPEN),
    ("send message to papa", IntentName.WHATSAPP),
]

# Phrase in, tool out, through the real orchestrator with fake side effects.
TOOL_ROUTING_TABLE = [
    ("open chrome", APPS_OPEN),
    ("play despacito on youtube", MEDIA_YOUTUBE_PLAY),
    ("take a screenshot", OS_SCREENSHOT),
    ("list of windows", OS_WINDOWS_LIST),
    ("now tell me regarding the list of processes", OS_PROCESSES_LIST),
    ("read the clipboard", OS_CLIPBOARD_GET),
    ("search the web for python", BROWSER_SEARCH),
    ("go to example.com", BROWSER_OPEN),
    ("what's on my screen", VISION_DESCRIBE),
    ("remember that my name is kabir", MEMORY_REMEMBER),
    ("do you know my name", RAG_SEARCH),
    ("add a note pack charger", NOTES_ADD),
    ("list my notes", NOTES_LIST),
    ("stop listening", SESSION_STOP),
    ("what is python", LLM_CHAT),
]


@pytest.mark.parametrize(("phrase", "expected"), INTENT_TABLE)
def test_phrase_classifies_to_intent(phrase: str, expected: IntentName) -> None:
    assert classify(phrase).name is expected


@pytest.mark.parametrize(("phrase", "expected"), STEAL_GUARD_TABLE)
def test_existing_commands_are_not_stolen(phrase: str, expected: IntentName) -> None:
    assert classify(phrase).name is expected


@pytest.mark.parametrize(("phrase", "tool"), TOOL_ROUTING_TABLE)
def test_phrase_reaches_tool(session, phrase: str, tool: str) -> None:
    result = session.say(phrase)
    assert result.task.steps, f"{phrase!r} planned no step"
    assert result.task.steps[0].tool == tool


@pytest.mark.parametrize(
    ("phrase", "tool"), [row for row in TOOL_ROUTING_TABLE if row[1] != LLM_CHAT]
)
def test_command_phrases_never_fall_through_to_chat(
    session, phrase: str, tool: str
) -> None:
    session.say(phrase)
    assert not session.actions.called("chatbot"), f"{phrase!r} fell through to chat"


def test_every_routed_tool_is_registered() -> None:
    for _phrase, tool in TOOL_ROUTING_TABLE:
        assert tool in REGISTERED_TOOL_NAMES


def test_negated_open_stays_conversation(session) -> None:
    result = session.say("don't open chrome")
    assert result.task.intent is IntentName.CHAT
    assert not session.actions.called("open_app")


def test_vague_list_does_not_launch_an_os_tool(session) -> None:
    result = session.say("list the")
    assert result.task.intent is IntentName.CHAT
    assert not any(call[0] == "list_windows" for call in session.os_adapter.calls)


def test_classify_is_case_and_padding_insensitive() -> None:
    assert classify("  OPEN CHROME  ").name is IntentName.OPEN
    assert classify("Take A Screenshot").name is IntentName.OS


def test_empty_utterance_does_not_raise() -> None:
    assert classify("").name is IntentName.CHAT
    assert classify("   ").name is IntentName.CHAT
