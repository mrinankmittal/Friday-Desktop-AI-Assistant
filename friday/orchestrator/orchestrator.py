from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import Any

from friday.orchestrator.intents import classify
from friday.orchestrator.legacy import EngineLegacyActions, LegacyActions
from friday.orchestrator.models import (
    HandleResult,
    Intent,
    IntentName,
    Task,
    TaskStatus,
    TaskStep,
)
from friday.tools.builtin import (
    APPS_OPEN,
    COMMS_WHATSAPP_CALL,
    COMMS_WHATSAPP_MESSAGE,
    CONTACTS_LOOKUP,
    LLM_CHAT,
    MEDIA_YOUTUBE_PLAY,
    SESSION_STOP,
    build_legacy_registry,
)
from friday.tools.browser_tools import (
    BROWSER_CLICK,
    BROWSER_DOWNLOAD,
    BROWSER_FILL,
    BROWSER_OPEN,
    BROWSER_READ,
    BROWSER_SEARCH,
    BROWSER_TABS,
)
from friday.tools.media_tools import MEDIA_CONTROL
from friday.tools.news_tools import NEWS_HEADLINES
from friday.tools.weather_tools import WEATHER_GET
from friday.tools.os_tools import (
    OS_AUTOMATE,
    OS_CLIPBOARD_GET,
    OS_CLIPBOARD_SET,
    OS_INFO,
    OS_NETWORK,
    OS_PROCESSES_LIST,
    OS_SCREENSHOT,
    OS_WINDOWS_FOCUS,
    OS_WINDOWS_LIST,
)
from friday.tools.vision_tools import VISION_DESCRIBE, VISION_OCR, VISION_VERIFY
from friday.tools.memory_tools import (
    MEMORY_FORGET,
    MEMORY_INGEST,
    MEMORY_LIST,
    MEMORY_REMEMBER,
    RAG_SEARCH,
)
from friday.tools.file_tools import (
    FILES_COPY,
    FILES_MKDIR,
    FILES_MOVE,
    FILES_READ,
    FILES_RUN,
    FILES_SEARCH,
    FILES_WRITE,
)
from friday.tools.code_tools import CODE_EXPLAIN, CODE_PATCH, CODE_READ, CODE_TEST
from friday.tools.productivity_tools import (
    NOTES_ADD,
    NOTES_LIST,
    REMINDERS_ADD,
    REMINDERS_LIST,
    TASKS_ADD,
    TASKS_DONE,
    TASKS_LIST,
)
from friday.tools.research_tools import RESEARCH_DOCS, RESEARCH_REPORT
from friday.tools.integration_tools import (
    DISCORD_SEND,
    EMAIL_LIST,
    EMAIL_SEND,
    INTEGRATIONS_CONNECT,
    INTEGRATIONS_DISCONNECT,
    INTEGRATIONS_STATUS,
    SLACK_SEND,
)
from friday.browser.types import BrowserDriver
from friday.integrations.address import (
    gmail_setup_reply,
    is_self_recipient,
    resolve_recipient,
    user_email,
)
from friday.integrations.contacts import resolve_contact_email
from friday.integrations.oauth import env_authorized_secrets
from friday.integrations.pending import (
    PendingSend,
    clear_pending,
    get_pending,
    set_pending,
)
from friday.integrations.settings import IntegrationSettings
from friday.integrations.store import IntegrationStore
from friday.memory import (
    CHAT_OFFLINE_HELP,
    format_grounded_prompt,
    get_memory_store,
    grounded_fallback_reply,
    is_chat_unavailable,
)
from friday.memory.store import MemoryStore
from friday.os_adapters.types import OsAdapter
from friday.providers.types import VisionProvider
from friday.security.settings import require_confirm_send, require_confirm_whatsapp
from friday.observability import emit
from friday.tools.registry import ToolRegistry
from friday.tools.types import ToolContext, ToolResult

logger = logging.getLogger("friday.orchestrator")

SpeakFn = Callable[[str], None]
ListenFn = Callable[[], str]

_SINGLE_STEP: dict[IntentName, tuple[str, str]] = {
    IntentName.YOUTUBE: ("system", MEDIA_YOUTUBE_PLAY),
    IntentName.OPEN: ("system", APPS_OPEN),
    IntentName.STOP: ("system", SESSION_STOP),
    IntentName.CHAT: ("conversation", LLM_CHAT),
    IntentName.WEATHER: ("system", WEATHER_GET),
    IntentName.NEWS: ("system", NEWS_HEADLINES),
}


_OS_TOOLS: dict[str, tuple[str, str]] = {
    "screenshot": ("system", OS_SCREENSHOT),
    "screenshot_show": ("system", OS_SCREENSHOT),
    "windows": ("system", OS_WINDOWS_LIST),
    "processes": ("system", OS_PROCESSES_LIST),
    "clipboard_get": ("system", OS_CLIPBOARD_GET),
    "clipboard_set": ("system", OS_CLIPBOARD_SET),
    "focus": ("system", OS_WINDOWS_FOCUS),
    "automate": ("system", OS_AUTOMATE),
    "info": ("system", OS_INFO),
    "network": ("system", OS_NETWORK),
}

_MEDIA_TOOLS: dict[str, tuple[str, str]] = {
    "play": ("system", MEDIA_CONTROL),
    "pause": ("system", MEDIA_CONTROL),
    "next": ("system", MEDIA_CONTROL),
    "previous": ("system", MEDIA_CONTROL),
    "stop": ("system", MEDIA_CONTROL),
}

_BROWSER_TOOLS: dict[str, tuple[str, str]] = {
    "search": ("browser", BROWSER_SEARCH),
    "open": ("browser", BROWSER_OPEN),
    "read": ("browser", BROWSER_READ),
    "click": ("browser", BROWSER_CLICK),
    "fill": ("browser", BROWSER_FILL),
    "download": ("browser", BROWSER_DOWNLOAD),
    "tabs": ("browser", BROWSER_TABS),
}

_VISION_TOOLS: dict[str, tuple[str, str]] = {
    "describe": ("vision", VISION_DESCRIBE),
    "ocr": ("vision", VISION_OCR),
    "verify": ("vision", VISION_VERIFY),
}

_MEMORY_TOOLS: dict[str, tuple[str, str]] = {
    "remember": ("memory", MEMORY_REMEMBER),
    "list": ("memory", MEMORY_LIST),
    "forget": ("memory", MEMORY_FORGET),
    "ingest": ("memory", MEMORY_INGEST),
    "search": ("memory", RAG_SEARCH),
}

_FILE_TOOLS: dict[str, tuple[str, str]] = {
    "search": ("file", FILES_SEARCH),
    "read": ("file", FILES_READ),
    "write": ("file", FILES_WRITE),
    "move": ("file", FILES_MOVE),
    "copy": ("file", FILES_COPY),
    "mkdir": ("file", FILES_MKDIR),
    "show_last": ("file", FILES_READ),
    "run": ("file", FILES_RUN),
}

_CODE_TOOLS: dict[str, tuple[str, str]] = {
    "read": ("coding", CODE_READ),
    "patch": ("coding", CODE_PATCH),
    "test": ("coding", CODE_TEST),
    "explain": ("coding", CODE_EXPLAIN),
}

_PRODUCTIVITY_TOOLS: dict[str, tuple[str, str]] = {
    "notes_add": ("productivity", NOTES_ADD),
    "notes_list": ("productivity", NOTES_LIST),
    "reminders_add": ("productivity", REMINDERS_ADD),
    "reminders_list": ("productivity", REMINDERS_LIST),
    "tasks_add": ("productivity", TASKS_ADD),
    "tasks_list": ("productivity", TASKS_LIST),
    "tasks_done": ("productivity", TASKS_DONE),
}

_RESEARCH_TOOLS: dict[str, tuple[str, str]] = {
    "report": ("research", RESEARCH_REPORT),
    "docs": ("research", RESEARCH_DOCS),
}

_INTEGRATION_TOOLS: dict[str, tuple[str, str]] = {
    "status": ("communication", INTEGRATIONS_STATUS),
    "connect": ("communication", INTEGRATIONS_CONNECT),
    "disconnect": ("communication", INTEGRATIONS_DISCONNECT),
    "email_send": ("communication", EMAIL_SEND),
    "email_list": ("communication", EMAIL_LIST),
    "slack_send": ("communication", SLACK_SEND),
    "discord_send": ("communication", DISCORD_SEND),
    "confirm_pending": ("communication", EMAIL_SEND),
    "cancel_pending": ("communication", INTEGRATIONS_STATUS),
}


def _plan(query: str, intent: Intent) -> Task:
    if intent.name is IntentName.WHATSAPP:
        action = str(intent.extra.get("action") or "message")
        send_tool = (
            COMMS_WHATSAPP_MESSAGE if action == "message" else COMMS_WHATSAPP_CALL
        )
        steps = [
            TaskStep(agent="communication", tool=CONTACTS_LOOKUP),
            TaskStep(agent="communication", tool=send_tool),
        ]
    elif intent.name is IntentName.OS:
        action = str(intent.extra.get("action") or "screenshot")
        agent, tool = _OS_TOOLS[action]
        steps = [TaskStep(agent=agent, tool=tool)]
    elif intent.name is IntentName.MEDIA:
        action = str(intent.extra.get("action") or "play")
        agent, tool = _MEDIA_TOOLS[action]
        steps = [TaskStep(agent=agent, tool=tool)]
    elif intent.name is IntentName.BROWSER:
        action = str(intent.extra.get("action") or "search")
        agent, tool = _BROWSER_TOOLS[action]
        steps = [TaskStep(agent=agent, tool=tool)]
    elif intent.name is IntentName.VISION:
        action = str(intent.extra.get("action") or "describe")
        agent, tool = _VISION_TOOLS[action]
        steps = [TaskStep(agent=agent, tool=tool)]
    elif intent.name is IntentName.MEMORY:
        action = str(intent.extra.get("action") or "list")
        agent, tool = _MEMORY_TOOLS[action]
        steps = [TaskStep(agent=agent, tool=tool)]
    elif intent.name is IntentName.FILE:
        action = str(intent.extra.get("action") or "search")
        agent, tool = _FILE_TOOLS[action]
        steps = [TaskStep(agent=agent, tool=tool)]
    elif intent.name is IntentName.CODE:
        action = str(intent.extra.get("action") or "read")
        agent, tool = _CODE_TOOLS[action]
        steps = [TaskStep(agent=agent, tool=tool)]
    elif intent.name is IntentName.PRODUCTIVITY:
        action = str(intent.extra.get("action") or "notes_list")
        agent, tool = _PRODUCTIVITY_TOOLS[action]
        steps = [TaskStep(agent=agent, tool=tool)]
    elif intent.name is IntentName.RESEARCH:
        action = str(intent.extra.get("action") or "report")
        agent, tool = _RESEARCH_TOOLS[action]
        steps = [TaskStep(agent=agent, tool=tool)]
    elif intent.name is IntentName.INTEGRATION:
        action = str(intent.extra.get("action") or "status")
        agent, tool = _INTEGRATION_TOOLS[action]
        steps = [TaskStep(agent=agent, tool=tool)]
    else:
        agent, tool = _SINGLE_STEP[intent.name]
        steps = [TaskStep(agent=agent, tool=tool)]

    return Task(request=query, intent=intent.name, steps=steps)


class Orchestrator:
    def __init__(
        self,
        registry: ToolRegistry | None = None,
        actions: LegacyActions | None = None,
        os_adapter: OsAdapter | None = None,
        browser: BrowserDriver | None = None,
        vision: VisionProvider | None = None,
        memory: MemoryStore | None = None,
        integration_transport: Any = None,
        open_browser: Any = None,
    ) -> None:
        self._memory = memory if memory is not None else get_memory_store()
        self._integrations = IntegrationStore(self._memory.db_path)
        self._remember_user_email()
        self._registry = registry or build_legacy_registry(
            actions or EngineLegacyActions(),
            os_adapter=os_adapter,
            browser=browser,
            vision=vision,
            memory=self._memory,
            integration_transport=integration_transport,
            open_browser=open_browser,
        )

    def handle(
        self,
        query: str,
        *,
        speak: SpeakFn,
        listen: ListenFn,
        confirm_listen: ListenFn | None = None,
        llm_classify: Callable[[str], Intent | None] | None = None,
    ) -> HandleResult:
        intent = classify(query, llm_classify=llm_classify)
        task = _plan(query, intent)
        task.status = TaskStatus.RUNNING
        context = ToolContext(task_id=task.task_id, speak=speak, listen=listen)
        tools = [step.tool for step in task.steps]
        started = time.perf_counter()
        self._emit(
            "task_start",
            task_id=task.task_id,
            intent=intent.name.value,
            tools=tools,
            request=str(query or "").strip(),
        )

        try:
            result = self._execute(
                intent,
                task=task,
                context=context,
                speak=speak,
                listen=listen,
                confirm_listen=confirm_listen or listen,
            )
        except Exception:
            task.status = TaskStatus.FAILED
            running = next(
                (step for step in task.steps if step.status is TaskStatus.RUNNING),
                task.steps[-1],
            )
            running.status = TaskStatus.FAILED
            running.observation = "exception"
            self._emit(
                "task_end",
                task_id=task.task_id,
                intent=intent.name.value,
                tools=tools,
                status=TaskStatus.FAILED.value,
                observation="exception",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            logger.exception("task_id=%s failed", task.task_id)
            raise

        result.task = task
        self._finalize_task(task, result)
        self._persist_task(task, result)
        self._emit(
            "task_end",
            task_id=task.task_id,
            intent=intent.name.value,
            tools=tools,
            status=task.status.value,
            observation=result.observation,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        self._announce_due_reminders(speak)
        return result

    def _emit(self, event: str, *, task_id: str, **fields: Any) -> None:
        try:
            emit(event, task_id=task_id, store=self._memory, **fields)
        except Exception:
            logger.exception("event emit failed")

    def _announce_due_reminders(self, speak: SpeakFn) -> None:
        if self._memory is None:
            return
        try:
            due = self._memory.due_reminders()
        except Exception:
            logger.exception("due reminder lookup failed")
            return
        for item in due:
            speak(f"Reminder: {item.content}.")
            try:
                self._memory.complete_reminder(item.id)
            except Exception:
                logger.exception("could not complete reminder %s", item.id)

    def _execute(
        self,
        intent: Intent,
        *,
        task: Task,
        context: ToolContext,
        speak: SpeakFn,
        listen: ListenFn,
        confirm_listen: ListenFn | None = None,
    ) -> HandleResult:
        if intent.name is IntentName.YOUTUBE:
            self._invoke_step(task, 0, {"query": intent.query}, context)
            return HandleResult()

        if intent.name is IntentName.OPEN:
            self._invoke_step(task, 0, {"query": intent.query}, context)
            return HandleResult()

        if intent.name is IntentName.STOP:
            self._invoke_step(task, 0, {}, context)
            speak("Stopping voice control")
            return HandleResult(continue_listening=False, observation="stopped")

        if intent.name is IntentName.CHAT:
            chat_query = intent.query
            hits = self._memory.search(intent.query) if self._memory else []
            if hits:
                chat_query = format_grounded_prompt(intent.query, hits)
            tool_result = self._invoke_step(
                task, 0, {"query": chat_query}, context
            )
            reply = str(tool_result.data.get("reply") or "")
            if is_chat_unavailable(reply):
                reply = (
                    grounded_fallback_reply(hits, intent.query)
                    if hits
                    else CHAT_OFFLINE_HELP
                )
            return HandleResult(assistant_reply=reply)

        if intent.name is IntentName.OS:
            return self._execute_os(intent, task=task, context=context)

        if intent.name is IntentName.MEDIA:
            return self._execute_media(intent, task=task, context=context)

        if intent.name is IntentName.WEATHER:
            return self._execute_weather(intent, task=task, context=context)

        if intent.name is IntentName.NEWS:
            return self._execute_news(intent, task=task, context=context)

        if intent.name is IntentName.BROWSER:
            return self._execute_browser(intent, task=task, context=context)

        if intent.name is IntentName.VISION:
            return self._execute_vision(intent, task=task, context=context)

        if intent.name is IntentName.MEMORY:
            return self._execute_memory(intent, task=task, context=context)

        if intent.name is IntentName.FILE:
            return self._execute_file(intent, task=task, context=context)

        if intent.name is IntentName.CODE:
            return self._execute_code(intent, task=task, context=context)

        if intent.name is IntentName.PRODUCTIVITY:
            return self._execute_productivity(intent, task=task, context=context)

        if intent.name is IntentName.RESEARCH:
            return self._execute_research(intent, task=task, context=context)

        if intent.name is IntentName.INTEGRATION:
            return self._execute_integration(
                intent,
                task=task,
                context=context,
                speak=speak,
                listen=listen,
                confirm_listen=confirm_listen or listen,
            )

        return self._execute_whatsapp(
            intent, task=task, context=context, speak=speak, listen=listen
        )

    def _execute_os(
        self,
        intent: Intent,
        *,
        task: Task,
        context: ToolContext,
    ) -> HandleResult:
        action = str(intent.extra.get("action") or "")
        if action == "clipboard_set":
            arguments = {"text": str(intent.extra.get("text") or "").strip()}
        elif action == "focus":
            arguments = {"title": str(intent.extra.get("title") or "").strip()}
        elif action == "screenshot_show":
            arguments = {"capture": False, "open": True}
        elif action == "screenshot":
            arguments = {"capture": True, "open": True}
        elif action == "automate":
            arguments = {"task": str(intent.extra.get("task") or "").strip()}
            text = str(intent.extra.get("text") or "")
            keys = str(intent.extra.get("keys") or "").strip()
            app = str(intent.extra.get("app") or "").strip()
            if text:
                arguments["text"] = text
            if keys:
                arguments["keys"] = keys
            if app:
                arguments["app"] = app
        else:
            arguments = {}
        tool_result = self._invoke_step(task, 0, arguments, context)
        reply = str(tool_result.data.get("reply") or "")
        return HandleResult(
            assistant_reply=reply,
            observation=tool_result.observation,
            status=TaskStatus.SUCCEEDED if tool_result.ok else TaskStatus.FAILED,
        )

    def _execute_media(
        self,
        intent: Intent,
        *,
        task: Task,
        context: ToolContext,
    ) -> HandleResult:
        action = str(intent.extra.get("action") or "play")
        tool_result = self._invoke_step(task, 0, {"action": action}, context)
        reply = str(tool_result.data.get("reply") or "")
        return HandleResult(
            assistant_reply=reply,
            observation=tool_result.observation,
            status=TaskStatus.SUCCEEDED if tool_result.ok else TaskStatus.FAILED,
        )

    def _execute_weather(
        self,
        intent: Intent,
        *,
        task: Task,
        context: ToolContext,
    ) -> HandleResult:
        arguments = {}
        place = str(intent.extra.get("place") or "").strip()
        if place:
            arguments["place"] = place
        tool_result = self._invoke_step(task, 0, arguments, context)
        reply = str(tool_result.data.get("reply") or "")
        return HandleResult(
            assistant_reply=reply,
            observation=tool_result.observation,
            status=TaskStatus.SUCCEEDED if tool_result.ok else TaskStatus.FAILED,
        )

    def _execute_news(
        self,
        intent: Intent,
        *,
        task: Task,
        context: ToolContext,
    ) -> HandleResult:
        arguments = {}
        topic = str(intent.extra.get("topic") or "").strip()
        query = str(intent.extra.get("query") or "").strip()
        if topic:
            arguments["topic"] = topic
        if query:
            arguments["query"] = query
        tool_result = self._invoke_step(task, 0, arguments, context)
        reply = str(tool_result.data.get("reply") or "")
        return HandleResult(
            assistant_reply=reply,
            observation=tool_result.observation,
            status=TaskStatus.SUCCEEDED if tool_result.ok else TaskStatus.FAILED,
        )

    def _execute_browser(
        self,
        intent: Intent,
        *,
        task: Task,
        context: ToolContext,
    ) -> HandleResult:
        action = str(intent.extra.get("action") or "search")
        if action == "open":
            arguments = {"url": str(intent.extra.get("url") or "").strip()}
        elif action == "read":
            url = str(intent.extra.get("url") or "").strip()
            arguments = {"url": url} if url else {}
        elif action == "click":
            arguments = {"target": str(intent.extra.get("target") or "").strip()}
        elif action == "fill":
            arguments = {
                "target": str(intent.extra.get("target") or "").strip(),
                "value": str(intent.extra.get("value") or ""),
            }
        elif action == "download":
            arguments = {"target": str(intent.extra.get("target") or "").strip()}
            folder = str(intent.extra.get("folder") or "").strip()
            if folder:
                arguments["folder"] = folder
        elif action == "tabs":
            url = str(intent.extra.get("url") or "").strip()
            arguments = {"url": url} if url else {}
        else:
            arguments = {
                "query": str(intent.extra.get("search_query") or intent.query).strip()
            }
        tool_result = self._invoke_step(task, 0, arguments, context)
        reply = str(tool_result.data.get("reply") or "")
        return HandleResult(
            assistant_reply=reply,
            observation=tool_result.observation,
            status=TaskStatus.SUCCEEDED if tool_result.ok else TaskStatus.FAILED,
        )

    def _execute_vision(
        self,
        intent: Intent,
        *,
        task: Task,
        context: ToolContext,
    ) -> HandleResult:
        action = str(intent.extra.get("action") or "describe")
        if action == "verify":
            arguments = {"needle": str(intent.extra.get("needle") or "").strip()}
        else:
            arguments = {}
        tool_result = self._invoke_step(task, 0, arguments, context)
        reply = str(tool_result.data.get("reply") or "")
        return HandleResult(
            assistant_reply=reply,
            observation=tool_result.observation,
            status=TaskStatus.SUCCEEDED if tool_result.ok else TaskStatus.FAILED,
        )

    def _execute_memory(
        self,
        intent: Intent,
        *,
        task: Task,
        context: ToolContext,
    ) -> HandleResult:
        action = str(intent.extra.get("action") or "list")
        if action == "remember":
            arguments = {"content": str(intent.extra.get("content") or "").strip()}
        elif action == "forget":
            arguments = {}
            if intent.extra.get("id") is not None:
                arguments["id"] = int(intent.extra["id"])
            text = str(intent.extra.get("text") or "").strip()
            if text:
                arguments["text"] = text
        elif action == "ingest":
            arguments = {"path": str(intent.extra.get("path") or "").strip()}
        elif action == "search":
            arguments = {
                "query": str(intent.extra.get("search_query") or intent.query).strip()
            }
        else:
            arguments = {}
        tool_result = self._invoke_step(task, 0, arguments, context)
        reply = str(tool_result.data.get("reply") or "")
        return HandleResult(
            assistant_reply=reply,
            observation=tool_result.observation,
            status=TaskStatus.SUCCEEDED if tool_result.ok else TaskStatus.FAILED,
        )

    def _ask_for_file_name(self, intent: Intent, context: ToolContext) -> tuple[str, str]:
        from friday.files.create import is_kind_label, plan_new_file

        if context.speak:
            context.speak("What should I call the file?")
        spoken = (context.listen() or "").strip() if context.listen else ""
        spoken = re.sub(
            r"^(?:please |call it |name it |named |called )",
            "",
            spoken,
            flags=re.IGNORECASE,
        ).strip()
        if not spoken or is_kind_label(spoken):
            if context.speak:
                context.speak(
                    "I need a real file name like hello or calculator, not just c plus plus."
                )
            return "", str(intent.extra.get("text") or "")
        path, text = plan_new_file(
            kind=str(intent.extra.get("kind") or ""),
            name=spoken,
            says=str(intent.extra.get("says") or ""),
        )
        if not path or is_kind_label(path.rsplit(".", 1)[0]):
            if context.speak:
                context.speak("I need a real file name like hello or calculator.")
            return "", str(intent.extra.get("text") or "")
        return path, text

    def _execute_file(
        self,
        intent: Intent,
        *,
        task: Task,
        context: ToolContext,
    ) -> HandleResult:
        action = str(intent.extra.get("action") or "search")
        if action == "read":
            arguments = {"path": str(intent.extra.get("path") or "").strip()}
        elif action == "show_last":
            arguments = {"open": True}
        elif action == "run":
            arguments = {}
            path = str(intent.extra.get("path") or "").strip()
            if path:
                arguments["path"] = path
        elif action == "write":
            path = str(intent.extra.get("path") or "").strip()
            text = str(intent.extra.get("text") or "")
            if not path:
                path, text = self._ask_for_file_name(intent, context)
                if not path:
                    task.steps[0].status = TaskStatus.CANCELLED
                    task.steps[0].observation = "cancelled"
                    return HandleResult(
                        assistant_reply=(
                            "I cancelled it. Say make a cpp file named NAME "
                            "when you have a name."
                        ),
                        observation="cancelled",
                        status=TaskStatus.CANCELLED,
                    )
            arguments = {
                "path": path,
                "text": text,
            }
            folder = str(intent.extra.get("folder") or "").strip()
            if folder:
                arguments["folder"] = folder
            if intent.extra.get("open"):
                arguments["open"] = True
        elif action == "move":
            arguments = {
                "source": str(intent.extra.get("source") or "").strip(),
                "destination": str(intent.extra.get("destination") or "").strip(),
            }
        elif action == "copy":
            arguments = {
                "source": str(intent.extra.get("source") or "").strip(),
                "destination": str(intent.extra.get("destination") or "").strip(),
            }
        elif action == "mkdir":
            arguments = {
                "path": str(intent.extra.get("path") or "").strip(),
            }
            folder = str(intent.extra.get("folder") or "").strip()
            if folder:
                arguments["folder"] = folder
        else:
            arguments = {}
            needle = str(intent.extra.get("needle") or "").strip()
            folder = str(intent.extra.get("folder") or "").strip()
            when = str(intent.extra.get("when") or "").strip()
            if needle:
                arguments["needle"] = needle
            if folder:
                arguments["folder"] = folder
            if when:
                arguments["when"] = when
        tool_result = self._invoke_step(task, 0, arguments, context)
        reply = str(tool_result.data.get("reply") or "")
        if action == "write" and tool_result.ok and intent.extra.get("run"):
            run_result = self._tools.invoke(
                FILES_RUN,
                {"path": str(tool_result.data.get("path") or "")},
                context,
            )
            run_reply = str(run_result.data.get("reply") or "")
            if run_reply:
                reply = f"{reply} {run_reply}".strip()
            if not run_result.ok:
                return HandleResult(
                    assistant_reply=reply,
                    observation=run_result.observation,
                    status=TaskStatus.FAILED,
                )
        return HandleResult(
            assistant_reply=reply,
            observation=tool_result.observation,
            status=TaskStatus.SUCCEEDED if tool_result.ok else TaskStatus.FAILED,
        )

    def _execute_code(
        self,
        intent: Intent,
        *,
        task: Task,
        context: ToolContext,
    ) -> HandleResult:
        action = str(intent.extra.get("action") or "read")
        if action == "patch":
            arguments = {
                "path": str(intent.extra.get("path") or "").strip(),
                "old": str(intent.extra.get("old") or ""),
                "new": str(intent.extra.get("new") or ""),
            }
        elif action == "test":
            arguments = {}
            target = str(intent.extra.get("target") or "").strip()
            if target:
                arguments["target"] = target
        elif action == "explain":
            arguments = {"path": str(intent.extra.get("path") or "").strip()}
            focus = str(intent.extra.get("focus") or "").strip()
            if focus:
                arguments["focus"] = focus
        else:
            arguments = {"path": str(intent.extra.get("path") or "").strip()}
        tool_result = self._invoke_step(task, 0, arguments, context)
        reply = str(tool_result.data.get("reply") or "")
        return HandleResult(
            assistant_reply=reply,
            observation=tool_result.observation,
            status=TaskStatus.SUCCEEDED if tool_result.ok else TaskStatus.FAILED,
        )

    def _execute_productivity(
        self,
        intent: Intent,
        *,
        task: Task,
        context: ToolContext,
    ) -> HandleResult:
        action = str(intent.extra.get("action") or "notes_list")
        if action in {"notes_add", "reminders_add", "tasks_add"}:
            arguments = {"content": str(intent.extra.get("content") or "").strip()}
        elif action == "tasks_done":
            arguments = {"needle": str(intent.extra.get("needle") or "").strip()}
        else:
            arguments = {}
        tool_result = self._invoke_step(task, 0, arguments, context)
        reply = str(tool_result.data.get("reply") or "")
        return HandleResult(
            assistant_reply=reply,
            observation=tool_result.observation,
            status=TaskStatus.SUCCEEDED if tool_result.ok else TaskStatus.FAILED,
        )

    def _execute_research(
        self,
        intent: Intent,
        *,
        task: Task,
        context: ToolContext,
    ) -> HandleResult:
        arguments = {
            "query": str(intent.extra.get("query") or intent.query).strip()
        }
        tool_result = self._invoke_step(task, 0, arguments, context)
        reply = str(tool_result.data.get("reply") or "")
        return HandleResult(
            assistant_reply=reply,
            observation=tool_result.observation,
            status=TaskStatus.SUCCEEDED if tool_result.ok else TaskStatus.FAILED,
        )

    def _execute_integration(
        self,
        intent: Intent,
        *,
        task: Task,
        context: ToolContext,
        speak: SpeakFn,
        listen: ListenFn,
        confirm_listen: ListenFn | None = None,
    ) -> HandleResult:
        del confirm_listen
        action = str(intent.extra.get("action") or "status")
        if action == "connect":
            arguments = {"provider": str(intent.extra.get("provider") or "").strip()}
        elif action == "disconnect":
            arguments = {"provider": str(intent.extra.get("provider") or "").strip()}
        elif action == "email_send":
            raw_to = str(intent.extra.get("to") or "").strip()
            to, failure = self._resolve_email_recipient(raw_to)
            if failure is not None:
                return HandleResult(assistant_reply=failure, status=TaskStatus.FAILED)
            body = str(intent.extra.get("body") or "").strip()
            subject = str(intent.extra.get("subject") or "").strip()
            if not body:
                speak("What should the email say?")
                body = listen().strip()
            if not body:
                return HandleResult(
                    assistant_reply="I couldn't hear the message, so I cancelled it.",
                    status=TaskStatus.CANCELLED,
                )
            if not self._ensure_gmail_connected():
                return HandleResult(
                    assistant_reply=gmail_setup_reply(),
                    status=TaskStatus.FAILED,
                )
            set_pending(
                PendingSend(kind="email", to=to, body=body, subject=subject),
                prompt=f"I'm about to email {to}: {body}. Say send it.",
            )
            return HandleResult(
                assistant_reply=f"I'm about to email {to}: {body}. Say send it.",
                observation="awaiting_confirm",
            )
        elif action == "slack_send":
            channel = str(intent.extra.get("channel") or "").strip()
            body = str(intent.extra.get("body") or "").strip()
            if not self._integrations.is_connected("slack"):
                return HandleResult(
                    assistant_reply="Slack is not connected. Say connect slack.",
                    status=TaskStatus.FAILED,
                )
            prompt = f"I'm about to send Slack to {channel}: {body}. Say send it."
            set_pending(
                PendingSend(kind="slack", channel=channel, body=body, to=channel),
                prompt=prompt,
            )
            return HandleResult(
                assistant_reply=prompt,
                observation="awaiting_confirm",
            )
        elif action == "discord_send":
            body = str(intent.extra.get("body") or "").strip()
            target = str(intent.extra.get("target") or "").strip()
            if not self._integrations.is_connected("discord"):
                return HandleResult(
                    assistant_reply="Discord is not connected. Say connect discord.",
                    status=TaskStatus.FAILED,
                )
            prompt = f"I'm about to post on Discord: {body}. Say send it."
            set_pending(
                PendingSend(kind="discord", body=body, target=target, to=target),
                prompt=prompt,
            )
            return HandleResult(
                assistant_reply=prompt,
                observation="awaiting_confirm",
            )
        elif action == "confirm_pending":
            pending = get_pending()
            if pending is None:
                return HandleResult(
                    assistant_reply="There's nothing waiting to send.",
                    status=TaskStatus.FAILED,
                )
            clear_pending()
            context.confirmed = True
            if pending.kind == "slack":
                task.steps[0].tool = SLACK_SEND
                arguments = {"channel": pending.channel, "body": pending.body}
            elif pending.kind == "discord":
                task.steps[0].tool = DISCORD_SEND
                arguments = {"body": pending.body}
                if pending.target:
                    arguments["target"] = pending.target
            elif pending.kind == "whatsapp":
                task.steps[0].tool = COMMS_WHATSAPP_MESSAGE
                arguments = {
                    "mobile_no": pending.mobile_no,
                    "name": pending.name,
                    "message": pending.body,
                }
                tool_result = self._invoke_step(task, 0, arguments, context)
                return HandleResult(
                    observation=tool_result.observation,
                    status=TaskStatus.SUCCEEDED if tool_result.ok else TaskStatus.FAILED,
                )
            elif pending.kind == "whatsapp_call":
                task.steps[0].tool = COMMS_WHATSAPP_CALL
                arguments = {
                    "mobile_no": pending.mobile_no,
                    "name": pending.name,
                    "mode": pending.mode or "voice",
                }
                tool_result = self._invoke_step(task, 0, arguments, context)
                return HandleResult(
                    observation=tool_result.observation,
                    status=TaskStatus.SUCCEEDED if tool_result.ok else TaskStatus.FAILED,
                )
            else:
                task.steps[0].tool = EMAIL_SEND
                arguments = {"to": pending.to, "body": pending.body}
                if pending.subject:
                    arguments["subject"] = pending.subject
        elif action == "cancel_pending":
            if get_pending() is None:
                return HandleResult(
                    assistant_reply="There's nothing waiting to send.",
                )
            clear_pending()
            task.steps[0].status = TaskStatus.CANCELLED
            return HandleResult(
                assistant_reply="Cancelled. I did not send it.",
                status=TaskStatus.CANCELLED,
            )
        else:
            arguments = {}
        tool_result = self._invoke_step(task, 0, arguments, context)
        reply = str(tool_result.data.get("reply") or "")
        return HandleResult(
            assistant_reply=reply,
            observation=tool_result.observation,
            status=TaskStatus.SUCCEEDED if tool_result.ok else TaskStatus.FAILED,
        )

    def _remember_user_email(self) -> None:
        email = user_email()
        if not email or self._memory is None:
            return
        existing = [
            item.content.lower()
            for item in self._memory.list_memories(limit=50)
        ]
        if any("my email is" in text and email.lower() in text for text in existing):
            return
        try:
            self._memory.remember(f"my email is {email}", kind="fact")
        except Exception:
            logger.exception("could not remember user email")

    def _resolve_email_recipient(self, raw_to: str) -> tuple[str, str | None]:
        """Turn a spoken recipient into an address.

        Returns ``(address, None)`` on success or ``("", message)`` with a
        spoken explanation when it cannot. Handles a dictated address, "me",
        and -- new -- a contact name looked up in the address book.
        """
        to = resolve_recipient(raw_to, default=user_email())
        if "@" in to:
            return to, None

        if is_self_recipient(raw_to) or not raw_to.strip():
            # "email me" with no address configured for the user.
            return "", gmail_setup_reply()

        contact = resolve_contact_email(raw_to, self._memory.db_path)
        if contact.has_email:
            return contact.email or "", None
        if contact.matched:
            return "", (
                f"I don't have an email address for {contact.name}. Add it to "
                "your contacts CSV and re-import, or say the full address like "
                "name at example dot com."
            )
        return "", "I need a full email address, like name at example dot com."

    def _ensure_gmail_connected(self) -> bool:
        if self._integrations.is_connected("gmail"):
            return True
        secrets = env_authorized_secrets("gmail", IntegrationSettings.from_env())
        if not secrets:
            return False
        self._integrations.save("gmail", secrets, label="env")
        return self._integrations.is_connected("gmail")

    def _execute_whatsapp(
        self,
        intent: Intent,
        *,
        task: Task,
        context: ToolContext,
        speak: SpeakFn,
        listen: ListenFn,
    ) -> HandleResult:
        lookup = self._invoke_step(task, 0, {"query": intent.query}, context)
        if not lookup.ok:
            return HandleResult(
                observation=lookup.observation,
                status=TaskStatus.FAILED,
            )

        action = str(intent.extra.get("action") or "message")
        mobile_no = str(lookup.data["mobile_no"])
        name = str(lookup.data["name"])
        inline_message = str(lookup.data.get("inline_message") or "").strip()

        if action == "message":
            if inline_message:
                message_text = inline_message
            else:
                speak("What message should I send?")
                message_text = listen().strip()
            if not message_text:
                speak("I couldn't hear the message, so I cancelled it.")
                task.steps[1].status = TaskStatus.CANCELLED
                task.steps[1].observation = "cancelled"
                return HandleResult(
                    observation="cancelled",
                    status=TaskStatus.CANCELLED,
                )
            if require_confirm_whatsapp():
                prompt = (
                    f"I'm about to WhatsApp {name}: {message_text}. Say send it."
                )
                set_pending(
                    PendingSend(
                        kind="whatsapp",
                        body=message_text,
                        mobile_no=mobile_no,
                        name=name,
                    ),
                    prompt=prompt,
                )
                return HandleResult(
                    assistant_reply=prompt,
                    observation="awaiting_confirm",
                )
            context.confirmed = True
            self._invoke_step(
                task,
                1,
                {"mobile_no": mobile_no, "name": name, "message": message_text},
                context,
            )
            return HandleResult()

        mode = "video" if action == "video" else "voice"
        if require_confirm_whatsapp():
            verb = "video-call" if mode == "video" else "call"
            prompt = f"I'm about to {verb} {name} on WhatsApp. Say send it."
            set_pending(
                PendingSend(
                    kind="whatsapp_call",
                    mobile_no=mobile_no,
                    name=name,
                    mode=mode,
                ),
                prompt=prompt,
            )
            return HandleResult(
                assistant_reply=prompt,
                observation="awaiting_confirm",
            )
        context.confirmed = True
        self._invoke_step(
            task,
            1,
            {"mobile_no": mobile_no, "name": name, "mode": mode},
            context,
        )
        return HandleResult()

    def _invoke_step(
        self,
        task: Task,
        index: int,
        arguments: dict,
        context: ToolContext,
    ) -> ToolResult:
        step = task.steps[index]
        step.status = TaskStatus.RUNNING
        result = self._registry.invoke(step.tool, arguments, context)
        step.input_hash = result.input_hash
        step.observation = result.observation
        step.status = TaskStatus.SUCCEEDED if result.ok else TaskStatus.FAILED
        return result

    @staticmethod
    def _finalize_task(task: Task, result: HandleResult) -> None:
        if result.status is not None:
            task.status = result.status
            return

        if any(step.status is TaskStatus.CANCELLED for step in task.steps):
            task.status = TaskStatus.CANCELLED
        elif any(step.status is TaskStatus.FAILED for step in task.steps):
            task.status = TaskStatus.FAILED
        else:
            task.status = TaskStatus.SUCCEEDED
            if result.observation is None:
                result.observation = "ok"

    def _persist_task(self, task: Task, result: HandleResult) -> None:
        if self._memory is None:
            return
        try:
            self._memory.record_task(
                task_id=task.task_id,
                request=task.request,
                intent=task.intent.value,
                status=task.status.value,
                observation=result.observation,
            )
            self._memory.record_turn("user", task.request)
            if result.assistant_reply:
                self._memory.record_turn("assistant", result.assistant_reply)
        except Exception:
            logger.exception("task_id=%s memory persist failed", task.task_id)


def handle_user_request(
    query: str,
    *,
    speak: SpeakFn,
    listen: ListenFn,
    actions: LegacyActions | None = None,
    registry: ToolRegistry | None = None,
    os_adapter: OsAdapter | None = None,
    browser: BrowserDriver | None = None,
    vision: VisionProvider | None = None,
    memory: MemoryStore | None = None,
    integration_transport: Any = None,
    open_browser: Any = None,
    confirm_listen: ListenFn | None = None,
) -> HandleResult:
    return Orchestrator(
        registry=registry,
        actions=actions,
        os_adapter=os_adapter,
        browser=browser,
        vision=vision,
        memory=memory,
        integration_transport=integration_transport,
        open_browser=open_browser,
    ).handle(
        query,
        speak=speak,
        listen=listen,
        confirm_listen=confirm_listen,
    )
