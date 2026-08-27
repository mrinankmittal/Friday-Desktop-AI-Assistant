import eel
import time

from engine.config import ASSISTANT_NAME
from friday.language.bilingual import (
    detect_language,
    localize_reply,
    set_user_language,
    speak_language_for,
)
from friday.language.stt_fix import fix_transcript
from friday.providers import get_stt_provider, get_tts_provider
from friday.providers.settings import VoiceSettings
from friday.providers.stt import listen_with_retry
from friday.providers.types import SttResult
from friday.providers.tts import can_speak_hindi
from friday.runtime import clear_stop, request_stop, stop_requested, submit

_last_tts_at = 0.0


def _orb(state: str) -> None:
    """Drive the UI orb. It is decoration, so never let it break the voice loop."""
    try:
        getattr(eel, "SetOrbState")(state)
    except Exception:
        pass


def speak(text: object) -> None:
    global _last_tts_at
    message = str(text).strip()

    if not message:
        return

    settings = VoiceSettings.from_env()
    lang = "en" if settings.english_only() else speak_language_for(message)
    # David/Zira go silent on Devanagari. Only swap in Hindi text when a
    # Hindi voice is actually installed.
    spoken = (
        localize_reply(message, lang)
        if lang != "hi" or can_speak_hindi()
        else message
    )

    try:
        print(f"{ASSISTANT_NAME}: {spoken}", flush=True)
    except UnicodeEncodeError:
        print(
            f"{ASSISTANT_NAME}: {spoken.encode('utf-8', errors='replace').decode('ascii', errors='replace')}",
            flush=True,
        )

    getattr(eel, "DisplayMessage")(spoken)
    _orb("speaking")

    # Eel runs exposed Python functions in a worker thread. On Windows,
    # create the SAPI engine in that same thread so audio plays reliably.
    try:
        get_tts_provider().speak(
            spoken,
            before_play=lambda: getattr(eel, "receiverText")(spoken),
            language=lang,
        )
    finally:
        _orb("idle")
    _last_tts_at = time.monotonic()


def takecommand(*, confirm: bool = False) -> str:
    settings = VoiceSettings.from_env()
    recent_tts = (time.monotonic() - _last_tts_at) < 3.0
    if confirm or recent_tts:
        # Give the speakers time to settle so the next listen is not empty.
        time.sleep(0.8 if recent_tts else 0.45)
    _orb("listening")
    language = settings.effective_stt_language()
    phrase_limit = 4.0 if confirm else settings.stt_phrase_limit
    listen_timeout = 8.0 if confirm else settings.stt_listen_timeout
    max_attempts = 1 if confirm else settings.stt_attempts
    pause = settings.stt_pause_threshold

    result = SttResult(status="unknown")
    for attempt in range(max_attempts):
        if stop_requested():
            break
        if attempt > 0:
            _orb("listening")
        result = listen_with_retry(
            get_stt_provider(),
            language=language,
            timeout=listen_timeout + (attempt * 4.0),
            phrase_time_limit=phrase_limit + (attempt * 2.0),
            adjust_noise=attempt == 0 and not confirm and not recent_tts,
            retry=True,
            pause_threshold=pause + (attempt * 0.15),
        )
        if result.status == "ok" and str(result.text or "").strip():
            break
        if attempt >= max_attempts - 1 or stop_requested():
            break
        # Ask once mid-way; other retries are silent so you can keep talking.
        if attempt == max_attempts // 2:
            speak("Sorry, I missed that. Please say the command again.")
            time.sleep(0.4)
        else:
            time.sleep(0.25)

    if result.status in {"timeout", "unknown", "error"}:
        _orb("idle")

    if result.status == "timeout":
        print("Listening timed out")
        return ""
    if result.status == "unknown":
        print("Could not understand the audio")
        return ""
    if result.status == "error":
        print(f"Speech recognition service error: {result.error}")
        return ""

    query = fix_transcript(result.text.strip())
    if not query:
        _orb("idle")
        return ""

    if settings.english_only():
        set_user_language("en")
    else:
        set_user_language(detect_language(query))
    print(f"User said: {query}")

    _orb("thinking")
    getattr(eel, "DisplayMessage")(query)
    return query.lower()


def _run_command(query: str) -> bool:
    """Process one command and return False when voice control should stop."""
    print(f"Command: {query}")

    from friday.orchestrator import handle_user_request

    result = handle_user_request(
        query,
        speak=speak,
        listen=takecommand,
        confirm_listen=lambda: takecommand(confirm=True),
    )
    if result.assistant_reply is not None:
        getattr(eel, "receiverText")(result.assistant_reply)
        speak(result.assistant_reply)

    return result.continue_listening


@eel.expose
def stopVoiceControl() -> None:
    """Interrupt the running session. Returns without waiting for the mic."""
    request_stop()
    return None


@eel.expose
def confirm_send(accepted: bool) -> None:
    submit(lambda: _run_command("yes" if accepted else "no"))
    return None


@eel.expose
def allCommands(message: str | None = None, keep_listening: bool = False) -> None:
    """Queue one typed command or a microphone session, then return.

    Returning immediately is what keeps the Eel bridge free while the worker
    listens and speaks, so STOP and the UI callbacks still get through.
    """
    submit(lambda: _voice_session(message, keep_listening))
    return None


def _voice_session(message: str | None, keep_listening: bool) -> None:
    """The blocking loop. Runs on the voice worker, never on the Eel bridge.

    ``keep_listening`` is used when the wake phrase included the command,
    e.g. "Friday yes" — run that command then stay in the voice loop.
    """
    clear_stop()
    try:
        # A value from the chat input represents one command.  Calling this
        # without a value starts the continuous microphone command loop.
        if message is not None:
            query = str(message).strip()
            if query:
                settings = VoiceSettings.from_env()
                if settings.english_only():
                    set_user_language("en")
                else:
                    set_user_language(detect_language(query))
                getattr(eel, "senderText")(query)
                getattr(eel, "DisplayMessage")(query)
                if not _run_command(query.lower()):
                    return
                if not keep_listening:
                    return

        while True:
            if stop_requested():
                speak("Stopping voice control")
                break
            query = takecommand()
            if stop_requested():
                speak("Stopping voice control")
                break
            if not query:
                continue

            getattr(eel, "senderText")(query)
            if not _run_command(query):
                break

    except KeyboardInterrupt:
        print("Voice control stopped by user")
    finally:
        getattr(eel, "ShowHood")()
