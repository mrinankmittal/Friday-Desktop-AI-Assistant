"""Playwright page control. Imported only in the browser subprocess, not by Eel."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

from friday.browser.types import (
    BrowserActionResult,
    PageContent,
    SearchHit,
    SearchResult,
    TabInfo,
)
from friday.browser.urls import normalize_url, unwrap_redirect

logger = logging.getLogger("friday.browser")

_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
_WHITESPACE = re.compile(r"\s+")
_RESULT_LIMIT = 5
_TEXT_LIMIT = 8000
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"
)


class PlaywrightSession:
    def __init__(
        self,
        *,
        headless: bool = False,
        timeout_ms: int = 20000,
        profile_dir: Path | None = None,
        persist: bool = False,
    ) -> None:
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._profile_dir = Path(profile_dir) if profile_dir else None
        self._persist = persist and self._profile_dir is not None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self.last_url: str | None = None
        self.using_saved_profile = False

    def search(self, query: str) -> SearchResult:
        page = self._ensure_page()
        encoded = quote_plus(query)
        bing_url = f"https://www.bing.com/search?q={encoded}"
        hits: list[SearchHit] = []
        title = ""
        used = bing_url

        try:
            page.goto(bing_url, wait_until="domcontentloaded", timeout=self._timeout_ms)
            self._dismiss_consent(page)
            title = page.title() or ""
            hits = self._extract_bing(page)
        except Exception:
            logger.exception("Bing search failed; trying DuckDuckGo HTML form")

        if not hits:
            used = "https://html.duckduckgo.com/html/"
            hits = self._search_duckduckgo_form(page, query)
            title = page.title() or title
            used = page.url or used

        self.last_url = page.url or used
        return SearchResult(
            query=query,
            page_url=self.last_url,
            hits=hits[:_RESULT_LIMIT],
            title=title,
            extracted=True,
        )

    def open_url(self, url: str) -> PageContent:
        target = normalize_url(url)
        if target is None:
            return PageContent(url=url, title="", text="", extracted=False)
        page = self._ensure_page()
        page.goto(target, wait_until="domcontentloaded", timeout=self._timeout_ms)
        self._dismiss_consent(page)
        content = self._snapshot(page)
        self.last_url = content.url
        return content

    def read(self, url: str | None = None) -> PageContent:
        target = url or self.last_url
        if not target:
            return PageContent(url="", title="", text="", extracted=False)
        page = self._ensure_page()
        current = ""
        try:
            current = page.url or ""
        except Exception:
            current = ""
        if normalize_url(target) and current.rstrip("/") != target.rstrip("/"):
            page.goto(target, wait_until="domcontentloaded", timeout=self._timeout_ms)
            self._dismiss_consent(page)
        content = self._snapshot(page)
        self.last_url = content.url
        return content

    def click(self, target: str) -> BrowserActionResult:
        page = self._ensure_page()
        needle = target.strip()
        if not needle:
            return BrowserActionResult(ok=False, reply="What should I click?")
        try:
            locator = self._resolve_clickable(page, needle)
            locator.first.click(timeout=min(8000, self._timeout_ms))
            content = self._snapshot(page)
            self.last_url = content.url
            return BrowserActionResult(
                ok=True,
                reply=f"Clicked {needle}.",
                url=content.url,
            )
        except Exception as error:
            return BrowserActionResult(
                ok=False,
                reply=f"I couldn't click {needle}.",
                url=page.url or self.last_url or "",
            )

    def fill(self, target: str, value: str) -> BrowserActionResult:
        page = self._ensure_page()
        needle = target.strip()
        text = value
        if not needle:
            return BrowserActionResult(ok=False, reply="Which field should I fill?")
        try:
            locator = self._resolve_input(page, needle)
            locator.first.fill(text, timeout=min(8000, self._timeout_ms))
            content = self._snapshot(page)
            self.last_url = content.url
            return BrowserActionResult(
                ok=True,
                reply=f"Filled {needle}.",
                url=content.url,
            )
        except Exception:
            return BrowserActionResult(
                ok=False,
                reply=f"I couldn't fill {needle}.",
                url=page.url or self.last_url or "",
            )

    def download(self, target: str, dest_dir: str) -> BrowserActionResult:
        page = self._ensure_page()
        folder = Path(dest_dir).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        needle = target.strip()
        try:
            with page.expect_download(timeout=min(20000, self._timeout_ms + 5000)) as download_info:
                if needle.lower().startswith("http"):
                    page.goto(needle, wait_until="domcontentloaded", timeout=self._timeout_ms)
                else:
                    locator = self._resolve_clickable(page, needle)
                    locator.first.click(timeout=min(8000, self._timeout_ms))
            download = download_info.value
            suggested = download.suggested_filename or "download.bin"
            dest = folder / Path(suggested).name
            download.save_as(str(dest))
            self.last_url = page.url or self.last_url
            return BrowserActionResult(
                ok=True,
                reply=f"Downloaded {dest.name} to {dest.parent}.",
                url=self.last_url or "",
                path=str(dest),
            )
        except Exception:
            return BrowserActionResult(
                ok=False,
                reply="I couldn't download that file.",
                url=page.url or self.last_url or "",
            )

    def tabs(self, url: str | None = None) -> list[TabInfo]:
        self._ensure_page()
        context = self._context
        if context is None:
            return []
        if url:
            target = normalize_url(url) or url
            page = context.new_page()
            page.set_default_timeout(self._timeout_ms)
            page.goto(target, wait_until="domcontentloaded", timeout=self._timeout_ms)
            self._page = page
            self.last_url = page.url or target
        infos: list[TabInfo] = []
        for index, page in enumerate(context.pages):
            try:
                infos.append(
                    TabInfo(
                        index=index,
                        url=page.url or "",
                        title=page.title() or "",
                    )
                )
            except Exception:
                continue
        return infos

    def close(self) -> None:
        page, context, browser, playwright = (
            self._page,
            self._context,
            self._browser,
            self._playwright,
        )
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        for closer in (page, context, browser):
            if closer is None:
                continue
            try:
                closer.close()
            except Exception:
                logger.debug("browser close ignored", exc_info=True)
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                logger.debug("playwright stop ignored", exc_info=True)

    def _ensure_page(self):
        if self._page is not None:
            try:
                if not self._page.is_closed():
                    return self._page
            except Exception:
                self._page = None
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._context = self._open_context(self._playwright)
        existing = list(self._context.pages)
        self._page = existing[0] if existing else self._context.new_page()
        self._page.set_default_timeout(self._timeout_ms)
        return self._page

    def _open_context(self, playwright):
        """Prefer the saved profile so logins survive between commands."""
        if self._persist:
            context = self._launch_persistent(playwright)
            if context is not None:
                self.using_saved_profile = True
                return context
        self._browser = self._launch(playwright)
        return self._browser.new_context(user_agent=_USER_AGENT, locale="en-US")

    def _launch_persistent(self, playwright):
        """Open the saved profile, or return None so the caller can fall back.

        Chromium takes an exclusive lock on a profile directory, so this fails
        whenever a second Friday browser command overlaps. A locked profile
        must degrade to a throwaway session rather than break browsing.
        """
        assert self._profile_dir is not None
        errors: list[str] = []
        for channel in ("msedge", "chrome", None):
            options: dict = {
                "user_data_dir": str(self._profile_dir),
                "headless": self._headless,
                "args": _LAUNCH_ARGS,
                "user_agent": _USER_AGENT,
                "locale": "en-US",
            }
            if channel:
                options["channel"] = channel
            try:
                self._profile_dir.mkdir(parents=True, exist_ok=True)
                context = playwright.chromium.launch_persistent_context(**options)
                logger.info(
                    "Using the saved profile at %s (channel=%s headless=%s)",
                    self._profile_dir,
                    channel,
                    self._headless,
                )
                return context
            except Exception as exc:
                errors.append(f"{channel or 'bundled'}: {exc}")
        logger.warning(
            "Could not open the saved profile at %s, browsing signed out instead: %s",
            self._profile_dir,
            "; ".join(errors),
        )
        return None

    def _launch(self, playwright):
        errors: list[str] = []
        for channel in ("msedge", "chrome", None):
            options: dict = {"headless": self._headless, "args": _LAUNCH_ARGS}
            if channel:
                options["channel"] = channel
            try:
                browser = playwright.chromium.launch(**options)
                logger.info(
                    "Launched Chromium channel=%s headless=%s",
                    channel,
                    self._headless,
                )
                return browser
            except Exception as exc:
                errors.append(f"{channel or 'bundled'}: {exc}")
        raise RuntimeError("Could not launch a browser. " + "; ".join(errors))

    def wait_for_signin(self, url: str, *, timeout_sec: float = 600.0) -> PageContent:
        """Open the saved profile and hold it open while the user signs in.

        This is the only way a login can be captured: normal commands close the
        browser in a few seconds, which is not long enough to type a password.
        """
        page = self._ensure_page()
        target = normalize_url(url) or url
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=self._timeout_ms)
        except Exception:
            logger.warning("Could not open %s for sign-in", target, exc_info=True)

        logger.info("Sign in, then close the browser window to save it.")
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                if not self._context.pages:
                    break
            except Exception:
                break
            time.sleep(0.5)

        content = PageContent(url=target, title="", text="", extracted=True)
        try:
            content = self._snapshot(page)
        except Exception:
            logger.debug("no page left to snapshot after sign-in", exc_info=True)
        self.last_url = content.url or target
        return content

    def _resolve_clickable(self, page, needle: str):
        if needle.startswith("#") or needle.startswith(".") or needle.startswith("//"):
            return page.locator(needle)
        by_role = page.get_by_role("button", name=re.compile(re.escape(needle), re.I))
        if by_role.count() > 0:
            return by_role
        by_link = page.get_by_role("link", name=re.compile(re.escape(needle), re.I))
        if by_link.count() > 0:
            return by_link
        return page.get_by_text(re.compile(re.escape(needle), re.I))

    def _resolve_input(self, page, needle: str):
        if needle.startswith("#") or needle.startswith(".") or "[" in needle:
            return page.locator(needle)
        by_label = page.get_by_label(re.compile(re.escape(needle), re.I))
        if by_label.count() > 0:
            return by_label
        by_placeholder = page.get_by_placeholder(re.compile(re.escape(needle), re.I))
        if by_placeholder.count() > 0:
            return by_placeholder
        return page.locator(
            f"input[name*='{needle}' i], textarea[name*='{needle}' i], "
            f"input[id*='{needle}' i], textarea[id*='{needle}' i]"
        )

    def _snapshot(self, page) -> PageContent:
        url = ""
        title = ""
        try:
            url = page.url or ""
            title = (page.title() or "").strip()
        except Exception:
            logger.debug("page metadata failed", exc_info=True)
        text = _clip(_clean_text(self._visible_text(page)), _TEXT_LIMIT)
        return PageContent(url=url, title=title, text=text, extracted=bool(title or text))

    def _visible_text(self, page) -> str:
        for selector in ("article", "main", "[role='main']", "body"):
            try:
                locator = page.locator(selector).first
                if locator.count() == 0:
                    continue
                text = locator.inner_text(timeout=min(4000, self._timeout_ms))
                if len(text.strip()) >= 40:
                    return text
            except Exception:
                continue
        try:
            return page.inner_text("body")
        except Exception:
            return ""

    def _extract_bing(self, page) -> list[SearchHit]:
        hits: list[SearchHit] = []
        try:
            page.wait_for_selector("li.b_algo h2 a", timeout=min(8000, self._timeout_ms))
        except Exception:
            return hits
        rows = page.locator("li.b_algo")
        count = min(rows.count(), _RESULT_LIMIT)
        for index in range(count):
            row = rows.nth(index)
            title, href = self._first_link(row, "h2 a")
            snippet = self._inner_text(row, ".b_caption p, p")
            hit = _hit(title, href, snippet)
            if hit is not None:
                hits.append(hit)
        return hits

    def _search_duckduckgo_form(self, page, query: str) -> list[SearchHit]:
        page.goto(
            "https://html.duckduckgo.com/html/",
            wait_until="domcontentloaded",
            timeout=self._timeout_ms,
        )
        page.locator("input[name='q']").first.fill(query)
        page.locator("input[type='submit']").first.click()
        return self._extract_ddg_html(page)

    def _extract_ddg_html(self, page) -> list[SearchHit]:
        hits: list[SearchHit] = []
        try:
            page.wait_for_selector(
                ".result__a, .result__title a",
                timeout=min(8000, self._timeout_ms),
            )
        except Exception:
            return hits
        rows = page.locator(".result")
        count = min(rows.count(), _RESULT_LIMIT)
        for index in range(count):
            row = rows.nth(index)
            title, href = self._first_link(row, ".result__a, .result__title a")
            snippet = self._inner_text(row, ".result__snippet")
            hit = _hit(title, href, snippet)
            if hit is not None:
                hits.append(hit)
        return hits

    @staticmethod
    def _first_link(root, selector: str) -> tuple[str, str]:
        try:
            link = root.locator(selector).first
            if link.count() == 0:
                return "", ""
            title = (link.inner_text(timeout=2000) or "").strip()
            href = link.get_attribute("href") or ""
            return title, href
        except Exception:
            return "", ""

    @staticmethod
    def _inner_text(root, selector: str) -> str:
        try:
            node = root.locator(selector).first
            if node.count() == 0:
                return ""
            return (node.inner_text(timeout=2000) or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _dismiss_consent(page) -> None:
        for selector in (
            "button:has-text('Accept')",
            "button:has-text('I agree')",
            "button:has-text('Agree')",
            "#bnp_btn_accept",
            "#onetrust-accept-btn-handler",
        ):
            try:
                button = page.locator(selector).first
                if button.count() and button.is_visible():
                    button.click(timeout=1000)
                    return
            except Exception:
                continue


def _hit(title: str, href: str, snippet: str) -> SearchHit | None:
    url = unwrap_redirect(href.strip())
    url = normalize_url(url) or url
    cleaned_title = _clean_text(title)
    if not cleaned_title or not url:
        return None
    lowered = url.lower()
    if "duckduckgo.com" in lowered and ("/l/" in lowered or "y.js" in lowered):
        return None
    if "bing.com/aclick" in lowered:
        return None
    return SearchHit(
        title=cleaned_title,
        url=url,
        snippet=_clip(_clean_text(snippet), 240),
    )


def _clean_text(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
