from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from friday.browser.session import PlaywrightSession
from friday.browser.settings import BrowserSettings
from friday.browser.types import PageContent, SearchResult

logger = logging.getLogger("friday.browser.worker")

_STATE_NAME = "friday-browser-state.json"
_SIGNIN_START_URL = "https://www.bing.com/"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s friday.browser: %(message)s",
        stream=sys.stderr,
    )
    raw = _request_payload(argv if argv is not None else sys.argv[1:])
    settings = BrowserSettings.from_env()
    session = PlaywrightSession(
        headless=headless_for(str(raw.get("op") or ""), settings),
        timeout_ms=settings.timeout_ms,
        profile_dir=settings.profile_dir,
        persist=settings.persist,
    )
    try:
        result = _dispatch(session, raw)
    except Exception as exc:
        logger.exception("browser worker failed")
        _write({"ok": False, "error": str(exc)})
        return 1
    finally:
        session.close()
    _write({"ok": True, "data": result})
    return 0


def headless_for(operation: str, settings: BrowserSettings) -> bool:
    """Signing in means typing a password, so that one op is never headless."""
    return settings.headless and operation.strip().lower() != "login"


def _dispatch(session: PlaywrightSession, raw: dict) -> dict:
    operation = str(raw.get("op") or "").strip().lower()
    last_url = _load_last_url()
    if last_url:
        session.last_url = last_url

    if operation == "search":
        query = str(raw.get("query") or "").strip()
        if not query:
            raise ValueError("search requires a query")
        payload = _search_dict(session.search(query))
    elif operation == "open":
        url = str(raw.get("url") or "").strip()
        if not url:
            raise ValueError("open requires a url")
        payload = _page_dict(session.open_url(url))
    elif operation == "read":
        url = str(raw.get("url") or "").strip() or None
        payload = _page_dict(session.read(url))
    elif operation == "login":
        url = str(raw.get("url") or "").strip() or _SIGNIN_START_URL
        payload = _page_dict(session.wait_for_signin(url))
        payload["saved_profile"] = session.using_saved_profile
    elif operation == "click":
        target = str(raw.get("target") or "").strip()
        payload = _action_dict(session.click(target))
    elif operation == "fill":
        target = str(raw.get("target") or "").strip()
        value = str(raw.get("value") or "")
        payload = _action_dict(session.fill(target, value))
    elif operation == "download":
        target = str(raw.get("target") or "").strip()
        dest_dir = str(raw.get("dest_dir") or "").strip()
        if not dest_dir:
            raise ValueError("download requires dest_dir")
        payload = _action_dict(session.download(target, dest_dir))
    elif operation == "tabs":
        url = str(raw.get("url") or "").strip() or None
        tabs = session.tabs(url)
        payload = {
            "tabs": [
                {"index": tab.index, "url": tab.url, "title": tab.title}
                for tab in tabs
            ]
        }
    else:
        raise ValueError(f"unknown browser op: {operation}")

    _save_last_url(session.last_url)
    return payload


def _request_payload(argv: list[str]) -> dict:
    if argv:
        operation = argv[0].lstrip("-")
        if operation == "search":
            return {"op": "search", "query": " ".join(argv[1:]).strip()}
        if operation == "open":
            return {"op": "open", "url": " ".join(argv[1:]).strip()}
        if operation == "read":
            return {"op": "read", "url": " ".join(argv[1:]).strip() or None}
        if operation == "login":
            return {"op": "login", "url": " ".join(argv[1:]).strip() or None}
    stdin = sys.stdin.read()
    if not stdin.strip():
        raise ValueError("no browser request on stdin")
    payload = json.loads(stdin)
    if not isinstance(payload, dict):
        raise ValueError("browser request must be a JSON object")
    return payload


def _write(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _search_dict(result: SearchResult) -> dict:
    return {
        "query": result.query,
        "page_url": result.page_url,
        "title": result.title,
        "extracted": result.extracted,
        "hits": [
            {"title": hit.title, "url": hit.url, "snippet": hit.snippet}
            for hit in result.hits
        ],
    }


def _page_dict(page: PageContent) -> dict:
    return {
        "url": page.url,
        "title": page.title,
        "text": page.text,
        "extracted": page.extracted,
    }


def _action_dict(result) -> dict:
    return {
        "ok": bool(result.ok),
        "reply": str(result.reply or ""),
        "url": str(result.url or ""),
        "path": str(getattr(result, "path", "") or ""),
    }


def _state_path() -> Path:
    return Path(os_temp()) / _STATE_NAME


def os_temp() -> str:
    import os

    return os.environ.get("TEMP") or os.environ.get("TMP") or "."


def _load_last_url() -> str | None:
    path = _state_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    url = str(payload.get("last_url") or "").strip()
    return url or None


def _save_last_url(url: str | None) -> None:
    if not url:
        return
    path = _state_path()
    try:
        path.write_text(json.dumps({"last_url": url}), encoding="utf-8")
    except OSError:
        logger.debug("could not save browser state", exc_info=True)
