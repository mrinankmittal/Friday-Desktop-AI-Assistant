from __future__ import annotations

from friday.providers.types import SttResult


class FakeStt:
    name = "fake"

    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls = 0

    def listen(
        self,
        *,
        timeout: float = 20.0,
        phrase_time_limit: float = 10.0,
        language: str = "en-in",
        adjust_noise: bool = True,
        **kwargs: object,
    ) -> SttResult:
        self.calls += 1
        if not self.replies:
            return SttResult(status="timeout")
        return SttResult(text=self.replies.pop(0), status="ok")


class FakeTts:
    name = "fake"

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def speak(self, text: str, before_play=None, **_kwargs) -> None:
        self.spoken.append(str(text))
        if before_play is not None:
            before_play()


class FakeWakeWord:
    name = "fake"

    def __init__(self, heard: bool = True, follow_up: str = "") -> None:
        self.heard = heard
        self.follow_up = follow_up
        self.waits = 0

    def wait(self) -> bool:
        self.waits += 1
        return self.heard


class FakeVision:
    name = "fake"

    def __init__(self, ocr_text: str = "Welcome to Python.org") -> None:
        self.ocr_text = ocr_text
        self.calls: list[tuple] = []
        self.available = True

    def ocr(self, path):
        from friday.providers.types import OcrResult

        self.calls.append(("ocr", str(path)))
        return OcrResult(
            text=self.ocr_text,
            provider="fake",
            available=self.available,
        )

    def describe(self, path, windows=None):
        from friday.providers.types import DescribeResult
        from friday.providers.vision import format_describe

        self.calls.append(("describe", str(path)))
        titles = list(windows or [])
        spoken = format_describe(titles, self.ocr_text, ocr_available=self.available)
        return DescribeResult(spoken=spoken, ocr_text=self.ocr_text, path=str(path))
