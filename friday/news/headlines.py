"""Live headlines from Google News (India) with BBC fallbacks."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote_plus

import requests

TIMEOUT_SEC = 8.0
HEADLINE_LIMIT = 4
USER_AGENT = "Friday/1.0 (local Windows voice assistant)"
_LOCALE = "hl=en-IN&gl=IN&ceid=IN:en"

CATEGORIES = (
    "top",
    "india",
    "world",
    "business",
    "technology",
    "sports",
    "entertainment",
    "science",
    "health",
)

_TOPIC_FEEDS = {
    "top": (
        f"https://news.google.com/rss?{_LOCALE}",
        "https://feeds.bbci.co.uk/news/rss.xml",
    ),
    "india": (
        f"https://news.google.com/rss/headlines/section/topic/NATION?{_LOCALE}",
        "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml",
    ),
    "world": (
        f"https://news.google.com/rss/headlines/section/topic/WORLD?{_LOCALE}",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
    ),
    "business": (
        f"https://news.google.com/rss/headlines/section/topic/BUSINESS?{_LOCALE}",
        "https://feeds.bbci.co.uk/news/business/rss.xml",
    ),
    "technology": (
        f"https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?{_LOCALE}",
        "https://feeds.bbci.co.uk/news/technology/rss.xml",
    ),
    "sports": (
        f"https://news.google.com/rss/headlines/section/topic/SPORTS?{_LOCALE}",
        "https://feeds.bbci.co.uk/sport/rss.xml",
    ),
    "entertainment": (
        f"https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?{_LOCALE}",
        "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
    ),
    "science": (
        f"https://news.google.com/rss/headlines/section/topic/SCIENCE?{_LOCALE}",
        "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    ),
    "health": (
        f"https://news.google.com/rss/headlines/section/topic/HEALTH?{_LOCALE}",
        "https://feeds.bbci.co.uk/news/health/rss.xml",
    ),
}

_TOPIC_ALIASES = {
    "top": "top",
    "latest": "top",
    "today": "top",
    "india": "india",
    "indian": "india",
    "national": "india",
    "nation": "india",
    "world": "world",
    "international": "world",
    "global": "world",
    "business": "business",
    "market": "business",
    "markets": "business",
    "economy": "business",
    "tech": "technology",
    "technology": "technology",
    "science": "science",
    "sports": "sports",
    "sport": "sports",
    "entertainment": "entertainment",
    "bollywood": "entertainment",
    "health": "health",
    "भारत": "india",
    "खेल": "sports",
    "खेलकूद": "sports",
    "तकनीक": "technology",
    "व्यापार": "business",
    "मनोरंजन": "entertainment",
    "विज्ञान": "science",
    "स्वास्थ्य": "health",
    "दुनिया": "world",
}

_LABEL = {
    "top": "top",
    "india": "India",
    "world": "world",
    "business": "business",
    "technology": "technology",
    "sports": "sports",
    "entertainment": "entertainment",
    "science": "science",
    "health": "health",
}

_ATOM = "{http://www.w3.org/2005/Atom}"
_STRIP_SOURCE = re.compile(r"\s+-\s+[^-]+$")


def normalize_topic(raw: str) -> str | None:
    """Return a category name, or None if this should be a search query."""
    key = " ".join(raw.lower().split())
    return _TOPIC_ALIASES.get(key)


def _search_feeds(query: str) -> tuple[str, ...]:
    encoded = quote_plus(query)
    return (
        f"https://news.google.com/rss/search?q={encoded}&{_LOCALE}",
        f"https://news.google.com/rss?{_LOCALE}",
    )


def _clean_title(raw: str) -> str:
    text = html.unescape(" ".join(raw.split()))
    text = _STRIP_SOURCE.sub("", text).strip(" -")
    return text


def _parse_feed(xml_text: str) -> list[str]:
    root = ET.fromstring(xml_text)
    titles: list[str] = []
    for tag in ("item", f"{_ATOM}entry"):
        for node in root.iter(tag):
            title_node = node.find("title")
            if title_node is None:
                title_node = node.find(f"{_ATOM}title")
            title = _clean_title(title_node.text or "") if title_node is not None else ""
            if title and title not in titles:
                titles.append(title)
            if len(titles) >= HEADLINE_LIMIT:
                return titles
    return titles


def _download(url: str) -> list[str]:
    response = requests.get(
        url,
        timeout=TIMEOUT_SEC,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"},
    )
    response.raise_for_status()
    return _parse_feed(response.text)


def fetch_headlines(topic: str = "", query: str = "") -> dict[str, Any]:
    """Headlines for a category, or a search if ``query`` is set."""
    search = " ".join(query.split())
    category = "top"
    feeds: tuple[str, ...]
    if search:
        feeds = _search_feeds(search)
        label = search
    else:
        category = normalize_topic(topic) or (topic.strip().lower() if topic.strip() in CATEGORIES else "top")
        if category not in _TOPIC_FEEDS:
            category = "top"
        feeds = _TOPIC_FEEDS[category]
        label = _LABEL[category]

    last_error: Exception | None = None
    for url in feeds:
        try:
            headlines = _download(url)
        except (requests.RequestException, ET.ParseError, ValueError) as error:
            last_error = error
            continue
        if headlines:
            return {
                "topic": category if not search else "search",
                "label": label,
                "query": search,
                "headlines": headlines,
            }
    if last_error is not None:
        raise last_error
    raise LookupError("No headlines came back.")


def speak_headlines(data: dict[str, Any], language: str | None = None) -> str:
    from friday.language.bilingual import user_language

    headlines = [str(item).strip() for item in (data.get("headlines") or []) if str(item).strip()]
    lang = (language or user_language() or "en").split("-", 1)[0].lower()
    if not headlines:
        return (
            "अभी कोई हेडलाइन नहीं मिली."
            if lang == "hi"
            else "I couldn't find any headlines just now."
        )
    label = str(data.get("label") or "top")
    query = str(data.get("query") or "").strip()
    if lang == "hi":
        if query:
            lead = f"{query} की ताज़ा हेडलाइनें ये हैं."
        elif label == "top":
            lead = "ये रही आज की मुख्य हेडलाइनें."
        else:
            lead = f"ये रही ताज़ा {label} हेडलाइनें."
    elif query:
        lead = f"Here are the latest headlines about {query}."
    elif label == "top":
        lead = "Here are the top headlines."
    else:
        lead = f"Here are the latest {label} headlines."
    numbered = " ".join(
        f"{index}. {title}." for index, title in enumerate(headlines, start=1)
    )
    return f"{lead} {numbered}"
