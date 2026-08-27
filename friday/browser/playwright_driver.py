"""Run Playwright in a fresh Python process so Eel/gevent cannot interfere."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from friday.browser.settings import BrowserSettings
from friday.browser.types import (
    BrowserActionResult,
    PageContent,
    SearchHit,
    SearchResult,
    TabInfo,
)
from friday.providers.types import project_root

logger = logging.getLogger("friday.browser")

_CREATE_NO_WINDOW = 0x08000000


class PlaywrightBrowser:
    """BrowserDriver that shells out to ``python -m friday.browser``."""

    name = "playwright"

    def __init__(self, settings: BrowserSettings | None = None) -> None:
        self._settings = settings or BrowserSettings.from_env()
        self.last_url: str | None = None

    def search(self, query: str) -> SearchResult:
        payload = self._run("search", query=query)
        result = _search_from_dict(payload)
        self.last_url = result.page_url or self.last_url
        return result

    def open_url(self, url: str) -> PageContent:
        payload = self._run("open", url=url)
        page = _page_from_dict(payload)
        self.last_url = page.url or self.last_url
        return page

    def read(self, url: str | None = None) -> PageContent:
        payload = self._run("read", url=url or self.last_url)
        page = _page_from_dict(payload)
        self.last_url = page.url or self.last_url
        return page

    def click(self, target: str) -> BrowserActionResult:
        payload = self._run("click", target=target)
        result = _action_from_dict(payload)
        if result.url:
            self.last_url = result.url
        return result

    def fill(self, target: str, value: str) -> BrowserActionResult:
        payload = self._run("fill", target=target, value=value)
        result = _action_from_dict(payload)
        if result.url:
            self.last_url = result.url
        return result

    def download(self, target: str, dest_dir: str) -> BrowserActionResult:
        payload = self._run("download", target=target, dest_dir=dest_dir)
        result = _action_from_dict(payload)
        if result.url:
            self.last_url = result.url
        return result

    def tabs(self, url: str | None = None) -> list[TabInfo]:
        payload = self._run("tabs", url=url)
        tabs = []
        for item in payload.get("tabs") or []:
            if not isinstance(item, dict):
                continue
            tabs.append(
                TabInfo(
                    index=int(item.get("index") or 0),
                    url=str(item.get("url") or ""),
                    title=str(item.get("title") or ""),
                )
            )
        if tabs:
            self.last_url = tabs[-1].url or self.last_url
        return tabs

    def close(self) -> None:
        return None

    def _run(self, operation: str, **fields: object) -> dict:
        request = {"op": operation, **{key: value for key, value in fields.items() if value is not None}}
        command = [sys.executable, "-m", "friday.browser"]
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["FRIDAY_BROWSER_HEADLESS"] = "true" if self._settings.headless else "false"
        env["FRIDAY_BROWSER_TIMEOUT_MS"] = str(self._settings.timeout_ms)
        kwargs: dict = {
            "input": json.dumps(request) + "\n",
            "capture_output": True,
            "text": True,
            "timeout": (self._settings.timeout_ms / 1000.0) + 15,
            "cwd": str(project_root()),
            "env": env,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = _CREATE_NO_WINDOW
        try:
            completed = subprocess.run(command, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("The browser timed out.") from exc
        except OSError as exc:
            raise RuntimeError(f"Could not start the browser worker: {exc}") from exc

        stderr = (completed.stderr or "").strip()
        if stderr:
            logger.info("browser worker: %s", stderr[-2000:])

        stdout = (completed.stdout or "").strip()
        if not stdout:
            raise RuntimeError(
                "The browser worker returned no result."
                + (f" {stderr}" if stderr else "")
            )
        try:
            payload = json.loads(_last_json_line(stdout))
        except json.JSONDecodeError as exc:
            raise RuntimeError("The browser worker returned invalid JSON.") from exc
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("error") or "Browser operation failed."))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("The browser worker returned an empty payload.")
        return data


def _last_json_line(stdout: str) -> str:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    return lines[-1] if lines else stdout


def _search_from_dict(data: dict) -> SearchResult:
    hits = []
    for item in data.get("hits") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if not title or not url:
            continue
        hits.append(
            SearchHit(
                title=title,
                url=url,
                snippet=str(item.get("snippet") or ""),
            )
        )
    return SearchResult(
        query=str(data.get("query") or ""),
        page_url=str(data.get("page_url") or ""),
        hits=hits,
        title=str(data.get("title") or ""),
        extracted=bool(data.get("extracted", True)),
    )


def _page_from_dict(data: dict) -> PageContent:
    return PageContent(
        url=str(data.get("url") or ""),
        title=str(data.get("title") or ""),
        text=str(data.get("text") or ""),
        extracted=bool(data.get("extracted", True)),
    )


def _action_from_dict(data: dict) -> BrowserActionResult:
    return BrowserActionResult(
        ok=bool(data.get("ok", True)),
        reply=str(data.get("reply") or ""),
        url=str(data.get("url") or ""),
        path=str(data.get("path") or ""),
    )


def worker_state_path() -> Path:
    return Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".") / "friday-browser-state.json"
