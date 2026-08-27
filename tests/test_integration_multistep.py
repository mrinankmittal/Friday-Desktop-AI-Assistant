"""Multi-step integration: one session, many turns, real orchestrator.

Every other test in the suite pins a single layer. This one drives a whole
conversation the way a person would, so it catches the failures that only show
up when turns depend on each other: a screenshot taken in one turn and opened
in the next, a send that is cancelled and then retried, a name remembered
early and recalled at the end.

Only the edges are faked (desktop, browser, screen, phone, LLM). The router,
planner, tool registry, confirm gate, SQLite store, and task traces are real.
"""

from __future__ import annotations

import json

import pytest

from friday.integrations.pending import get_pending
from friday.orchestrator.models import IntentName, TaskStatus
from friday.tools.memory_tools import MEMORY_REMEMBER
from friday.tools.os_tools import OS_SCREENSHOT
from friday.tools.productivity_tools import NOTES_ADD

pytestmark = pytest.mark.integration

SECRET_BODY = "hello from friday"
CONTACT_NUMBER = "919999999999"


def test_full_session_walks_every_layer(session) -> None:
    # 1. Teach it something. This has to survive until the last turn.
    remembered = session.say("remember that my name is Kabir")
    assert remembered.task.intent is IntentName.MEMORY
    assert remembered.task.steps[0].tool == MEMORY_REMEMBER
    assert remembered.task.status is TaskStatus.SUCCEEDED

    # 2. Take a screenshot, then 3. open the file the previous turn produced.
    shot = session.say("take a screenshot")
    assert shot.task.steps[0].tool == OS_SCREENSHOT
    saved = session.os_adapter.last_saved
    assert saved is not None

    shown = session.say("show me the screenshot")
    assert "Opening the screenshot" in shown.assistant_reply
    assert ("open_path", str(saved)) in session.os_adapter.calls

    # 4. Write a note, 5. read it back on the next turn.
    note = session.say("add a note pack charger")
    assert note.task.steps[0].tool == NOTES_ADD
    listed = session.say("list my notes")
    assert "pack charger" in listed.assistant_reply.lower()

    # 6. A send is staged, never delivered, until the user says so.
    staged = session.say(f"send message to papa {SECRET_BODY}")
    assert staged.task.intent is IntentName.WHATSAPP
    assert "say send it" in staged.assistant_reply.lower()
    assert get_pending() is not None
    assert not session.actions.called("whatsapp")

    # 7. Saying no really cancels it. Nothing has left the machine yet.
    cancelled = session.say("no")
    assert cancelled.task.status is TaskStatus.CANCELLED
    assert get_pending() is None
    assert not session.actions.called("whatsapp")

    # 8. Ask again, 9. confirm, and only now does it send.
    session.say(f"send message to papa {SECRET_BODY}")
    sent = session.say("yes")
    assert sent.task.status is TaskStatus.SUCCEEDED
    assert get_pending() is None
    whatsapp = session.actions.last("whatsapp")
    assert whatsapp[2]["message"] == SECRET_BODY
    assert whatsapp[2]["flag"] == "message"
    assert whatsapp[2]["name"] == "Papa"

    # 10. The name from turn 1 is still there, without asking the LLM.
    recalled = session.say("do you know my name")
    assert "kabir" in recalled.assistant_reply.lower()

    # 11. Stop ends the listening loop.
    stopped = session.say("stop listening")
    assert stopped.continue_listening is False

    # Exactly one WhatsApp send across eleven turns, despite two attempts.
    assert len([c for c in session.actions.calls if c[0] == "whatsapp"]) == 1
    # No command turn quietly fell through to the chatbot.
    assert not session.actions.called("chatbot")


def test_session_traces_are_complete_and_clean(session) -> None:
    session.say("remember that my name is Kabir")
    session.say("take a screenshot")
    session.say(f"send message to papa {SECRET_BODY}")
    session.say("yes")

    task_ids = session.task_ids
    assert all(task_ids), "every turn needs a task_id"
    assert len(set(task_ids)) == len(task_ids), "task_ids must not repeat"

    events = session.memory.list_events(limit=80)
    assert events

    # Each turn opened and closed a task under its own id.
    for task_id in task_ids:
        names = {event.event for event in events if event.task_id == task_id}
        assert "task_start" in names
        assert "task_end" in names

    # Tool calls are attributed to the task that made them.
    tool_events = [event for event in events if event.event == "tool_call"]
    assert tool_events
    assert all(event.task_id in set(task_ids) for event in tool_events)

    # Neither the trace nor the audit trail may carry the body or the number.
    dumped = json.dumps(
        [event.to_dict() for event in events]
        + [row.to_dict() for row in session.memory.list_audit(limit=50)]
    )
    assert SECRET_BODY not in dumped
    assert CONTACT_NUMBER not in dumped


def test_file_written_in_one_turn_is_found_and_read_in_the_next(session) -> None:
    path = session.memory.db_path.parent / "phase13-invoice.txt"
    path.write_text("paid in full", encoding="utf-8")

    found = session.say("find file phase13-invoice.txt")
    assert found.task.intent is IntentName.FILE
    assert "phase13-invoice" in found.assistant_reply.lower()

    read = session.say("read file phase13-invoice.txt")
    assert "paid" in read.assistant_reply.lower()
    assert not session.actions.called("chatbot")


def test_a_failed_step_stops_the_plan_instead_of_sending(session) -> None:
    session.actions.contact = (0, 0)
    result = session.say("send message to nobody")

    assert result.task.status is TaskStatus.FAILED
    assert result.task.steps[0].tool == "contacts.lookup"
    assert result.task.steps[1].status is TaskStatus.PLANNED
    assert not session.actions.called("whatsapp")
    assert result.continue_listening is True
