from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import requests

from friday.providers.llm import (
    OLLAMA_KEEP_ALIVE,
    _spoken_text,
    ollama_reply,
    reset_chat_history,
    resolve_ollama_model,
    warmup_ollama,
)
from friday.providers.settings import LlmSettings


class OllamaReplyTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_chat_history()

    def test_returns_none_when_ollama_is_down(self) -> None:
        """Down means /api/chat is unreachable, not merely /api/tags."""
        with (
            patch("friday.providers.llm.requests.get", side_effect=ConnectionError("down")),
            patch("friday.providers.llm.requests.post", side_effect=ConnectionError("down")),
        ):
            self.assertIsNone(ollama_reply("hello"))

    def test_a_slow_model_listing_does_not_make_chat_offline(self) -> None:
        """The bug behind "General chat is offline" while Ollama was running.

        /api/tags had a 5s budget and blocks whenever Ollama is loading a model,
        so a busy-but-healthy server took the whole chat down with it.
        """
        chat = MagicMock()
        chat.status_code = 200
        chat.json.return_value = {"message": {"content": "I am fine."}}
        chat.raise_for_status.return_value = None

        with (
            patch(
                "friday.providers.llm.requests.get",
                side_effect=requests.exceptions.ReadTimeout("tags timed out"),
            ),
            patch("friday.providers.llm.requests.post", return_value=chat) as post,
        ):
            self.assertEqual(ollama_reply("how are you doing"), "I am fine.")

        # It must fall back to the configured model rather than an empty name.
        self.assertEqual(
            post.call_args.kwargs["json"]["model"], LlmSettings.from_env().model
        )

    def test_model_listing_happens_only_once(self) -> None:
        tags = MagicMock()
        tags.json.return_value = {"models": [{"name": "gemma3:4b"}]}
        tags.raise_for_status.return_value = None
        chat = MagicMock()
        chat.status_code = 200
        chat.json.return_value = {"message": {"content": "hello"}}
        chat.raise_for_status.return_value = None

        with (
            patch("friday.providers.llm.requests.get", return_value=tags) as get,
            patch("friday.providers.llm.requests.post", return_value=chat),
        ):
            ollama_reply("hello")
            ollama_reply("again")

        self.assertEqual(get.call_count, 1)

    def test_warmup_loads_the_model_before_the_first_command(self) -> None:
        tags = MagicMock()
        tags.json.return_value = {"models": [{"name": "gemma3:4b"}]}
        tags.raise_for_status.return_value = None
        chat = MagicMock()
        chat.status_code = 200
        chat.json.return_value = {"message": {"content": "hi"}}
        chat.raise_for_status.return_value = None

        with (
            patch("friday.providers.llm._ensure_ollama", return_value=True),
            patch("friday.providers.llm.requests.get", return_value=tags) as get,
            patch("friday.providers.llm.requests.post", return_value=chat) as post,
        ):
            self.assertTrue(warmup_ollama())
            get.reset_mock()
            ollama_reply("how are you")

        get.assert_not_called()
        self.assertEqual(post.call_args.kwargs["json"]["keep_alive"], OLLAMA_KEEP_ALIVE)
        self.assertEqual(post.call_args.kwargs["json"]["model"], "gemma3:4b")

    def test_the_model_is_kept_warm_between_turns(self) -> None:
        """Without keep_alive the model unloads after 5 minutes idle and the
        next question pays a ~16s cold load."""
        tags = MagicMock()
        tags.json.return_value = {"models": [{"name": "gemma3:4b"}]}
        tags.raise_for_status.return_value = None
        chat = MagicMock()
        chat.status_code = 200
        chat.json.return_value = {"message": {"content": "hello"}}
        chat.raise_for_status.return_value = None

        with (
            patch("friday.providers.llm.requests.get", return_value=tags),
            patch("friday.providers.llm.requests.post", return_value=chat) as post,
        ):
            ollama_reply("hello")

        self.assertEqual(post.call_args.kwargs["json"]["keep_alive"], OLLAMA_KEEP_ALIVE)

    def test_uses_chat_content(self) -> None:
        tags = MagicMock()
        tags.json.return_value = {"models": [{"name": "gemma3:4b"}]}
        tags.raise_for_status.return_value = None
        chat = MagicMock()
        chat.json.return_value = {"message": {"content": "hi from local"}}
        chat.raise_for_status.return_value = None
        with (
            patch("friday.providers.llm.requests.get", return_value=tags),
            patch("friday.providers.llm.requests.post", return_value=chat),
        ):
            self.assertEqual(ollama_reply("hello"), "hi from local")

    def test_prefers_gemma_over_llava(self) -> None:
        installed = ["llava:latest", "qwen3:14b", "gemma3:4b"]
        self.assertEqual(resolve_ollama_model(installed), "gemma3:4b")
        self.assertEqual(resolve_ollama_model(installed, "qwen3:14b"), "qwen3:14b")

    def test_strips_think_tags(self) -> None:
        self.assertEqual(_spoken_text("<think>secret</think>\nHello there."), "Hello there.")

    def test_system_prompt_does_not_claim_sends(self) -> None:
        from friday.providers.llm import _SYSTEM

        self.assertIn("connect gmail", _SYSTEM.lower())
        self.assertIn("cannot send", _SYSTEM.lower())
        self.assertIn("never claim you already sent", _SYSTEM.lower())
        self.assertIn("someone else", _SYSTEM.lower())

    def test_llm_defaults_to_ollama(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            settings = LlmSettings.from_env()
        self.assertEqual(settings.provider, "ollama")
        self.assertEqual(settings.model, "gemma3:4b")


if __name__ == "__main__":
    unittest.main()
