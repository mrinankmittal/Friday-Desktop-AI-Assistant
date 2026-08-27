from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from friday.browser.fake import FakeBrowser
from friday.os_adapters.fake import FakeOsAdapter
from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName
from friday.providers.fake import FakeVision
from friday.providers.vision import (
    WindowsOcrEngine,
    format_describe,
    verify_on_screen,
    windows_ocr_available,
)
from friday.os_adapters.types import WindowInfo
from friday.tools.builtin import build_legacy_registry
from friday.tools.types import ToolContext
from friday.tools.vision_tools import VISION_DESCRIBE, VISION_OCR, VISION_VERIFY
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


class ClassifyVisionTests(unittest.TestCase):
    def test_describe_phrases(self) -> None:
        for query in (
            "what's on my screen",
            "what is on the screen",
            "what do you see",
            "describe the screen",
            "tell me what's on my screen",
        ):
            intent = classify(query)
            self.assertEqual(intent.name, IntentName.VISION, query)
            self.assertEqual(intent.extra["action"], "describe", query)

    def test_ocr_phrases(self) -> None:
        for query in ("read the screen", "read the text on the screen", "ocr"):
            intent = classify(query)
            self.assertEqual(intent.name, IntentName.VISION, query)
            self.assertEqual(intent.extra["action"], "ocr", query)

    def test_verify_phrases(self) -> None:
        intent = classify("is chrome on the screen")
        self.assertEqual(intent.name, IntentName.VISION)
        self.assertEqual(intent.extra["action"], "verify")
        self.assertEqual(intent.extra["needle"], "chrome")

        seen = classify("can you see notepad on the screen")
        self.assertEqual(seen.extra["needle"], "notepad")

    def test_does_not_steal_screenshot_or_browser(self) -> None:
        self.assertEqual(classify("screenshot").extra["action"], "screenshot")
        self.assertEqual(classify("take a screenshot").name, IntentName.OS)
        self.assertEqual(classify("read this page").name, IntentName.BROWSER)
        self.assertEqual(classify("what is python").name, IntentName.CHAT)
        self.assertEqual(classify("tell me where is the screenshot").name, IntentName.CHAT)


class VisionToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = FakeOsAdapter()
        self.vision = FakeVision()
        self._memory_folder, memory, _root = make_memory_store()
        self.registry = build_legacy_registry(
            _UnusedActions(),
            os_adapter=self.adapter,
            browser=FakeBrowser(),
            vision=self.vision,
            memory=memory,
        )
        self.context = ToolContext(task_id="vision-test")

    def tearDown(self) -> None:
        self._memory_folder.cleanup()

    def test_describe_uses_windows_and_ocr(self) -> None:
        result = self.registry.invoke(VISION_DESCRIBE, {}, self.context)
        self.assertTrue(result.ok)
        self.assertIn("Chrome", result.data["reply"])
        self.assertIn("Python.org", result.data["reply"])
        self.assertEqual(self.adapter.calls[0][0], "screenshot")

    def test_ocr_speaks_text(self) -> None:
        result = self.registry.invoke(VISION_OCR, {}, self.context)
        self.assertTrue(result.ok)
        self.assertIn("Python.org", result.data["reply"])

    def test_verify_finds_window_title(self) -> None:
        result = self.registry.invoke(
            VISION_VERIFY, {"needle": "chrome"}, self.context
        )
        self.assertTrue(result.data["ok"])
        self.assertEqual(result.data["source"], "window")
        self.assertEqual(result.observation, "verified")

    def test_verify_finds_ocr_text(self) -> None:
        result = self.registry.invoke(
            VISION_VERIFY, {"needle": "python.org"}, self.context
        )
        self.assertTrue(result.data["ok"])
        self.assertEqual(result.data["source"], "ocr")

    def test_logs_do_not_include_ocr_body(self) -> None:
        with self.assertLogs("friday.tools", level="INFO") as captured:
            self.registry.invoke(VISION_DESCRIBE, {}, self.context)
        combined = "\n".join(captured.output)
        self.assertIn("vision.describe_screen", combined)
        self.assertNotIn("Welcome to Python.org", combined)


class VerifyHookTests(unittest.TestCase):
    def test_window_title_match(self) -> None:
        result = verify_on_screen(
            "chrome",
            windows=[WindowInfo(handle=1, title="Google Chrome")],
            ocr_text="",
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.source, "window")

    def test_ocr_match(self) -> None:
        result = verify_on_screen(
            "hello friday",
            windows=[],
            ocr_text="HELLO FRIDAY",
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.source, "ocr")

    def test_not_found(self) -> None:
        result = verify_on_screen("slack", windows=[], ocr_text="inbox")
        self.assertFalse(result.ok)

    def test_format_describe_without_ocr(self) -> None:
        spoken = format_describe(
            [WindowInfo(1, "Notepad")],
            "",
            ocr_available=False,
        )
        self.assertIn("Notepad", spoken)
        self.assertIn("isn't available", spoken)


class LiveWindowsOcrTests(unittest.TestCase):
    def test_reads_drawn_text(self) -> None:
        if not windows_ocr_available():
            self.skipTest("winocr is not installed")
        path = _draw_text_png("HELLO FRIDAY")
        try:
            text = WindowsOcrEngine().read(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertIn("HELLO", text.upper())
        self.assertIn("FRIDAY", text.upper())


def _draw_text_png(message: str) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.close()
    path = Path(handle.name)
    image = Image.new("RGB", (800, 200), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 48)
    except OSError:
        font = ImageFont.load_default()
    draw.text((20, 60), message, fill="black", font=font)
    image.save(path)
    return path


if __name__ == "__main__":
    unittest.main()
