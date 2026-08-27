"""Live news: classify topics, speak headlines, do not steal Google searches."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from friday.news.headlines import fetch_headlines, normalize_topic, speak_headlines
from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName
from friday.tools.news_tools import NEWS_HEADLINES


class ClassifyNewsTests(unittest.TestCase):
    def test_bare_headlines(self) -> None:
        intent = classify("what is the news")
        self.assertEqual(intent.name, IntentName.NEWS)
        self.assertEqual(intent.extra["action"], "headlines")
        self.assertNotIn("query", intent.extra)

    def test_topic_and_search(self) -> None:
        sports = classify("sports news")
        self.assertEqual(sports.name, IntentName.NEWS)
        self.assertEqual(sports.extra["topic"], "sports")
        cricket = classify("news about cricket")
        self.assertEqual(cricket.extra["query"], "cricket")
        tech = classify("latest technology headlines")
        self.assertEqual(tech.extra["topic"], "technology")

    def test_does_not_steal_other_commands(self) -> None:
        self.assertEqual(classify("google for cricket news").name, IntentName.BROWSER)
        self.assertEqual(classify("search the web for headlines").name, IntentName.BROWSER)
        self.assertEqual(classify("open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("play music").name, IntentName.MEDIA)
        self.assertEqual(classify("make a note buy milk").name, IntentName.PRODUCTIVITY)


class SpeakHeadlinesTests(unittest.TestCase):
    def test_numbers_the_titles(self) -> None:
        reply = speak_headlines(
            {
                "label": "sports",
                "query": "",
                "headlines": ["India win the toss", "Final goes to Super Over"],
            }
        )
        self.assertIn("sports headlines", reply)
        self.assertIn("1. India win the toss.", reply)
        self.assertIn("2. Final goes to Super Over.", reply)

    def test_search_lead(self) -> None:
        reply = speak_headlines(
            {"label": "cricket", "query": "cricket", "headlines": ["Kohli fifty"]}
        )
        self.assertIn("about cricket", reply)


class FetchHeadlinesTests(unittest.TestCase):
    def test_uses_india_google_news_then_speaks(self) -> None:
        self.assertEqual(normalize_topic("indian"), "india")
        feed = Mock()
        feed.text = (
            "<rss><channel>"
            "<item><title>First story - Times</title></item>"
            "<item><title>Second story</title></item>"
            "</channel></rss>"
        )
        feed.raise_for_status = Mock()
        with patch("friday.news.headlines.requests.get", return_value=feed) as get:
            data = fetch_headlines(topic="india")
        self.assertEqual(data["headlines"][0], "First story")
        url = get.call_args.args[0]
        self.assertIn("news.google.com", url)
        self.assertIn("gl=IN", url)


class NewsToolNameTests(unittest.TestCase):
    def test_tool_name(self) -> None:
        self.assertEqual(NEWS_HEADLINES, "news.headlines")


if __name__ == "__main__":
    unittest.main()
