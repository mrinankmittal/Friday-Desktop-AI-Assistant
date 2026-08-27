from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class OcrResult:
    text: str = ""
    provider: str = "none"
    available: bool = True
    error: str | None = None


@dataclass(frozen=True)
class DescribeResult:
    spoken: str
    ocr_text: str = ""
    path: str = ""


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    spoken: str
    source: str = ""  # window | ocr | ""
    path: str = ""


class VisionProvider(Protocol):
    """Screenshot OCR / describe. Tests use a fake."""

    name: str

    def ocr(self, path: Path) -> OcrResult: ...

    def describe(
        self,
        path: Path,
        windows: list | None = None,
    ) -> DescribeResult: ...


@dataclass(frozen=True)
class SttResult:
    text: str = ""
    status: str = "ok"  # ok | timeout | unknown | error
    error: str | None = None


class SttProvider(Protocol):
    name: str

    def listen(
        self,
        *,
        timeout: float = 20.0,
        phrase_time_limit: float = 10.0,
        language: str = "en-in",
        adjust_noise: bool = True,
        **kwargs: object,
    ) -> SttResult: ...


class TtsProvider(Protocol):
    name: str

    def speak(
        self,
        text: str,
        before_play: Callable[[], None] | None = None,
        **kwargs,
    ) -> None: ...


class WakeWordProvider(Protocol):
    name: str

    def wait(self) -> bool:
        """Block until the wake word is heard. Return True on a match."""
        ...


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def wake_model_path() -> Path:
    return project_root() / "models" / "friday.onnx"
