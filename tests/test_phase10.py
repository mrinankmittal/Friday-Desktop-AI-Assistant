from __future__ import annotations

import json
import os
import sqlite3
import unittest
from unittest.mock import patch

from friday.browser.fake import FakeBrowser
from friday.integrations.address import resolve_recipient
from friday.integrations.confirm import (
    is_confirm_no,
    is_confirm_yes,
    is_short_voice_reply,
)
from friday.integrations.oauth import (
    authorize_url,
    exchange_code,
    secrets_from_token_response,
)
from friday.integrations.pending import clear_pending, get_pending, set_pending, PendingSend
from friday.integrations.settings import is_gmail_app_password
from friday.integrations.store import IntegrationStore
from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName, TaskStatus
from friday.orchestrator.orchestrator import handle_user_request
from friday.os_adapters.fake import FakeOsAdapter
from friday.providers.fake import FakeVision
from friday.tools.builtin import REGISTERED_TOOL_NAMES, build_legacy_registry
from friday.tools.registry import InvokePolicy
from friday.tools.types import ToolContext
from tests.helpers import make_memory_store


class FakeResponse:
    def __init__(self, payload=None, status: int = 200) -> None:
        self.status_code = status
        self._payload = payload if payload is not None else {"ok": True, "id": "1"}

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeTransport:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[tuple[str, dict]] = []

    def post(self, url: str, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse({"ok": True, "id": "msg1"})

    def get(self, url: str, **kwargs):
        self.gets.append((url, kwargs))
        if url.rstrip("/").endswith("/messages"):
            return FakeResponse({"messages": [{"id": "abc12345"}]})
        return FakeResponse(
            {"payload": {"headers": [{"name": "Subject", "value": "Hello from tests"}]}}
        )


class FakeSession:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.posts: list[tuple[str, dict]] = []

    def post(self, url: str, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse(self.payload)


class FakeActions:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.contact = ("919999999999", "Papa")
        self.chat_reply = "should not be called"

    def play_youtube(self, query: str) -> None:
        self.calls.append(("play_youtube", query))

    def open_app(self, query: str) -> None:
        self.calls.append(("open_app", query))

    def find_contact(self, query: str) -> tuple:
        self.calls.append(("find_contact", query))
        return self.contact

    def whatsapp(self, mobile_no, message, flag, name) -> bool:
        self.calls.append(("whatsapp", mobile_no, message, flag, name))
        return True

    def chatbot(self, query: str) -> str:
        self.calls.append(("chatbot", query))
        return self.chat_reply


class ConfirmTests(unittest.TestCase):
    def test_yes_and_no(self) -> None:
        self.assertTrue(is_confirm_yes("sure"))
        self.assertTrue(is_confirm_yes("yes"))
        self.assertTrue(is_short_voice_reply("yes"))
        self.assertTrue(is_short_voice_reply("Yes."))
        self.assertTrue(is_short_voice_reply("Sure"))
        self.assertTrue(is_short_voice_reply("friday yes"))
        self.assertTrue(is_short_voice_reply("yes send it"))
        self.assertTrue(is_short_voice_reply("send"))
        self.assertFalse(is_short_voice_reply("send an email to myself"))
        self.assertTrue(is_confirm_yes("send it"))
        self.assertTrue(is_confirm_yes("send"))
        self.assertTrue(is_confirm_yes("ok sure"))
        self.assertTrue(is_confirm_yes("yes please"))
        self.assertTrue(is_confirm_yes("haan"))
        self.assertFalse(is_confirm_yes(""))
        self.assertFalse(is_confirm_yes("no"))
        self.assertFalse(is_confirm_yes("say yes or no"))
        self.assertFalse(is_confirm_no(""))
        self.assertTrue(is_confirm_no("cancel"))
        self.assertFalse(is_confirm_no("yes"))


class GmailAppPasswordTests(unittest.TestCase):
    def test_accepts_sixteen_letter_codes(self) -> None:
        self.assertTrue(is_gmail_app_password("abcdefghijklmnop"))
        self.assertTrue(is_gmail_app_password("abcd efgh ijkl mnop"))
        self.assertFalse(is_gmail_app_password(""))
        self.assertFalse(is_gmail_app_password("short"))
        self.assertFalse(is_gmail_app_password("Mri@notanapppwd"))


class AddressTests(unittest.TestCase):
    def test_resolves_me(self) -> None:
        self.assertEqual(resolve_recipient("me", default="a@b.com"), "a@b.com")
        self.assertEqual(resolve_recipient("myself", default="a@b.com"), "a@b.com")
        self.assertEqual(
            resolve_recipient("someone@gmail.com", default="a@b.com"),
            "someone@gmail.com",
        )


class ClassifyPhase10Tests(unittest.TestCase):
    def setUp(self) -> None:
        clear_pending()

    def tearDown(self) -> None:
        clear_pending()

    def test_integration_phrases(self) -> None:
        connected = classify("connect gmail")
        self.assertEqual(connected.name, IntentName.INTEGRATION)
        self.assertEqual(connected.extra["action"], "connect")
        self.assertEqual(connected.extra["provider"], "gmail")
        for query in (
            "connect my email",
            "connect my gmail",
            "connect to my email",
            "please connect my email",
            "can you connect my gmail",
            "connect my email account",
        ):
            spoken = classify(query)
            self.assertEqual(spoken.name, IntentName.INTEGRATION, query)
            self.assertEqual(spoken.extra["action"], "connect", query)
        self.assertEqual(classify("connect slack").extra["provider"], "slack")
        self.assertEqual(classify("connect my slack").extra["provider"], "slack")
        self.assertEqual(classify("disconnect discord").extra["action"], "disconnect")
        self.assertEqual(classify("disconnect my email").extra["action"], "disconnect")
        self.assertEqual(classify("now connect again").extra["action"], "connect")
        self.assertEqual(classify("now connect again").extra["provider"], "gmail")

        status = classify("what integrations do I have")
        self.assertEqual(status.extra["action"], "status")

        inbox = classify("check my email")
        self.assertEqual(inbox.extra["action"], "email_list")
        self.assertEqual(classify("check my gmail").extra["action"], "email_list")
        self.assertEqual(classify("read my emails").extra["action"], "email_list")
        self.assertEqual(classify("is my gmail connected").extra["action"], "status")
        self.assertEqual(classify("is it connected").extra["action"], "status")

        self_send = classify("send me an email")
        self.assertEqual(self_send.extra["action"], "email_send")
        self.assertEqual(self_send.extra["to"], "me")
        self.assertEqual(classify("send me a email").extra["to"], "me")
        self.assertEqual(classify("email myself").extra["to"], "me")
        self.assertEqual(
            classify("i would like to send email to myself").extra["to"], "me"
        )
        self.assertEqual(
            classify("send me an email saying hello from friday").extra["body"],
            "hello from friday",
        )
        by_saying = classify("email to myself by saying how are you")
        self.assertEqual(by_saying.extra["action"], "email_send")
        self.assertEqual(by_saying.extra["to"], "me")
        self.assertEqual(by_saying.extra["body"], "how are you")
        self.assertEqual(
            classify("send email to myself saying hi").extra["body"], "hi"
        )
        self.assertEqual(
            classify("myself by saying hello there").extra["to"], "me"
        )
        self.assertEqual(
            classify("myself by saying hello there").extra["body"], "hello there"
        )
        for spoken_self in (
            "send a email to my",
            "send a email to me",
            "send an email to myself",
            "i want you to send a email to myself",
            "i want to send a email to myself",
            "send it to me",
            "no send it to me",
            "draught email",
            "draft an email",
        ):
            intent = classify(spoken_self)
            self.assertEqual(intent.name, IntentName.INTEGRATION, spoken_self)
            self.assertEqual(intent.extra["action"], "email_send", spoken_self)
            self.assertEqual(intent.extra["to"], "me", spoken_self)

        emailed = classify("send an email to papa@example.com saying running late")
        self.assertEqual(emailed.extra["action"], "email_send")
        self.assertEqual(emailed.extra["to"], "papa@example.com")
        self.assertEqual(emailed.extra["body"], "running late")

        about = classify("email papa@example.com about dinner")
        self.assertEqual(about.extra["action"], "email_send")
        self.assertEqual(about.extra["subject"], "dinner")

        slack = classify("send a slack message to general saying standup is now")
        self.assertEqual(slack.extra["action"], "slack_send")
        self.assertEqual(slack.extra["channel"], "general")
        self.assertEqual(slack.extra["body"], "standup is now")

        discord = classify("send a discord message to mods saying server is up")
        self.assertEqual(discord.extra["action"], "discord_send")
        self.assertEqual(discord.extra["target"], "mods")
        posted = classify("post to discord saying hello friday")
        self.assertEqual(posted.extra["action"], "discord_send")
        self.assertEqual(posted.extra["body"], "hello friday")

    def test_does_not_steal_existing_commands(self) -> None:
        self.assertEqual(classify("send message to papa").name, IntentName.WHATSAPP)
        self.assertEqual(classify("call papa").name, IntentName.WHATSAPP)
        self.assertEqual(classify("what is my email").name, IntentName.MEMORY)
        self.assertEqual(classify("remind me to email papa").name, IntentName.PRODUCTIVITY)
        self.assertEqual(classify("open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("search my documents for goa").name, IntentName.RESEARCH)
        self.assertEqual(classify("note that I prefer tea").name, IntentName.MEMORY)
        self.assertEqual(classify("forget it").name, IntentName.CHAT)
        self.assertEqual(classify("remind me later").name, IntentName.CHAT)
        self.assertEqual(classify("yes").name, IntentName.CHAT)
        self.assertEqual(classify("sure").name, IntentName.CHAT)
        self.assertEqual(classify("yes send it").name, IntentName.CHAT)

    def test_pending_confirm_is_a_follow_up_command(self) -> None:
        set_pending(PendingSend(kind="email", to="a@b.com", body="hello"))
        self.assertEqual(classify("yes send it").extra["action"], "confirm_pending")
        self.assertEqual(classify("yes").extra["action"], "confirm_pending")
        self.assertEqual(classify("sure").extra["action"], "confirm_pending")
        self.assertEqual(classify("friday yes").extra["action"], "confirm_pending")
        self.assertEqual(classify("friday sure").extra["action"], "confirm_pending")
        self.assertEqual(classify("send it").extra["action"], "confirm_pending")
        self.assertEqual(classify("send").extra["action"], "confirm_pending")
        self.assertEqual(classify("send the email now").extra["action"], "confirm_pending")
        self.assertEqual(classify("no").extra["action"], "cancel_pending")
        self.assertEqual(classify("send message to papa").name, IntentName.WHATSAPP)


class OAuthHelperTests(unittest.TestCase):
    def test_authorize_url_and_token_secrets(self) -> None:
        url = authorize_url(
            "gmail",
            client_id="client",
            redirect_uri="http://127.0.0.1:8765/oauth/callback",
            state="abc",
        )
        self.assertIn("accounts.google.com", url)
        self.assertIn("client_id=client", url)
        self.assertNotIn("client_secret", url)

        gmail = secrets_from_token_response(
            "gmail",
            {"access_token": "tok", "refresh_token": "ref"},
        )
        self.assertEqual(gmail["access_token"], "tok")
        discord = secrets_from_token_response(
            "discord",
            {"webhook": {"url": "https://discord.com/api/webhooks/x", "channel": "general"}},
        )
        self.assertEqual(discord["webhook_url"], "https://discord.com/api/webhooks/x")

    def test_exchange_code_uses_injected_session(self) -> None:
        session = FakeSession({"access_token": "tok", "refresh_token": "ref"})
        payload = exchange_code(
            "gmail",
            code="auth-code",
            redirect_uri="http://127.0.0.1:8765/oauth/callback",
            client_id="id",
            client_secret="secret",
            session=session,
        )
        self.assertEqual(payload["access_token"], "tok")
        self.assertTrue(session.posts)
        self.assertIn("oauth2.googleapis.com/token", session.posts[0][0])


class IntegrationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder, self.memory, self.root = make_memory_store()
        self.store = IntegrationStore(self.memory.db_path)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_secrets_stay_out_of_sqlite(self) -> None:
        self.store.save("gmail", {"access_token": "super-secret-token"})
        self.assertEqual(
            self.store.secrets_for("gmail")["access_token"], "super-secret-token"
        )
        on_disk = self.store.secrets_path.read_text(encoding="utf-8")
        self.assertNotIn("super-secret-token", on_disk)
        self.assertIn("_friday_protected", on_disk)
        with sqlite3.connect(self.memory.db_path) as connection:
            dumped = " ".join(
                str(row) for row in connection.execute("SELECT * FROM integrations")
            )
        self.assertNotIn("super-secret-token", dumped)
        self.assertTrue(self.store.is_connected("gmail"))
        self.store.delete("gmail")
        self.assertFalse(self.store.is_connected("gmail"))


class Phase10ToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder, self.memory, self.root = make_memory_store()
        self.transport = FakeTransport()
        self.opened: list[str] = []
        self.env = patch.dict(
            os.environ,
            {
                "FRIDAY_USER_EMAIL": "",
                "FRIDAY_GMAIL_APP_PASSWORD": "",
            },
            clear=False,
        )
        self.env.start()
        self.registry = build_legacy_registry(
            FakeActions(),
            policy=InvokePolicy(),
            memory=self.memory,
            integration_transport=self.transport,
            open_browser=self.opened.append,
        )
        self.store = IntegrationStore(self.memory.db_path)
        self.context = ToolContext(task_id="phase10")

    def tearDown(self) -> None:
        self.env.stop()
        self.folder.cleanup()

    def test_send_requires_confirm(self) -> None:
        self.store.save("gmail", {"access_token": "tok"})
        blocked = self.registry.invoke(
            "email.send",
            {"to": "a@b.com", "body": "hello"},
            self.context,
        )
        self.assertFalse(blocked.ok)
        self.assertEqual(blocked.observation, "confirm_required")
        self.assertEqual(self.transport.posts, [])

        self.context.confirmed = True
        sent = self.registry.invoke(
            "email.send",
            {"to": "a@b.com", "body": "hello"},
            self.context,
        )
        self.assertTrue(sent.ok)
        self.assertTrue(self.transport.posts)
        self.assertIn("gmail.googleapis.com", self.transport.posts[0][0])

    def test_email_without_at_fails(self) -> None:
        self.store.save("gmail", {"access_token": "tok"})
        self.context.confirmed = True
        result = self.registry.invoke(
            "email.send",
            {"to": "papa", "body": "hello"},
            self.context,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.observation, "invalid_to")
        self.assertEqual(self.transport.posts, [])

    def test_logs_do_not_include_email_body(self) -> None:
        self.store.save("gmail", {"access_token": "tok"})
        self.context.confirmed = True
        with self.assertLogs("friday.tools", level="INFO") as captured:
            self.registry.invoke(
                "email.send",
                {"to": "a@b.com", "body": "secret-body"},
                self.context,
            )
        combined = "\n".join(captured.output)
        self.assertNotIn("secret-body", combined)
        self.assertNotIn("a@b.com", combined)
        self.assertNotIn("tok", combined)


class Phase10OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actions = FakeActions()
        self.spoken: list[str] = []
        self.listen_replies: list[str] = []
        self.opened: list[str] = []
        self.transport = FakeTransport()
        self._memory_folder, self.memory, _root = make_memory_store()
        self.store = IntegrationStore(self.memory.db_path)
        self.oauth_patcher = patch(
            "friday.tools.integration_tools.begin_oauth",
            return_value="https://example.test/oauth",
        )
        self.mock_oauth = self.oauth_patcher.start()
        self.env = patch.dict(
            os.environ,
            {
                "FRIDAY_GOOGLE_CLIENT_ID": "",
                "FRIDAY_GOOGLE_CLIENT_SECRET": "",
                "FRIDAY_USER_EMAIL": "",
                "FRIDAY_GMAIL_APP_PASSWORD": "",
                "FRIDAY_SLACK_CLIENT_ID": "",
                "FRIDAY_SLACK_CLIENT_SECRET": "",
                "FRIDAY_SLACK_BOT_TOKEN": "",
                "FRIDAY_DISCORD_CLIENT_ID": "",
                "FRIDAY_DISCORD_CLIENT_SECRET": "",
                "FRIDAY_DISCORD_WEBHOOK_URL": "",
                "FRIDAY_REQUIRE_CONFIRM_SEND": "true",
                "FRIDAY_WHATSAPP_CONFIRM": "true",
            },
            clear=False,
        )
        self.env.start()
        clear_pending()

    def tearDown(self) -> None:
        clear_pending()
        self.env.stop()
        self.oauth_patcher.stop()
        self._memory_folder.cleanup()

    def _handle(self, query: str):
        return handle_user_request(
            query,
            speak=self.spoken.append,
            listen=lambda: self.listen_replies.pop(0) if self.listen_replies else "",
            actions=self.actions,
            os_adapter=FakeOsAdapter(),
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=self.memory,
            integration_transport=self.transport,
            open_browser=self.opened.append,
        )

    def test_registers_integration_tools(self) -> None:
        self.assertEqual(len(REGISTERED_TOOL_NAMES), 61)
        self.assertIn("email.send", REGISTERED_TOOL_NAMES)

    def test_gmail_missing_oauth_skips_browser(self) -> None:
        result = self._handle("connect gmail")
        self.assertEqual(result.task.intent, IntentName.INTEGRATION)
        self.assertIn("FRIDAY_GMAIL_APP_PASSWORD", result.assistant_reply)
        self.mock_oauth.assert_not_called()
        self.assertEqual(self.opened, [])
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))

    def test_connect_my_email_is_not_chat(self) -> None:
        result = self._handle("connect my email")
        self.assertEqual(result.task.intent, IntentName.INTEGRATION)
        self.assertEqual(result.task.steps[0].tool, "integrations.connect")
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))

    def test_gmail_connects_with_app_password(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FRIDAY_USER_EMAIL": "a@b.com",
                "FRIDAY_GMAIL_APP_PASSWORD": "abcdefghijklmnop",
            },
            clear=False,
        ):
            result = self._handle("connect gmail")
        self.assertIn("connected", result.assistant_reply.lower())
        self.assertIn("a@b.com", result.assistant_reply)
        self.assertTrue(self.store.is_connected("gmail"))
        self.mock_oauth.assert_not_called()

    def test_gmail_rejects_normal_password(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FRIDAY_USER_EMAIL": "a@b.com",
                "FRIDAY_GMAIL_APP_PASSWORD": "Not@Your#Normal1",
            },
            clear=False,
        ):
            result = self._handle("connect gmail")
        self.assertIn("16 letters", result.assistant_reply.lower())
        self.assertFalse(self.store.is_connected("gmail"))
        self.mock_oauth.assert_not_called()
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))

    @patch("friday.integrations.send._smtp_send")
    def test_send_me_an_email_uses_smtp(self, smtp) -> None:
        with patch.dict(
            os.environ,
            {
                "FRIDAY_USER_EMAIL": "a@b.com",
                "FRIDAY_GMAIL_APP_PASSWORD": "abcdefghijklmnop",
            },
            clear=False,
        ):
            self.listen_replies = ["hello from friday"]
            staged = self._handle("send me an email")
            self.assertIn("say send it", staged.assistant_reply.lower())
            smtp.assert_not_called()
            sent = self._handle("yes send it")
        self.assertEqual(sent.task.status, TaskStatus.SUCCEEDED)
        self.assertIn("Email sent", sent.assistant_reply)
        smtp.assert_called_once()
        self.assertEqual(smtp.call_args.kwargs["to"], "a@b.com")
        self.assertEqual(smtp.call_args.kwargs["body"], "hello from friday")
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))

    def test_slack_and_discord_connect_from_env(self) -> None:
        with patch.dict(os.environ, {"FRIDAY_SLACK_BOT_TOKEN": "xoxb-test"}, clear=False):
            slack = self._handle("connect slack")
        self.assertIn("connected", slack.assistant_reply.lower())
        self.assertTrue(self.store.is_connected("slack"))
        self.mock_oauth.assert_not_called()

        with patch.dict(
            os.environ,
            {"FRIDAY_DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/abc"},
            clear=False,
        ):
            discord = self._handle("connect discord")
        self.assertIn("connected", discord.assistant_reply.lower())
        self.assertTrue(self.store.is_connected("discord"))
        self.assertEqual(
            self.store.secrets_for("discord")["webhook_url"],
            "https://discord.com/api/webhooks/1/abc",
        )
        self.mock_oauth.assert_not_called()

    def test_gmail_connect_uses_oauth_helper_when_configured(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FRIDAY_GOOGLE_CLIENT_ID": "id",
                "FRIDAY_GOOGLE_CLIENT_SECRET": "secret",
            },
            clear=False,
        ):
            result = self._handle("connect gmail")
        self.mock_oauth.assert_called_once()
        self.assertIn("Sign in", result.assistant_reply)

    def test_email_not_connected_skips_confirm_and_chatbot(self) -> None:
        result = self._handle("send an email to a@b.com saying hello")
        self.assertEqual(result.task.status, TaskStatus.FAILED)
        self.assertIn("FRIDAY_GMAIL_APP_PASSWORD", result.assistant_reply)
        self.assertEqual(self.spoken, [])
        self.assertEqual(self.transport.posts, [])
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))

    def test_email_without_at_fails_before_send(self) -> None:
        self.store.save("gmail", {"access_token": "tok"})
        result = self._handle("send an email to papa saying hello")
        self.assertEqual(result.task.status, TaskStatus.FAILED)
        self.assertIn("email address", result.assistant_reply.lower())
        self.assertEqual(self.transport.posts, [])
        self.assertEqual(self.spoken, [])

    def test_email_stages_confirm_without_sending(self) -> None:
        self.store.save("gmail", {"access_token": "tok"})
        result = self._handle("send an email to a@b.com saying hello")
        self.assertEqual(result.observation, "awaiting_confirm")
        self.assertIn("say send it", result.assistant_reply.lower())
        self.assertEqual(self.transport.posts, [])
        self.assertEqual(self.spoken, [])
        self.assertIsNotNone(get_pending())

    def test_email_yes_send_it_sends_on_next_command(self) -> None:
        self.store.save("gmail", {"access_token": "tok"})
        staged = self._handle("send an email to a@b.com saying hello friday")
        self.assertEqual(self.transport.posts, [])
        self.assertIn("say send it", staged.assistant_reply.lower())
        sent = self._handle("yes send it")
        self.assertEqual(sent.task.status, TaskStatus.SUCCEEDED)
        self.assertIn("Email sent", sent.assistant_reply)
        self.assertTrue(self.transport.posts)

    def test_email_no_cancels_on_next_command(self) -> None:
        self.store.save("gmail", {"access_token": "tok"})
        self._handle("send an email to a@b.com saying hello")
        cancelled = self._handle("no")
        self.assertEqual(cancelled.task.status, TaskStatus.CANCELLED)
        self.assertEqual(self.transport.posts, [])
        self.assertIsNone(get_pending())

    def test_email_yes_sends_over_mock_transport(self) -> None:
        self.store.save("gmail", {"access_token": "tok"})
        self._handle("send an email to a@b.com saying hello friday")
        result = self._handle("yes")
        self.assertEqual(result.task.status, TaskStatus.SUCCEEDED)
        self.assertIn("Email sent", result.assistant_reply)
        self.assertTrue(self.transport.posts)
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))

    def test_email_sure_sends_over_mock_transport(self) -> None:
        self.store.save("gmail", {"access_token": "tok"})
        self._handle("send an email to a@b.com saying hello friday")
        result = self._handle("sure")
        self.assertEqual(result.task.status, TaskStatus.SUCCEEDED)
        self.assertIn("Email sent", result.assistant_reply)
        self.assertTrue(self.transport.posts)

    def test_slack_and_discord_confirm(self) -> None:
        self.store.save("slack", {"access_token": "xoxb-test"})
        slack_staged = self._handle("send a slack message to general saying hello")
        self.assertIn("say send it", slack_staged.assistant_reply.lower())
        slack = self._handle("send it")
        self.assertIn("Slack message sent", slack.assistant_reply)
        self.assertTrue(any("slack.com" in url for url, _ in self.transport.posts))

        self.store.save(
            "discord",
            {"webhook_url": "https://discord.com/api/webhooks/1/abc"},
        )
        discord_staged = self._handle("post to discord saying hello")
        self.assertIn("say send it", discord_staged.assistant_reply.lower())
        discord = self._handle("yes send it")
        self.assertIn("Discord message sent", discord.assistant_reply)

    def test_whatsapp_confirms_and_does_not_steal_email(self) -> None:
        result = self._handle("send message to papa hello from friday")
        self.assertEqual(result.task.intent, IntentName.WHATSAPP)
        self.assertIn("say send it", (result.assistant_reply or "").lower())
        self.assertFalse(any(call[0] == "whatsapp" for call in self.actions.calls))
        self.assertEqual(self.transport.posts, [])
        sent = self._handle("yes")
        whatsapp = next(call for call in self.actions.calls if call[0] == "whatsapp")
        self.assertEqual(whatsapp[3], "message")
        self.assertEqual(sent.task.status, TaskStatus.SUCCEEDED)
        self.assertEqual(self.transport.posts, [])

    def test_status_skips_chatbot(self) -> None:
        result = self._handle("what integrations do I have")
        self.assertEqual(result.task.steps[0].tool, "integrations.status")
        self.assertIn("gmail", result.assistant_reply.lower())
        self.assertFalse(any(name == "chatbot" for name, *_ in self.actions.calls))


if __name__ == "__main__":
    unittest.main()
