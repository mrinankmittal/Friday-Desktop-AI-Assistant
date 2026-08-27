from __future__ import annotations

import unittest

from friday.browser.fake import FakeBrowser
from friday.providers.fake import FakeVision
from friday.browser.format import format_read, format_search
from friday.browser.urls import looks_like_url, normalize_url, unwrap_redirect
from friday.orchestrator.models import IntentName
from friday.orchestrator.intents import classify
from friday.tools.browser_tools import BROWSER_OPEN, BROWSER_READ, BROWSER_SEARCH
from friday.tools.builtin import build_legacy_registry
from friday.tools.types import ToolContext
from tests.helpers import make_memory_store


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
        return "should not be called"


class UrlHelperTests(unittest.TestCase):
    def test_normalize_https_and_host(self) -> None:
        self.assertEqual(normalize_url("https://example.com"), "https://example.com")
        self.assertEqual(normalize_url("example.com"), "https://example.com")
        self.assertEqual(normalize_url("www.python.org/docs"), "https://www.python.org/docs")

    def test_rejects_unsafe_schemes(self) -> None:
        self.assertIsNone(normalize_url("javascript:alert(1)"))
        self.assertIsNone(normalize_url("file:///C:/Windows/notepad.exe"))
        self.assertIsNone(normalize_url("not a url"))
        self.assertFalse(looks_like_url("sleep"))
        self.assertTrue(looks_like_url("python.org"))

    def test_unwraps_search_redirects(self) -> None:
        ddg = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2F&rut=abc"
        self.assertEqual(unwrap_redirect(ddg), "https://www.python.org/")
        bing = (
            "https://www.bing.com/ck/a?!&&p=abc&u=a1aHR0cHM6Ly93d3cucHl0aG9uLm9yZy8&ntb=1"
        )
        self.assertEqual(unwrap_redirect(bing), "https://www.python.org/")


class BrowserToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.browser = FakeBrowser()
        self._memory_folder, memory, _root = make_memory_store()
        self.registry = build_legacy_registry(
            _UnusedActions(),
            browser=self.browser,
            vision=FakeVision(),
            memory=memory,
        )
        self.context = ToolContext(task_id="browser-test")

    def tearDown(self) -> None:
        self._memory_folder.cleanup()

    def test_search_returns_spoken_results(self) -> None:
        result = self.registry.invoke(
            BROWSER_SEARCH, {"query": "python"}, self.context
        )
        self.assertTrue(result.ok)
        self.assertEqual(self.browser.calls[0], ("search", "python"))
        self.assertIn("Python.org", result.data["reply"])
        self.assertEqual(result.data["count"], 2)

    def test_open_rejects_javascript(self) -> None:
        result = self.registry.invoke(
            BROWSER_OPEN, {"url": "javascript:alert(1)"}, self.context
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.observation, "invalid_url")
        self.assertEqual(self.browser.calls, [])

    def test_open_and_read(self) -> None:
        opened = self.registry.invoke(
            BROWSER_OPEN, {"url": "https://example.com"}, self.context
        )
        self.assertTrue(opened.ok)
        self.assertIn("Example Domain", opened.data["reply"])
        read = self.registry.invoke(BROWSER_READ, {}, self.context)
        self.assertTrue(read.ok)
        self.assertIn("illustrative examples", read.data["reply"])

    def test_search_logs_do_not_include_page_body(self) -> None:
        with self.assertLogs("friday.tools", level="INFO") as captured:
            self.registry.invoke(BROWSER_SEARCH, {"query": "python"}, self.context)
        combined = "\n".join(captured.output)
        self.assertIn("browser.search", combined)
        self.assertNotIn("The official home of the Python", combined)


class FormatTests(unittest.TestCase):
    def test_empty_search(self) -> None:
        from friday.browser.types import SearchResult

        spoken = format_search(SearchResult(query="xyz", page_url="", hits=[], extracted=True))
        self.assertIn("couldn't find", spoken)

    def test_read_without_page(self) -> None:
        from friday.browser.types import PageContent

        spoken = format_read(PageContent(url="", title="", text="", extracted=False))
        self.assertIn("no page to read", spoken)


class ClassifyBrowserTests(unittest.TestCase):
    def test_open_website_without_host_searches(self) -> None:
        intent = classify("open website python docs")
        self.assertEqual(intent.name, IntentName.BROWSER)
        self.assertEqual(intent.extra["action"], "search")
        self.assertEqual(intent.extra["search_query"], "python docs")


if __name__ == "__main__":
    unittest.main()
