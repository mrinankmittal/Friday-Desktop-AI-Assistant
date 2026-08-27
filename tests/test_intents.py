from __future__ import annotations

import unittest

from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName


class ClassifyRulesTests(unittest.TestCase):
    def test_youtube_requires_play_and_youtube(self) -> None:
        intent = classify("play lo-fi beats on youtube")
        self.assertEqual(intent.name, IntentName.YOUTUBE)

    def test_open_youtube_is_open_not_youtube(self) -> None:
        intent = classify("open youtube")
        self.assertEqual(intent.name, IntentName.OPEN)

    def test_whatsapp_message_phrases(self) -> None:
        for query in (
            "send message to kabir",
            "send a message to mummy",
            "whatsapp message papa",
            "message to kabir",
            "text to mummy hello",
            "send text to papa",
        ):
            intent = classify(query)
            self.assertEqual(intent.name, IntentName.WHATSAPP, query)
            self.assertEqual(intent.extra["action"], "message", query)

    def test_whatsapp_calls(self) -> None:
        for query in (
            "phone call papa",
            "phone call to papa",
            "voice call papa",
            "call papa",
            "call to mummy",
            "make a call to kabir",
            "whatsapp call kabir",
        ):
            intent = classify(query)
            self.assertEqual(intent.name, IntentName.WHATSAPP, query)
            self.assertEqual(intent.extra["action"], "call", query)

    def test_whatsapp_video_calls(self) -> None:
        for query in (
            "video call kabir",
            "video call to mummy",
            "make a video call to papa",
            "start a video call to kabir",
        ):
            intent = classify(query)
            self.assertEqual(intent.name, IntentName.WHATSAPP, query)
            self.assertEqual(intent.extra["action"], "video", query)

    def test_message_body_with_call_stays_a_message(self) -> None:
        intent = classify("send message to papa call me later")
        self.assertEqual(intent.name, IntentName.WHATSAPP)
        self.assertEqual(intent.extra["action"], "message")

    def test_open_is_substring(self) -> None:
        self.assertEqual(classify("open chrome").name, IntentName.OPEN)

    def test_open_is_command_shaped(self) -> None:
        self.assertEqual(classify("open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("please open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("i want to open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("opened chrome").name, IntentName.CHAT)
        self.assertEqual(classify("don't open chrome").name, IntentName.CHAT)
        self.assertEqual(classify("please don't open chrome").name, IntentName.CHAT)

    def test_os_laptop_commands(self) -> None:
        self.assertEqual(classify("take a screenshot").extra["action"], "screenshot")
        self.assertEqual(
            classify("show me the screenshot").extra["action"], "screenshot_show"
        )
        self.assertEqual(
            classify("take a screenshot and show me the screenshot").extra["action"],
            "screenshot",
        )
        self.assertEqual(classify("list windows").extra["action"], "windows")
        self.assertEqual(classify("list of windows").extra["action"], "windows")
        self.assertEqual(classify("show me the windows").extra["action"], "windows")
        self.assertEqual(
            classify("tell me regarding the list of windows").extra["action"],
            "windows",
        )
        self.assertEqual(classify("list processes").extra["action"], "processes")
        self.assertEqual(classify("list of processes").extra["action"], "processes")
        self.assertEqual(
            classify("now tell me regarding the list of processes").extra["action"],
            "processes",
        )
        self.assertEqual(classify("list the").name, IntentName.CHAT)
        self.assertEqual(classify("open the task").name, IntentName.OPEN)
        self.assertEqual(classify("open task manager").name, IntentName.OPEN)
        self.assertEqual(classify("read the clipboard").extra["action"], "clipboard_get")
        clip = classify("copy to clipboard hello friday")
        self.assertEqual(clip.extra["action"], "clipboard_set")
        self.assertEqual(clip.extra["text"], "hello friday")
        focus = classify("switch to chrome")
        self.assertEqual(focus.extra["action"], "focus")
        self.assertEqual(focus.extra["title"], "chrome")

    def test_open_is_not_stolen_by_os_intents(self) -> None:
        self.assertEqual(classify("open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("list my notes").name, IntentName.PRODUCTIVITY)
        self.assertEqual(classify("list files in downloads").name, IntentName.FILE)
        self.assertEqual(classify("search my documents for goa").name, IntentName.RESEARCH)
        self.assertEqual(classify("forget it").name, IntentName.CHAT)

    def test_questions_do_not_fire_tools(self) -> None:
        self.assertEqual(classify("tell me where is the screenshot").name, IntentName.CHAT)
        self.assertEqual(classify("show the location of screenshot").name, IntentName.CHAT)
        self.assertEqual(classify("what is a phone call").name, IntentName.CHAT)
        self.assertEqual(classify("screenshot").extra["action"], "screenshot")

    def test_stop_is_exact_phrase(self) -> None:
        for query in ("exit", "quit", "stop listening"):
            self.assertEqual(classify(query).name, IntentName.STOP, query)
        self.assertEqual(classify("please stop listening now").name, IntentName.CHAT)

    def test_unmatched_goes_to_chat(self) -> None:
        self.assertEqual(classify("what is the weather").name, IntentName.WEATHER)

    def test_web_search_phrases(self) -> None:
        for query, terms in (
            ("search the web for python", "python"),
            ("google python tutorials", "python tutorials"),
            ("google for weather in delhi", "weather in delhi"),
            ("can you google python", "python"),
            ("look up python on the web", "python"),
            ("look up python online", "python"),
            ("search python on the web", "python"),
            ("find weather on google", "weather"),
            ("web search python", "python"),
        ):
            intent = classify(query)
            self.assertEqual(intent.name, IntentName.BROWSER, query)
            self.assertEqual(intent.extra["action"], "search", query)
            self.assertEqual(intent.extra["search_query"], terms, query)

    def test_browser_open_and_read(self) -> None:
        opened = classify("go to python.org")
        self.assertEqual(opened.name, IntentName.BROWSER)
        self.assertEqual(opened.extra["action"], "open")
        self.assertEqual(opened.extra["url"], "https://python.org")

        visit = classify("visit https://example.com")
        self.assertEqual(visit.extra["action"], "open")
        self.assertEqual(visit.extra["url"], "https://example.com")

        bare = classify("https://example.com/docs")
        self.assertEqual(bare.extra["action"], "open")

        read = classify("read this page")
        self.assertEqual(read.name, IntentName.BROWSER)
        self.assertEqual(read.extra["action"], "read")
        self.assertEqual(classify("summarize this page").extra["action"], "read")
        self.assertEqual(classify("what's on this page").extra["action"], "read")

        site = classify("open python.org")
        self.assertEqual(site.name, IntentName.BROWSER)
        self.assertEqual(site.extra["action"], "open")
        self.assertEqual(site.extra["url"], "https://python.org")

    def test_browser_does_not_steal_existing_commands(self) -> None:
        self.assertEqual(classify("open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("open youtube").name, IntentName.OPEN)
        self.assertEqual(classify("play despacito on youtube").name, IntentName.YOUTUBE)
        self.assertEqual(classify("go to sleep").name, IntentName.CHAT)
        self.assertEqual(classify("what is python").name, IntentName.CHAT)
        self.assertEqual(classify("what is google").name, IntentName.CHAT)

    def test_vision_screen_commands(self) -> None:
        self.assertEqual(classify("what's on my screen").name, IntentName.VISION)
        self.assertEqual(classify("read the screen").extra["action"], "ocr")
        self.assertEqual(classify("is chrome on the screen").extra["needle"], "chrome")
        self.assertEqual(classify("screenshot").name, IntentName.OS)

    def test_llm_fallback_only_for_chat(self) -> None:
        def llm_classify(_query: str):
            return classify("open notepad")

        youtube = classify("play music on youtube", llm_classify=llm_classify)
        self.assertEqual(youtube.name, IntentName.YOUTUBE)

        rerouted = classify("remind me later", llm_classify=llm_classify)
        self.assertEqual(rerouted.name, IntentName.OPEN)


if __name__ == "__main__":
    unittest.main()
