"""Screenshot OCR, describe, and on-screen verification."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path

from friday.os_adapters.types import WindowInfo
from friday.providers.types import DescribeResult, OcrResult, VerifyResult

logger = logging.getLogger("friday.providers.vision")

_SPEAK_LIMIT = 400
_WINDOW_LIMIT = 5
_OCR_TIMEOUT_SEC = 25


def format_describe(
    windows: list[WindowInfo],
    ocr_text: str,
    *,
    ocr_available: bool,
) -> str:
    titles = [window.title for window in windows[:_WINDOW_LIMIT] if window.title.strip()]
    extra = max(0, len(windows) - len(titles))
    parts: list[str] = []
    if titles:
        spoken = ", ".join(titles)
        if extra > 0:
            parts.append(f"Open windows include {spoken}, and {extra} more.")
        else:
            parts.append(f"Open windows: {spoken}.")
    body = " ".join(ocr_text.split())
    if body:
        parts.append("The screen text says: " + _clip(body, _SPEAK_LIMIT))
    elif ocr_available:
        parts.append("I couldn't read any text on the screen.")
    else:
        parts.append("I can see the screen, but text recognition isn't available.")
    return " ".join(parts) if parts else "I couldn't see anything on the screen."


def format_ocr(ocr: OcrResult) -> str:
    body = " ".join(ocr.text.split())
    if body:
        return _clip(body, _SPEAK_LIMIT)
    if ocr.available:
        return "I couldn't read any text on the screen."
    return "Text recognition isn't available on this PC."


def format_verify(ok: bool, needle: str, source: str) -> str:
    label = needle.strip() or "that"
    if ok and source == "window":
        return f"Yes, I can see a window named {label}."
    if ok:
        return f"Yes, I can see {label} on the screen."
    return f"I don't see {label} on the screen."


def verify_on_screen(
    needle: str,
    *,
    windows: list[WindowInfo],
    ocr_text: str,
    path: Path | str = "",
) -> VerifyResult:
    """Computer-agent hook: does ``needle`` appear in titles or OCR text?"""
    target = needle.strip()
    if not target:
        spoken = "Tell me what to look for on the screen."
        return VerifyResult(ok=False, spoken=spoken, source="", path=str(path))
    folded = target.casefold()
    for window in windows:
        if folded in window.title.casefold():
            spoken = format_verify(True, window.title, "window")
            return VerifyResult(
                ok=True,
                spoken=spoken,
                source="window",
                path=str(path),
            )
    if folded in ocr_text.casefold():
        spoken = format_verify(True, target, "ocr")
        return VerifyResult(ok=True, spoken=spoken, source="ocr", path=str(path))
    spoken = format_verify(False, target, "")
    return VerifyResult(ok=False, spoken=spoken, source="", path=str(path))


class ScreenVision:
    """Default vision provider: Windows OCR when installed, else titles only."""

    def __init__(self, engine: object | None = None) -> None:
        self._engine = engine if engine is not None else create_ocr_engine()
        self.name = getattr(self._engine, "name", "none")

    def ocr(self, path: Path) -> OcrResult:
        image = Path(path)
        if not image.is_file():
            return OcrResult(
                text="",
                provider=self.name,
                available=self._engine_available(),
                error="missing_image",
            )
        if not self._engine_available():
            return OcrResult(text="", provider="none", available=False)
        try:
            text = self._engine.read(image)
        except Exception as exc:
            logger.exception("OCR failed for %s", image)
            return OcrResult(
                text="",
                provider=self.name,
                available=True,
                error=str(exc),
            )
        return OcrResult(text=text, provider=self.name, available=True)

    def describe(
        self,
        path: Path,
        windows: list[WindowInfo] | None = None,
    ) -> DescribeResult:
        ocr = self.ocr(path)
        spoken = format_describe(
            list(windows or []),
            ocr.text,
            ocr_available=ocr.available,
        )
        return DescribeResult(spoken=spoken, ocr_text=ocr.text, path=str(path))

    def _engine_available(self) -> bool:
        return bool(getattr(self._engine, "available", True))


class WindowsOcrEngine:
    name = "windows"
    available = True

    def __init__(self, languages: tuple[str, ...] | None = None) -> None:
        env_lang = os.environ.get("FRIDAY_VISION_LANGUAGE", "").strip()
        self._languages = languages or (
            (env_lang,) if env_lang else ("en", "en-US")
        )

    def read(self, path: Path) -> str:
        last_error: Exception | None = None
        for lang in self._languages:
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(_read_windows_ocr, path, lang).result(
                        timeout=_OCR_TIMEOUT_SEC
                    )
            except FuturesTimeout as exc:
                last_error = RuntimeError("OCR timed out.")
                last_error.__cause__ = exc
            except Exception as exc:
                last_error = exc
                logger.info("Windows OCR language %s failed: %s", lang, exc)
        raise RuntimeError("Windows OCR failed.") from last_error


class UnavailableOcrEngine:
    name = "none"
    available = False

    def read(self, path: Path) -> str:
        return ""


def windows_ocr_available() -> bool:
    try:
        import winocr  # noqa: F401
    except ImportError:
        return False
    return True


def create_ocr_engine() -> WindowsOcrEngine | UnavailableOcrEngine:
    requested = os.environ.get("FRIDAY_VISION_PROVIDER", "auto").strip().lower() or "auto"
    if requested in {"none", "off", "titles"}:
        return UnavailableOcrEngine()
    if requested in {"auto", "windows", "winocr"} and windows_ocr_available():
        return WindowsOcrEngine()
    if requested in {"windows", "winocr"}:
        logger.warning("Windows OCR was requested but winocr is not installed")
        return UnavailableOcrEngine()
    return UnavailableOcrEngine()


def _read_windows_ocr(path: Path, lang: str) -> str:
    from PIL import Image
    import winocr

    image = Image.open(path)
    payload = winocr.recognize_pil_sync(image, lang=lang)
    if isinstance(payload, dict):
        return str(payload.get("text") or "").strip()
    return str(getattr(payload, "text", "") or "").strip()


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
