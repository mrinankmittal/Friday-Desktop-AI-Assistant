"""Guards for the installed-app scanner and the fuzzy open matcher.

Store apps like Spotify and WhatsApp have no Start Menu shortcut and exist only
as ``Get-StartApps`` AppIDs, so the scanner must read that list, keep the real
apps, and record a ``shell:AppsFolder`` target that ``execute_open`` can launch.
The catalog then has full names ("Google Chrome") while people say short ones
("chrome"), so ``lookup_open_target`` grew a fuzzy fallback.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from friday.os_adapters.app_scan import (
    APPS_FOLDER_PREFIX,
    AppEntry,
    discover_apps,
    is_noise_name,
    parse_start_apps,
    sync_app_catalog,
)
from friday.os_adapters.apps import lookup_open_target

REAL_APPS = [
    {"Name": "Spotify", "AppID": "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"},
    {"Name": "WhatsApp", "AppID": "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"},
    {"Name": "Google Chrome", "AppID": "Chrome"},
    {"Name": "Visual Studio Code", "AppID": "Microsoft.VisualStudioCode"},
    {"Name": "Calculator", "AppID": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"},
]


def as_json(items: list[dict[str, str]]) -> str:
    return json.dumps(items)


class NoiseTests(unittest.TestCase):
    def test_uninstallers_and_help_links_are_noise(self) -> None:
        for name in [
            "Uninstall Python",
            "Read Me",
            "Release Notes",
            "Blender Website",
            "Node.js Documentation",
            "Modify Office",
            "Repair Steam",
        ]:
            with self.subTest(name=name):
                self.assertTrue(is_noise_name(name))

    def test_real_apps_are_not_noise(self) -> None:
        for name in ["Spotify", "WhatsApp", "Google Chrome", "Notepad", "Steam"]:
            with self.subTest(name=name):
                self.assertFalse(is_noise_name(name))


class ParseTests(unittest.TestCase):
    def test_store_apps_become_appsfolder_targets(self) -> None:
        entries = parse_start_apps(as_json(REAL_APPS))
        spotify = next(e for e in entries if e.name == "Spotify")
        self.assertEqual(
            spotify.target,
            APPS_FOLDER_PREFIX + "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify",
        )

    def test_a_single_object_is_accepted(self) -> None:
        entries = parse_start_apps(as_json([REAL_APPS[0]]).strip("[]"))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "Spotify")

    def test_entries_without_name_or_appid_are_dropped(self) -> None:
        raw = as_json(
            [
                {"Name": "", "AppID": "Something"},
                {"Name": "Ghost", "AppID": ""},
                {"Name": "Good", "AppID": "Good.App"},
            ]
        )
        entries = parse_start_apps(raw)
        self.assertEqual([e.name for e in entries], ["Good"])

    def test_noise_is_filtered_during_parse(self) -> None:
        raw = as_json(REAL_APPS + [{"Name": "Uninstall Spotify", "AppID": "x"}])
        names = [e.name for e in parse_start_apps(raw)]
        self.assertIn("Spotify", names)
        self.assertNotIn("Uninstall Spotify", names)

    def test_duplicate_names_keep_the_first_only(self) -> None:
        raw = as_json(
            [
                {"Name": "Spotify", "AppID": "one"},
                {"Name": "spotify", "AppID": "two"},
            ]
        )
        entries = parse_start_apps(raw)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].app_id, "one")

    def test_blank_or_broken_json_is_empty(self) -> None:
        self.assertEqual(parse_start_apps(""), [])
        self.assertEqual(parse_start_apps("not json"), [])
        self.assertEqual(parse_start_apps("null"), [])

    def test_discover_uses_the_injected_runner(self) -> None:
        entries = discover_apps(runner=lambda: as_json(REAL_APPS))
        self.assertEqual(len(entries), len(REAL_APPS))


class SyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self._folder.name) / "friday.db"

    def tearDown(self) -> None:
        self._folder.cleanup()

    def _names(self) -> list[str]:
        with sqlite3.connect(self.db_path) as connection:
            return [r[0] for r in connection.execute("SELECT name FROM sys_command")]

    def test_sync_creates_the_table_and_inserts_apps(self) -> None:
        result = sync_app_catalog(self.db_path, runner=lambda: as_json(REAL_APPS))
        self.assertEqual(result.added, len(REAL_APPS))
        self.assertEqual(result.skipped_existing, 0)
        self.assertIn("Spotify", self._names())
        self.assertIn("WhatsApp", self._names())

    def test_sync_is_additive_and_idempotent(self) -> None:
        sync_app_catalog(self.db_path, runner=lambda: as_json(REAL_APPS))
        again = sync_app_catalog(self.db_path, runner=lambda: as_json(REAL_APPS))
        self.assertEqual(again.added, 0)
        self.assertEqual(again.skipped_existing, len(REAL_APPS))
        self.assertEqual(len(self._names()), len(REAL_APPS))

    def test_sync_preserves_hand_curated_rows(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "CREATE TABLE sys_command (id INTEGER PRIMARY KEY, "
                "name VARCHAR(100) NOT NULL, path VARCHAR(1000) NOT NULL)"
            )
            connection.execute(
                "INSERT INTO sys_command (name, path) VALUES (?, ?)",
                ("Spotify", r"C:\custom\Spotify.exe"),
            )
            connection.commit()
        sync_app_catalog(self.db_path, runner=lambda: as_json(REAL_APPS))
        with sqlite3.connect(self.db_path) as connection:
            path = connection.execute(
                "SELECT path FROM sys_command WHERE name = 'Spotify'"
            ).fetchone()[0]
        self.assertEqual(path, r"C:\custom\Spotify.exe")

    def test_a_new_app_is_picked_up_on_rerun(self) -> None:
        sync_app_catalog(self.db_path, runner=lambda: as_json(REAL_APPS))
        extra = REAL_APPS + [{"Name": "Steam", "AppID": "Valve.Steam"}]
        result = sync_app_catalog(self.db_path, runner=lambda: as_json(extra))
        self.assertEqual(result.added, 1)
        self.assertIn("Steam", self._names())

    def test_apps_can_be_passed_directly(self) -> None:
        result = sync_app_catalog(
            self.db_path, apps=[AppEntry(name="Steam", app_id="Valve.Steam")]
        )
        self.assertEqual(result.added, 1)
        self.assertIn("Steam", self._names())


class ScannedCatalogOpensTests(unittest.TestCase):
    """After a scan the launcher must resolve both exact and spoken names."""

    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self._folder.name) / "friday.db"
        sync_app_catalog(self.db_path, runner=lambda: as_json(REAL_APPS))

    def tearDown(self) -> None:
        self._folder.cleanup()

    def test_a_store_app_opens_via_appsfolder(self) -> None:
        kind, target = lookup_open_target("spotify", self.db_path)
        self.assertEqual(kind, "path")
        self.assertTrue(target.startswith(APPS_FOLDER_PREFIX))
        self.assertIn("Spotify", target)

    def test_whatsapp_resolves(self) -> None:
        kind, target = lookup_open_target("whatsapp", self.db_path)
        self.assertEqual(kind, "path")
        self.assertIn("WhatsApp", target)

    def test_a_short_spoken_name_matches_the_full_catalog_name(self) -> None:
        _, chrome = lookup_open_target("chrome", self.db_path)
        self.assertIn("Chrome", chrome)
        _, code = lookup_open_target("code", self.db_path)
        self.assertIn("VisualStudioCode", code)
        _, studio = lookup_open_target("visual studio", self.db_path)
        self.assertIn("VisualStudioCode", studio)

    def test_an_unknown_app_still_falls_back_to_its_name(self) -> None:
        kind, target = lookup_open_target("some imaginary program", self.db_path)
        self.assertEqual(kind, "name")
        self.assertEqual(target, "some imaginary program")


class FuzzyScoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self._folder.name) / "friday.db"
        catalog = [
            AppEntry(name="Microsoft Word", app_id="word"),
            AppEntry(name="WordPad", app_id="wordpad"),
            AppEntry(name="Microsoft Edge", app_id="edge"),
            AppEntry(name="Google Chrome", app_id="chrome"),
        ]
        sync_app_catalog(self.db_path, apps=catalog)

    def tearDown(self) -> None:
        self._folder.cleanup()

    def test_exact_word_beats_longer_name(self) -> None:
        # "word" is a whole word in "Microsoft Word" but only a prefix in
        # "WordPad", so the whole-word hit must win.
        _, target = lookup_open_target("word", self.db_path)
        self.assertEqual(target, APPS_FOLDER_PREFIX + "word")

    def test_a_one_or_two_letter_query_never_fuzzy_matches(self) -> None:
        kind, target = lookup_open_target("go", self.db_path)
        self.assertEqual(kind, "name")
        self.assertEqual(target, "go")


if __name__ == "__main__":
    unittest.main()
