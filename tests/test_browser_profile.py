"""The saved browser profile: sign in once, stay signed in.

Every browser command used to open a blank context, so a login never outlived
the four seconds the command took. These cover the profile that replaced it,
and the ways it is allowed to fail.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from friday.browser.session import PlaywrightSession
from friday.browser.settings import PROFILE_DIR_NAME, BrowserSettings, default_profile_dir
from friday.browser.worker import _request_payload, headless_for
from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName
from friday.providers.types import project_root
from friday.rag.extract import is_blocked
from friday.tools.builtin import REGISTERED_TOOL_NAMES

PROFILE_ENV = "FRIDAY_BROWSER_PROFILE"
PERSIST_ENV = "FRIDAY_BROWSER_PERSIST"


def fake_playwright(*, persistent_ok: bool):
    """A stand-in for sync_playwright().start()."""
    playwright = MagicMock()
    context = MagicMock()
    page = MagicMock()
    page.is_closed.return_value = False
    context.pages = []
    context.new_page.return_value = page

    if persistent_ok:
        playwright.chromium.launch_persistent_context.return_value = context
    else:
        playwright.chromium.launch_persistent_context.side_effect = Exception(
            "profile is already in use"
        )

    browser = MagicMock()
    browser.new_context.return_value = context
    playwright.chromium.launch.return_value = browser
    return playwright, context, page


class ProfileSettingsTests(unittest.TestCase):
    def test_the_profile_is_saved_outside_temp(self) -> None:
        """A login has to survive a reboot, and Windows clears TEMP."""
        with patch.dict("os.environ", {}, clear=True):
            folder = default_profile_dir()
        self.assertEqual(folder.name, PROFILE_DIR_NAME)
        self.assertEqual(folder.parent, project_root())
        self.assertNotIn("temp", str(folder).lower())

    def test_persistence_is_on_by_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            settings = BrowserSettings.from_env()
        self.assertTrue(settings.persist)
        self.assertIsNotNone(settings.profile_dir)

    def test_persistence_can_be_turned_off(self) -> None:
        with patch.dict("os.environ", {PERSIST_ENV: "false"}, clear=True):
            self.assertFalse(BrowserSettings.from_env().persist)

    def test_the_profile_location_can_be_moved(self) -> None:
        with patch.dict("os.environ", {PROFILE_ENV: r"D:\somewhere\else"}, clear=True):
            self.assertEqual(
                BrowserSettings.from_env().profile_dir, Path(r"D:\somewhere\else")
            )


class SignInEntryPointTests(unittest.TestCase):
    def test_login_is_reachable_from_the_command_line(self) -> None:
        self.assertEqual(
            _request_payload(["login", "https://github.com"]),
            {"op": "login", "url": "https://github.com"},
        )

    def test_login_without_a_url_is_allowed(self) -> None:
        self.assertEqual(_request_payload(["login"]), {"op": "login", "url": None})

    def test_signing_in_is_never_headless(self) -> None:
        """You cannot type a password into a browser you cannot see."""
        settings = BrowserSettings(headless=True)
        self.assertFalse(headless_for("login", settings))
        self.assertTrue(headless_for("search", settings))

    def test_a_visible_browser_stays_visible(self) -> None:
        settings = BrowserSettings(headless=False)
        self.assertFalse(headless_for("search", settings))


class SessionProfileTests(unittest.TestCase):
    def _page_from(self, session: PlaywrightSession, playwright) -> object:
        started = MagicMock()
        started.start.return_value = playwright
        with patch("playwright.sync_api.sync_playwright", return_value=started):
            return session._ensure_page()

    def test_the_saved_profile_is_used_when_it_opens(self) -> None:
        playwright, _context, page = fake_playwright(persistent_ok=True)
        session = PlaywrightSession(profile_dir=Path("D:/profile"), persist=True)

        self.assertIs(self._page_from(session, playwright), page)
        self.assertTrue(session.using_saved_profile)
        playwright.chromium.launch_persistent_context.assert_called_once()
        playwright.chromium.launch.assert_not_called()

    def test_the_profile_directory_is_passed_through(self) -> None:
        playwright, _context, _page = fake_playwright(persistent_ok=True)
        session = PlaywrightSession(profile_dir=Path("D:/profile"), persist=True)
        self._page_from(session, playwright)

        options = playwright.chromium.launch_persistent_context.call_args.kwargs
        self.assertEqual(options["user_data_dir"], str(Path("D:/profile")))

    def test_a_locked_profile_falls_back_instead_of_failing(self) -> None:
        """Chromium locks the profile, so two overlapping commands collide.
        Browsing must degrade to signed out, not break."""
        playwright, _context, page = fake_playwright(persistent_ok=False)
        session = PlaywrightSession(profile_dir=Path("D:/profile"), persist=True)

        self.assertIs(self._page_from(session, playwright), page)
        self.assertFalse(session.using_saved_profile)
        playwright.chromium.launch.assert_called()

    def test_persistence_off_never_touches_the_profile(self) -> None:
        playwright, _context, page = fake_playwright(persistent_ok=True)
        session = PlaywrightSession(profile_dir=Path("D:/profile"), persist=False)

        self.assertIs(self._page_from(session, playwright), page)
        self.assertFalse(session.using_saved_profile)
        playwright.chromium.launch_persistent_context.assert_not_called()

    def test_edge_is_still_preferred_over_chrome(self) -> None:
        playwright, _context, _page = fake_playwright(persistent_ok=True)
        session = PlaywrightSession(profile_dir=Path("D:/profile"), persist=True)
        self._page_from(session, playwright)

        options = playwright.chromium.launch_persistent_context.call_args.kwargs
        self.assertEqual(options["channel"], "msedge")


class ProfileSecrecyTests(unittest.TestCase):
    """The profile stores live session cookies inside an allowed folder."""

    def test_the_cookie_store_cannot_be_read_by_the_file_tools(self) -> None:
        cookies = default_profile_dir() / "Default" / "Network" / "Cookies"
        self.assertTrue(is_blocked(cookies))

    def test_nothing_in_the_profile_can_be_read(self) -> None:
        folder = default_profile_dir()
        for name in ["Local State", "Default/Login Data", "Default/Preferences"]:
            with self.subTest(entry=name):
                self.assertTrue(is_blocked(folder / name))

    def test_a_relocated_profile_is_still_protected(self) -> None:
        with patch.dict("os.environ", {PROFILE_ENV: r"C:\Users\me\Documents\.edge-profile"}):
            folder = default_profile_dir()
        self.assertTrue(is_blocked(folder / "Default" / "Network" / "Cookies"))

    def test_ordinary_project_files_are_still_readable(self) -> None:
        self.assertFalse(is_blocked(project_root() / "README.md"))
        self.assertFalse(is_blocked(project_root() / "www" / "orb.js"))


class ProfileStealGuardTests(unittest.TestCase):
    """Sign-in is a one-time terminal step, so no voice command moved."""

    def test_connect_edge_is_not_an_integration(self) -> None:
        self.assertEqual(classify("connect edge").name, IntentName.CHAT)
        self.assertEqual(classify("sign in to edge").name, IntentName.CHAT)

    def test_the_real_connect_commands_still_route(self) -> None:
        for phrase in ["connect gmail", "connect slack", "connect discord"]:
            self.assertEqual(classify(phrase).name, IntentName.INTEGRATION)

    def test_browsing_commands_are_unchanged(self) -> None:
        self.assertEqual(classify("search the web for python").name, IntentName.BROWSER)
        self.assertEqual(classify("go to python.org").name, IntentName.BROWSER)

    def test_tool_count_is_unchanged(self) -> None:
        self.assertEqual(len(REGISTERED_TOOL_NAMES), 61)


if __name__ == "__main__":
    unittest.main()
