"""Launch the Friday UI and hotword listener in separate processes."""

import logging
import multiprocessing


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(processName)s: %(message)s",
        force=True,
    )


def start_friday(activation_event, command_queue) -> None:
    """Run the Eel application in its own process."""
    configure_logging()
    logging.info("Friday application process started")
    from main import start

    start(activation_event, command_queue)


def listen_for_hotword(activation_event, command_queue) -> None:
    """Run the microphone listener in its own process."""
    configure_logging()
    logging.info("Friday hotword process started")
    from engine.features import hotword

    hotword(activation_event, command_queue)


def stop_process(process: multiprocessing.Process, timeout: float = 5.0) -> None:
    """Allow a child to exit, then force it down if it remains alive."""
    if process.pid is None:
        return

    if not process.is_alive():
        process.join()
        return

    process.join(timeout)
    if process.is_alive():
        logging.warning("Stopping %s", process.name)
        process.terminate()
        process.join(timeout)


def main() -> None:
    configure_logging()

    # Explicit spawn behavior keeps process startup predictable on Windows.
    context = multiprocessing.get_context("spawn")
    activation_event = context.Event()
    command_queue = context.Queue()
    friday_process = context.Process(
        name="FridayApp",
        target=start_friday,
        args=(activation_event, command_queue),
    )
    hotword_process = context.Process(
        name="FridayHotword",
        target=listen_for_hotword,
        args=(activation_event, command_queue),
    )

    try:
        friday_process.start()
        hotword_process.start()

        # The application controls the overall lifetime of the system.
        friday_process.join()
    except KeyboardInterrupt:
        logging.info("Shutdown requested by user")
    finally:
        stop_process(hotword_process) # type: ignore
        stop_process(friday_process) # type: ignore

    logging.info(
        "Friday stopped (app exit=%s, hotword exit=%s)",
        friday_process.exitcode,
        hotword_process.exitcode,
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
