import eel
import logging
import socket
import threading

from engine.features import *
from engine.command import *
import friday.memory.bridge  # noqa: F401  Settings inspect/delete

try:
    from queue import Empty as QueueEmpty
except ImportError:  # pragma: no cover
    QueueEmpty = Exception


HOST = "127.0.0.1"
PREFERRED_PORT = 8000
PORT_SEARCH_LIMIT = 100


def find_available_port() -> int:
    """Return a free loopback port for the local Eel server."""
    for port in range(PREFERRED_PORT, PREFERRED_PORT + PORT_SEARCH_LIMIT):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((HOST, port))
            except OSError:
                continue
            return port

    raise RuntimeError(
        f"No available port found between {PREFERRED_PORT} and "
        f"{PREFERRED_PORT + PORT_SEARCH_LIMIT - 1}."
    )


def _activate_from_hotword(activation_event, command_queue=None) -> None:
    """Forward a process-safe hotword signal to the browser UI."""
    activation_event.wait()

    leftover = ""
    if command_queue is not None:
        try:
            leftover = str(command_queue.get_nowait() or "").strip()
        except QueueEmpty:
            leftover = ""

    try:
        getattr(eel, "TriggerVoiceControl")(leftover)
    except Exception:
        logging.exception("Unable to activate the UI after hotword detection")


def _warmup_for_first_command() -> None:
    """Load Ollama and Windows voices while the UI opens, not on the first Friday."""
    try:
        from friday.providers.llm import warmup_ollama

        warmup_ollama()
    except Exception:
        logging.exception("Ollama warmup failed")
    try:
        from friday.providers.tts import warmup_sapi
        from friday.runtime import submit

        submit(warmup_sapi)
    except Exception:
        logging.exception("Voice warmup failed")


def start(activation_event=None, command_queue=None):
    eel.init("www")
    port = find_available_port()
    logging.info("Starting Friday UI at http://%s:%s", HOST, port)

    playAssistantSound()
    threading.Thread(target=_warmup_for_first_command, name="FridayWarmup", daemon=True).start()

    if activation_event is not None:
        threading.Thread(
            target=_activate_from_hotword,
            args=(activation_event, command_queue),
            name="HotwordUiBridge",
            daemon=True,
        ).start()

    eel.start("index.html", mode="edge", host=HOST, port=port, block=True)
