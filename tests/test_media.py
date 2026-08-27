"""Media playback control: media keys, classifier steal-guards, open-then-play.

"Open spotify" launches the app but never presses play, so these commands send
the Windows media transport keys (which drive whatever owns the media session)
and, for "play music" specifically, launch Spotify first when nothing is running
yet so the play key has a session to resume.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from friday.os_adapters.fake import FakeOsAdapter
from friday.os_adapters.types import ProcessInfo
from friday.orchestrator.intents import classify, classify_media
from friday.orchestrator.models import IntentName
from friday.tools.builtin import build_legacy_registry
from friday.tools.media_tools import (
    MEDIA_CONTROL,
    is_spotify_running,
    register_media_tools,
    warmup_seconds,
)
from friday.tools.registry import ToolRegistry
from friday.tools.types import ToolContext
from friday.browser.fake import FakeBrowser
from friday.providers.fake import FakeVision
from tests.helpers import make_memory_store


class ClassifyMediaTests(unittest.TestCase):
    def _action(self, phrase: str) -> str | None:
        intent = classify_media(phrase)
        return None if intent is None else intent.extra.get("action")

    def test_play_phrases(self) -> None:
        for phrase in [
            "play music",
            "play the music",
            "play some music",
            "play my music",
            "play song",
            "play spotify",
            "resume",
            "resume music",
            "unpause",
            "start playing",
            "continue playing",
            "friday play music please",
        ]:
            with self.subTest(phrase=phrase):
                self.assertEqual(self._action(phrase), "play")

    def test_pause_phrases(self) -> None:
        for phrase in ["pause", "pause music", "pause the song", "pause spotify"]:
            with self.subTest(phrase=phrase):
                self.assertEqual(self._action(phrase), "pause")

    def test_next_phrases(self) -> None:
        for phrase in ["next", "next song", "next track", "skip", "skip this song", "play next"]:
            with self.subTest(phrase=phrase):
                self.assertEqual(self._action(phrase), "next")

    def test_previous_phrases(self) -> None:
        for phrase in ["previous", "previous song", "go back", "last song", "play previous"]:
            with self.subTest(phrase=phrase):
                self.assertEqual(self._action(phrase), "previous")

    def test_stop_phrases_need_a_media_object(self) -> None:
        for phrase in ["stop music", "stop the music", "stop playing", "stop the song", "stop spotify"]:
            with self.subTest(phrase=phrase):
                self.assertEqual(self._action(phrase), "stop")

    def test_the_whole_thing_routes_through_classify(self) -> None:
        self.assertEqual(classify("play music").name, IntentName.MEDIA)
        self.assertEqual(classify("next song").name, IntentName.MEDIA)
        self.assertEqual(classify("pause").name, IntentName.MEDIA)


class MediaStealGuardTests(unittest.TestCase):
    """The new commands must not capture anything they should not."""

    def test_bare_stop_still_stops_voice_control(self) -> None:
        self.assertIsNone(classify_media("stop"))
        self.assertNotEqual(classify("exit").name, IntentName.MEDIA)
        self.assertNotEqual(classify("stop listening").name, IntentName.MEDIA)

    def test_play_on_youtube_still_goes_to_youtube(self) -> None:
        self.assertIsNone(classify_media("play despacito on youtube"))
        self.assertEqual(classify("play despacito on youtube").name, IntentName.YOUTUBE)

    def test_a_specific_song_is_not_hijacked_as_resume(self) -> None:
        # We do not support named tracks, but "play <song>" must not silently
        # resume the wrong thing -- it should fall through, not become MEDIA.
        self.assertIsNone(classify_media("play bohemian rhapsody"))

    def test_open_spotify_is_still_an_open_command(self) -> None:
        self.assertEqual(classify("open spotify").name, IntentName.OPEN)

    def test_ordinary_chat_is_untouched(self) -> None:
        for phrase in ["what's the weather", "play with the dog", "i want to skip lunch"]:
            with self.subTest(phrase=phrase):
                self.assertIsNone(classify_media(phrase))


class WarmupTests(unittest.TestCase):
    def test_default_when_unset(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(warmup_seconds(), 3.5)

    def test_env_override(self) -> None:
        with patch.dict("os.environ", {"FRIDAY_SPOTIFY_WARMUP_SEC": "1.0"}):
            self.assertEqual(warmup_seconds(), 1.0)

    def test_garbage_env_falls_back(self) -> None:
        with patch.dict("os.environ", {"FRIDAY_SPOTIFY_WARMUP_SEC": "soon"}):
            self.assertEqual(warmup_seconds(), 3.5)


class MediaToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = FakeOsAdapter()
        self.slept: list[float] = []
        self.registry = ToolRegistry()
        register_media_tools(
            self.registry, self.adapter, sleeper=lambda s: self.slept.append(s)
        )
        self.context = ToolContext(task_id="media-test")

    def _run(self, action: str):
        return self.registry.invoke(MEDIA_CONTROL, {"action": action}, self.context)

    def test_pause_sends_the_toggle_key_only(self) -> None:
        result = self._run("pause")
        self.assertTrue(result.ok)
        self.assertIn(("media_control", "play_pause"), self.adapter.calls)
        self.assertNotIn(("list_processes",), self.adapter.calls)
        self.assertEqual(self.slept, [])

    def test_next_and_previous_and_stop_map_to_their_keys(self) -> None:
        for action, key in [("next", "next"), ("previous", "previous"), ("stop", "stop")]:
            with self.subTest(action=action):
                adapter = FakeOsAdapter()
                registry = ToolRegistry()
                register_media_tools(registry, adapter, sleeper=lambda s: None)
                registry.invoke(MEDIA_CONTROL, {"action": action}, self.context)
                self.assertIn(("media_control", key), adapter.calls)

    def test_play_when_spotify_running_just_presses_play(self) -> None:
        self.adapter.processes = [ProcessInfo(pid=1, name="Spotify.exe")]
        result = self._run("play")
        self.assertTrue(result.ok)
        self.assertNotIn(("open_path", "shell:AppsFolder\\x"), self.adapter.calls)
        opened = [c for c in self.adapter.calls if c[0] == "open_path"]
        self.assertEqual(opened, [])
        self.assertIn(("media_control", "play_pause"), self.adapter.calls)
        self.assertEqual(self.slept, [])

    def test_play_when_spotify_closed_opens_it_then_plays(self) -> None:
        self.adapter.processes = [ProcessInfo(pid=1, name="chrome.exe")]
        with patch(
            "friday.tools.media_tools.lookup_open_target",
            return_value=("path", "shell:AppsFolder\\Spotify"),
        ):
            result = self._run("play")
        self.assertTrue(result.ok)
        self.assertIn(("open_path", "shell:AppsFolder\\Spotify"), self.adapter.calls)
        # It must open first, wait, then press play -- in that order.
        open_index = self.adapter.calls.index(("open_path", "shell:AppsFolder\\Spotify"))
        play_index = self.adapter.calls.index(("media_control", "play_pause"))
        self.assertLess(open_index, play_index)
        self.assertEqual(self.slept, [warmup_seconds()])
        self.assertIn("Spotify", result.data["reply"])


class MediaRegisteredInRealRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder, memory, _root = make_memory_store()
        self.adapter = FakeOsAdapter()
        self.registry = build_legacy_registry(
            actions=_UnusedActions(),
            os_adapter=self.adapter,
            browser=FakeBrowser(),
            vision=FakeVision(),
            memory=memory,
        )

    def tearDown(self) -> None:
        self._folder.cleanup()

    def test_media_tool_is_registered(self) -> None:
        self.assertIn(MEDIA_CONTROL, self.registry.names())

    def test_is_spotify_running_reads_processes(self) -> None:
        self.adapter.processes = [ProcessInfo(pid=1, name="Spotify.exe")]
        self.assertTrue(is_spotify_running(self.adapter))
        self.adapter.processes = [ProcessInfo(pid=1, name="chrome.exe")]
        self.assertFalse(is_spotify_running(self.adapter))


class _UnusedActions:
    def play_youtube(self, query: str) -> None:
        return None

    def open_app(self, query: str) -> None:
        return None

    def find_contact(self, query: str) -> tuple:
        return (0, 0)

    def whatsapp(self, mobile_no, message, flag, name) -> bool:
        return False

    def chatbot(self, query: str) -> str:
        return ""


if __name__ == "__main__":
    unittest.main()
