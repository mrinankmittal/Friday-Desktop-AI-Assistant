"""Phase 15: the declared environment must match the one that actually runs.

A requirements file rots the moment someone adds an import and forgets it, and
nothing fails until a fresh machine tries to start the app. These tests read
the real imports out of the source tree and compare them against what is
declared.
"""

from __future__ import annotations

import ast
import sys
import unittest
from importlib.metadata import PackageNotFoundError, packages_distributions, version
from pathlib import Path

from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName
from friday.tools.builtin import REGISTERED_TOOL_NAMES

ROOT = Path(__file__).resolve().parent.parent

RUNTIME = ROOT / "requirements.txt"
OPTIONAL = ROOT / "requirements-optional.txt"
DEV = ROOT / "requirements-dev.txt"
LOCK = ROOT / "requirements-lock.txt"
README = ROOT / "README.md"
LAUNCHER = ROOT / "friday.bat"

APP_SOURCES = ("friday", "engine")
APP_FILES = ("main.py", "run.py")

# First-party names that will never come from a distribution.
FIRST_PARTY = {"friday", "engine", "tests", "main", "run"}

# Imported behind a try/except for a provider we deliberately do not install.
# The architecture document lists these as available but not wired up.
KNOWN_ABSENT = {"faster_whisper"}


def _requirements(path: Path) -> dict[str, str]:
    """Map normalized distribution name to pinned version."""
    found: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name, _, pinned = line.partition("==")
        found[name.strip().lower().replace("_", "-")] = pinned.strip()
    return found


def _app_files() -> list[Path]:
    files = [ROOT / name for name in APP_FILES]
    for folder in APP_SOURCES:
        files.extend(sorted((ROOT / folder).rglob("*.py")))
    return [path for path in files if path.exists()]


def _imported_modules() -> set[str]:
    """Every top-level module name imported anywhere in the app, lazy ones too."""
    modules: set[str] = set()
    for path in _app_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    modules.add(node.module.split(".")[0])
    return modules


def _third_party(modules: set[str]) -> set[str]:
    return {
        name
        for name in modules
        if name not in sys.stdlib_module_names
        and name not in FIRST_PARTY
        and not name.startswith("_")
    }


class RequirementsFileTests(unittest.TestCase):
    def test_all_requirement_files_exist(self) -> None:
        for path in (RUNTIME, OPTIONAL, DEV, LOCK):
            self.assertTrue(path.exists(), f"missing {path.name}")

    def test_every_requirement_is_pinned(self) -> None:
        for path in (RUNTIME, OPTIONAL, DEV, LOCK):
            for name, pinned in _requirements(path).items():
                self.assertTrue(pinned, f"{path.name}: {name} is not pinned to a version")

    def test_runtime_requirements_are_installed_at_the_pinned_version(self) -> None:
        for name, pinned in _requirements(RUNTIME).items():
            with self.subTest(package=name):
                try:
                    installed = version(name)
                except PackageNotFoundError:  # pragma: no cover - env specific
                    self.fail(f"{name} is declared but not installed")
                self.assertEqual(installed, pinned)

    def test_lock_agrees_with_the_runtime_pins(self) -> None:
        lock = _requirements(LOCK)
        for name, pinned in _requirements(RUNTIME).items():
            with self.subTest(package=name):
                self.assertIn(name, lock, f"{name} is missing from the lockfile")
                self.assertEqual(lock[name], pinned)

    def test_test_tools_are_not_runtime_dependencies(self) -> None:
        runtime = _requirements(RUNTIME)
        for tool in _requirements(DEV):
            self.assertNotIn(tool, runtime, f"{tool} is a test tool, not a runtime one")

    def test_optional_extras_are_kept_out_of_the_runtime_set(self) -> None:
        """Local wake word does nothing without models/friday.onnx."""
        runtime = _requirements(RUNTIME)
        optional = _requirements(OPTIONAL)
        self.assertIn("openwakeword", optional)
        for name in optional:
            self.assertNotIn(name, runtime)


class DeclaredDependencyTests(unittest.TestCase):
    def test_every_imported_package_is_declared_somewhere(self) -> None:
        declared = set(_requirements(RUNTIME))
        declared |= set(_requirements(OPTIONAL))
        declared |= set(_requirements(DEV))
        mapping = packages_distributions()

        undeclared: list[str] = []
        for module in sorted(_third_party(_imported_modules())):
            if module in KNOWN_ABSENT:
                continue
            distributions = mapping.get(module)
            if not distributions:
                undeclared.append(f"{module} (not installed and not documented)")
                continue
            normalized = {
                dist.lower().replace("_", "-") for dist in distributions
            }
            if not normalized & declared:
                undeclared.append(f"{module} -> {sorted(distributions)}")

        self.assertEqual(
            undeclared,
            [],
            "these imports are not in any requirements file",
        )

    def test_core_packages_are_declared(self) -> None:
        """A short explicit list, so the scan above cannot pass vacuously."""
        runtime = _requirements(RUNTIME)
        for name in ["eel", "speechrecognition", "pyaudio", "pyttsx3", "requests"]:
            self.assertIn(name, runtime)


class LaunchDocumentationTests(unittest.TestCase):
    def test_readme_documents_install_and_launch(self) -> None:
        text = README.read_text(encoding="utf-8")
        self.assertIn("python run.py", text)
        self.assertIn("pip install -r requirements.txt", text)
        self.assertIn("python -m pytest", text)

    def test_readme_documents_the_confirm_default(self) -> None:
        text = README.read_text(encoding="utf-8")
        self.assertIn("FRIDAY_REQUIRE_CONFIRM_SEND", text)

    def test_windows_launcher_runs_the_documented_entry_point(self) -> None:
        script = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("run.py", script)
        self.assertIn(".venv\\Scripts\\python.exe", script)

    def test_secrets_stay_gitignored(self) -> None:
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for entry in [".env", "friday.db", "*.secrets.json"]:
            self.assertIn(entry, ignored)


class Phase15StealGuardTests(unittest.TestCase):
    """Packaging must not move a single command."""

    def test_tool_count_is_unchanged(self) -> None:
        self.assertEqual(len(REGISTERED_TOOL_NAMES), 61)

    def test_existing_commands_still_classify_the_same(self) -> None:
        self.assertEqual(classify("open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("send message to papa").name, IntentName.WHATSAPP)
        self.assertEqual(classify("list of windows").name, IntentName.OS)
        self.assertEqual(classify("forget it").name, IntentName.CHAT)
        self.assertEqual(classify("exit").name, IntentName.STOP)

    def test_no_voice_command_was_added_for_packaging(self) -> None:
        for phrase in ["install", "requirements", "update packages", "pip install"]:
            self.assertEqual(classify(phrase).name, IntentName.CHAT)


if __name__ == "__main__":
    unittest.main()
