"""A single worker thread for everything that blocks on the microphone.

Eel dispatches exposed functions on its own bridge. Listening for twenty
seconds or speaking a long sentence there freezes every other call, including
the STOP button that is supposed to interrupt exactly that. So the exposed
functions do nothing but hand work to this queue and return.

One worker thread, not a pool. A voice assistant has to finish speaking before
it starts listening again, and two overlapping sessions would open two
microphones, so the ordering the queue gives us is the point.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

logger = logging.getLogger("friday.runtime")

Job = Callable[[], None]

_JOIN_TIMEOUT = 5.0

_lock = threading.Lock()
_queue: queue.Queue[Job | None] = queue.Queue()
_worker: threading.Thread | None = None
_stop_event = threading.Event()
_idle = threading.Event()
_idle.set()
_running = 0


def submit(job: Job) -> None:
    """Queue work for the voice thread and return immediately."""
    _ensure_worker()
    _idle.clear()
    _queue.put(job)


def request_stop() -> None:
    """Ask the running session to stop. Safe to call while a job is blocking."""
    _stop_event.set()


def clear_stop() -> None:
    _stop_event.clear()


def stop_requested() -> bool:
    return _stop_event.is_set()


def is_busy() -> bool:
    return not _idle.is_set()


def pending() -> int:
    return _queue.qsize()


def wait_idle(timeout: float = 10.0) -> bool:
    """Block until the queue drains. For tests and shutdown, not the UI."""
    return _idle.wait(timeout)


def reset() -> None:
    """Drop queued work and clear the stop flag. Used by tests."""
    while True:
        try:
            _queue.get_nowait()
            _queue.task_done()
        except queue.Empty:
            break
    _stop_event.clear()
    _mark_idle_if_drained()


def shutdown(timeout: float = _JOIN_TIMEOUT) -> None:
    """Stop the worker thread. Used by tests; the app leaves it running."""
    global _worker
    with _lock:
        worker = _worker
        _worker = None
    if worker is None:
        return
    _queue.put(None)
    worker.join(timeout)


def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_run, name="FridayVoice", daemon=True)
        _worker.start()


def _run() -> None:
    global _running
    while True:
        job = _queue.get()
        if job is None:
            _queue.task_done()
            return
        with _lock:
            _running += 1
        try:
            job()
        except Exception:
            # One bad command must not take the microphone down with it.
            logger.exception("voice job failed")
        finally:
            with _lock:
                _running -= 1
            _queue.task_done()
            _mark_idle_if_drained()


def _mark_idle_if_drained() -> None:
    with _lock:
        if _running == 0 and _queue.empty():
            _idle.set()
