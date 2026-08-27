"""Phase 14: keep blocking work off the Eel bridge, and one SQLite writer."""

from __future__ import annotations

import sqlite3
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from friday.db import pool
from friday.memory.store import connect
from friday.orchestrator.intents import classify
from friday.orchestrator.models import IntentName
from friday.runtime import voice
from friday.tools.builtin import REGISTERED_TOOL_NAMES
from tests.helpers import make_memory_store


class VoiceWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        voice.reset()

    def tearDown(self) -> None:
        voice.request_stop()
        voice.wait_idle(5.0)
        voice.reset()

    def test_submit_returns_before_the_job_finishes(self) -> None:
        """This is the whole point: the bridge must not wait for the mic."""
        gate = threading.Event()
        done = threading.Event()

        def slow_job() -> None:
            gate.wait(5.0)
            done.set()

        started = time.monotonic()
        voice.submit(slow_job)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.5, "submit blocked the caller")
        self.assertFalse(done.is_set())
        self.assertTrue(voice.is_busy())

        gate.set()
        self.assertTrue(voice.wait_idle(5.0))
        self.assertTrue(done.is_set())

    def test_job_runs_off_the_calling_thread(self) -> None:
        seen: list[int] = []
        voice.submit(lambda: seen.append(threading.get_ident()))
        self.assertTrue(voice.wait_idle(5.0))
        self.assertEqual(len(seen), 1)
        self.assertNotEqual(seen[0], threading.get_ident())

    def test_stop_reaches_a_job_that_is_already_running(self) -> None:
        """STOP used to sit behind the blocking listen. Now it lands."""
        running = threading.Event()
        stopped = threading.Event()

        def loop() -> None:
            running.set()
            while not voice.stop_requested():
                time.sleep(0.01)
            stopped.set()

        voice.submit(loop)
        self.assertTrue(running.wait(5.0))
        self.assertFalse(stopped.is_set())

        voice.request_stop()
        self.assertTrue(stopped.wait(5.0), "stop never reached the running job")

    def test_clear_stop_resets_the_flag(self) -> None:
        voice.request_stop()
        self.assertTrue(voice.stop_requested())
        voice.clear_stop()
        self.assertFalse(voice.stop_requested())

    def test_sessions_run_one_at_a_time_in_order(self) -> None:
        """Two microphones open at once would be worse than a slow bridge."""
        order: list[str] = []
        overlap: list[str] = []
        active = threading.Lock()

        def job(name: str):
            def run() -> None:
                if not active.acquire(blocking=False):
                    overlap.append(name)
                    return
                try:
                    order.append(name)
                    time.sleep(0.02)
                finally:
                    active.release()

            return run

        for name in ["a", "b", "c", "d"]:
            voice.submit(job(name))
        self.assertTrue(voice.wait_idle(10.0))

        self.assertEqual(order, ["a", "b", "c", "d"])
        self.assertEqual(overlap, [])

    def test_a_failing_job_does_not_kill_the_worker(self) -> None:
        def boom() -> None:
            raise RuntimeError("bad command")

        after: list[str] = []
        voice.submit(boom)
        voice.submit(lambda: after.append("still alive"))
        self.assertTrue(voice.wait_idle(5.0))
        self.assertEqual(after, ["still alive"])

    def test_idle_when_nothing_is_queued(self) -> None:
        self.assertTrue(voice.wait_idle(5.0))
        self.assertFalse(voice.is_busy())
        self.assertEqual(voice.pending(), 0)


class SingleWriterSqliteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder, self.memory, self.root = make_memory_store()

    def tearDown(self) -> None:
        pool.forget(self.memory.db_path)
        self._folder.cleanup()

    def test_migrations_run_once_per_path_not_once_per_call(self) -> None:
        pool.forget(self.memory.db_path)
        with patch(
            "friday.db.pool.apply_migrations", wraps=pool.apply_migrations
        ) as migrate:
            for index in range(5):
                self.memory.remember(f"fact {index}")
            self.assertEqual(migrate.call_count, 1)

    def test_connection_is_closed_after_the_block(self) -> None:
        with connect(self.memory.db_path) as connection:
            connection.execute("SELECT 1")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_wal_is_enabled(self) -> None:
        with connect(self.memory.db_path) as connection:
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(str(mode).lower(), "wal")

    def test_busy_timeout_is_set(self) -> None:
        with connect(self.memory.db_path) as connection:
            timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        self.assertEqual(int(timeout), pool.BUSY_TIMEOUT_MS)

    def test_concurrent_writers_all_land(self) -> None:
        """Before the lock, two threads writing raced for the file."""
        errors: list[BaseException] = []
        start = threading.Barrier(6)

        def writer(index: int) -> None:
            try:
                start.wait(10.0)
                for item in range(5):
                    self.memory.remember(f"thread {index} item {item}")
            except BaseException as error:  # noqa: BLE001 - reported below
                errors.append(error)

        threads = [
            threading.Thread(target=writer, args=(index,), name=f"w{index}")
            for index in range(6)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30.0)

        self.assertEqual(errors, [])
        self.assertEqual(len(self.memory.list_memories(limit=50)), 30)

    def test_readers_and_writers_do_not_deadlock(self) -> None:
        errors: list[BaseException] = []

        def reader() -> None:
            try:
                for _ in range(20):
                    self.memory.list_memories(limit=10)
            except BaseException as error:  # noqa: BLE001 - reported below
                errors.append(error)

        def writer() -> None:
            try:
                for index in range(20):
                    self.memory.remember(f"row {index}")
            except BaseException as error:  # noqa: BLE001 - reported below
                errors.append(error)

        threads = [threading.Thread(target=reader), threading.Thread(target=writer)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30.0)
        self.assertEqual(errors, [])

    def test_failed_transaction_rolls_back(self) -> None:
        before = len(self.memory.list_memories(limit=50))
        with self.assertRaises(RuntimeError):
            with connect(self.memory.db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO memories (kind, content, source, created_at, updated_at)
                    VALUES ('fact', 'should not survive', 'test', '', '')
                    """
                )
                raise RuntimeError("abort")
        self.assertEqual(len(self.memory.list_memories(limit=50)), before)

    def test_nested_session_on_one_thread_does_not_deadlock(self) -> None:
        with connect(self.memory.db_path) as outer:
            outer.execute("SELECT 1")
            with connect(self.memory.db_path) as inner:
                inner.execute("SELECT 1")


class ExposedBridgeTests(unittest.TestCase):
    """The Eel-exposed functions must hand work off and return."""

    def setUp(self) -> None:
        import engine.command as command

        self.command = command
        voice.reset()
        self._eel = patch.object(command, "eel", MagicMock())
        self._eel.start()

    def tearDown(self) -> None:
        voice.request_stop()
        voice.wait_idle(5.0)
        voice.reset()
        self._eel.stop()

    def test_all_commands_returns_without_running_the_command(self) -> None:
        gate = threading.Event()
        seen: list[str] = []

        def fake_run(query: str) -> bool:
            gate.wait(5.0)
            seen.append(query)
            return False

        with patch.object(self.command, "_run_command", fake_run):
            started = time.monotonic()
            self.assertIsNone(self.command.allCommands("open chrome"))
            elapsed = time.monotonic() - started

            self.assertLess(elapsed, 0.5, "the Eel bridge waited for the command")
            self.assertEqual(seen, [])

            gate.set()
            self.assertTrue(voice.wait_idle(5.0))
            self.assertEqual(seen, ["open chrome"])

    def test_stop_is_accepted_while_a_session_is_running(self) -> None:
        running = threading.Event()
        stopped = threading.Event()

        def fake_run(_query: str) -> bool:
            running.set()
            while not voice.stop_requested():
                time.sleep(0.01)
            stopped.set()
            return False

        with patch.object(self.command, "_run_command", fake_run):
            self.command.allCommands("open chrome")
            self.assertTrue(running.wait(5.0))

            started = time.monotonic()
            self.assertIsNone(self.command.stopVoiceControl())
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertTrue(stopped.wait(5.0))

    def test_confirm_send_is_queued_not_run_inline(self) -> None:
        seen: list[str] = []

        with patch.object(
            self.command, "_run_command", lambda query: seen.append(query) or False
        ):
            self.command.confirm_send(True)
            self.assertTrue(voice.wait_idle(5.0))
            self.assertEqual(seen, ["yes"])

            self.command.confirm_send(False)
            self.assertTrue(voice.wait_idle(5.0))
            self.assertEqual(seen, ["yes", "no"])

    def test_typed_command_still_shows_in_the_ui(self) -> None:
        with patch.object(self.command, "_run_command", lambda _query: False):
            self.command.allCommands("open chrome")
            self.assertTrue(voice.wait_idle(5.0))
        self.command.eel.senderText.assert_called_with("open chrome")
        self.command.eel.ShowHood.assert_called()

    def test_session_clears_a_stale_stop_flag(self) -> None:
        voice.request_stop()
        with patch.object(self.command, "_run_command", lambda _query: False):
            self.command.allCommands("open chrome")
            self.assertTrue(voice.wait_idle(5.0))
        self.assertFalse(voice.stop_requested())


class Phase14StealGuardTests(unittest.TestCase):
    """Phase 14 is plumbing. It must not move a single command."""

    def test_tool_count_is_unchanged(self) -> None:
        self.assertEqual(len(REGISTERED_TOOL_NAMES), 61)

    def test_existing_commands_still_classify_the_same(self) -> None:
        self.assertEqual(classify("open chrome").name, IntentName.OPEN)
        self.assertEqual(classify("send message to papa").name, IntentName.WHATSAPP)
        self.assertEqual(classify("list of windows").name, IntentName.OS)
        self.assertEqual(classify("search my documents for goa").name, IntentName.RESEARCH)
        self.assertEqual(classify("forget it").name, IntentName.CHAT)
        self.assertEqual(classify("exit").name, IntentName.STOP)

    def test_no_voice_command_was_added_for_the_worker(self) -> None:
        for phrase in ["queue", "worker", "stop the queue", "flush the queue"]:
            self.assertEqual(classify(phrase).name, IntentName.CHAT)


if __name__ == "__main__":
    unittest.main()
