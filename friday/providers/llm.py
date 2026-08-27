"""Local Ollama chat. HuggingChat is optional and off by default."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import time

import requests

from friday.providers.settings import LlmSettings, VoiceSettings

_ = VoiceSettings  # load .env

logger = logging.getLogger("friday.providers")

OLLAMA_TIMEOUT_SEC = 90.0
# /api/tags blocks while Ollama loads a model for someone else, and a cold
# load here measured ~16s, so a 5s budget turned a busy server into "offline".
OLLAMA_TAGS_TIMEOUT_SEC = 20.0
# Hold the model in memory between turns. Ollama's default is 5 minutes, which
# means an idle chat pays the cold-load wait over and over.
OLLAMA_KEEP_ALIVE = "30m"
_resolved_model: str | None = None
_HISTORY_LIMIT = 8
_SYSTEM = (
    "You are Friday, a local Windows voice assistant. Answer the user directly. "
    "Keep spoken answers to a few short sentences unless they ask for code or a list. "
    "Do not mention HuggingChat or API credits. "
    "You cannot send email, Slack, Discord, or WhatsApp from chat, and you cannot "
    "connect accounts from chat. If they want Gmail, tell them to say connect gmail. "
    "Never claim you already sent, drafted, or delivered a message. "
    "Never use the user's own email as the recipient for a message to someone else. "
    "If they want to email a person, tell them to say: send email to NAME saying MESSAGE. "
    "You cannot create or open files from chat. If they want a C++ file, tell them to "
    "say make a cpp file named NAME, then show me the file, then compile and run. "
    "The name can be anything. "
    "You cannot give live weather from chat. If they ask the weather, tell them to say "
    "what's the weather or weather in CITY. "
    "You cannot give live news from chat. If they want headlines, tell them to say "
    "what's the news, sports news, or news about TOPIC. "
    "You cannot control the keyboard from chat. If they want a hotkey, tell them to say "
    "copy that, paste, type TEXT, or press ctrl s. "
    "To drive an app, tell them to say play NAME on spotify, search NAME on whatsapp, "
    "or open APP and write TEXT, or write TEXT in APP. "
    "Reply in the same language the user used. If they spoke English, answer "
    "in English. If they spoke Hindi or Hinglish, answer in everyday spoken "
    "Hindi written in देवनागरी — the way a friend talks, short sentences, "
    "not textbook Hindi and not Roman letters like 'main theek hoon'. "
    "Your name in Hindi is फ्राइडे. Example: राम राम, मैं बिलकुल ठीक हूँ। तुम्हारा क्या हाल है?"
)
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_PREFERRED_MODELS = (
    "gemma3:4b",
    "gemma3:latest",
    "llama3.2:latest",
    "llama3.2",
    "llama3.1",
    "nemotron-3-nano:4b",
    "qwen3:8b",
)

_history: list[dict[str, str]] = []


def resolve_ollama_model(installed: list[str], requested: str = "") -> str:
    names = [item.strip() for item in installed if str(item).strip()]
    by_lower = {name.lower(): name for name in names}
    want = requested.strip().lower()
    if want:
        if want in by_lower:
            return by_lower[want]
        for name in names:
            if name.lower().startswith(want):
                return name
        stem = want.split(":", 1)[0]
        for name in names:
            lowered = name.lower()
            if lowered == stem or lowered.startswith(stem + ":"):
                return name
    for pref in _PREFERRED_MODELS:
        if pref.lower() in by_lower:
            return by_lower[pref.lower()]
    for pref in _PREFERRED_MODELS:
        stem = pref.split(":", 1)[0].lower()
        for name in names:
            if name.lower() == stem or name.lower().startswith(stem + ":"):
                return name
    for name in names:
        lowered = name.lower()
        if "cloud" in lowered or "llava" in lowered:
            continue
        return name
    return names[0] if names else ""


def complete_chat(prompt: str, *, settings: LlmSettings | None = None) -> str | None:
    """Chat with a short memory window. Used by the Friday chatbot tool."""
    global _history
    text = str(prompt or "").strip()
    if not text:
        return None
    config = settings or LlmSettings.from_env()
    from friday.language.bilingual import detect_language
    from friday.providers.settings import VoiceSettings as VoiceCfg

    if VoiceCfg.from_env().english_only() or detect_language(text) != "hi":
        turn_hint = (
            "The latest user message is English. Reply only in English. "
            "Do not use Hindi or देवनागरी, even if earlier messages were Hindi."
        )
    else:
        turn_hint = (
            "The latest user message is Hindi or Hinglish. Reply only in "
            "everyday spoken Hindi written in देवनागरी. Do not use English."
        )
    messages = [
        {"role": "system", "content": _SYSTEM},
        *_history[-_HISTORY_LIMIT:],
        {"role": "system", "content": turn_hint},
        {"role": "user", "content": text},
    ]
    reply = _ollama_chat(messages, host=config.host, model=config.model)
    if reply:
        _history.append({"role": "user", "content": text})
        _history.append({"role": "assistant", "content": reply})
        _history = _history[-_HISTORY_LIMIT:]
    return reply


def ollama_reply(prompt: str, *, timeout: float = OLLAMA_TIMEOUT_SEC) -> str | None:
    """Single-turn Ollama reply, or None if Ollama is not running."""
    text = str(prompt or "").strip()
    if not text:
        return None
    config = LlmSettings.from_env()
    return _ollama_chat(
        [{"role": "user", "content": text}],
        host=config.host,
        model=config.model,
        timeout=timeout,
    )


def reset_chat_history() -> None:
    global _history, _resolved_model
    _history = []
    _resolved_model = None


def warmup_ollama(settings: LlmSettings | None = None) -> bool:
    """Load the chat model now so the first spoken command is not a cold start.

    A first ``how are you`` after launch paid ~30s while gemma3:4b loaded.
    Later turns were ~3s. Starting that load with the UI removes the wait.
    """
    config = settings or LlmSettings.from_env()
    if not _ensure_ollama(config.host):
        logger.info("Ollama is not running; first chat will load the model later")
        return False
    chosen = _choose_model(config.host, config.model)
    if not chosen:
        return False
    started = time.monotonic()
    try:
        body = {
            "model": chosen,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {"num_predict": 1},
        }
        response = requests.post(
            f"{config.host}/api/chat",
            json={**body, "think": False},
            timeout=OLLAMA_TIMEOUT_SEC,
        )
        if response.status_code == 400:
            response = requests.post(
                f"{config.host}/api/chat",
                json=body,
                timeout=OLLAMA_TIMEOUT_SEC,
            )
        response.raise_for_status()
    except (requests.RequestException, OSError, ValueError, TypeError) as error:
        logger.info("Ollama warmup failed: %s", error)
        return False
    logger.info("Ollama model %s ready (%.1fs)", chosen, time.monotonic() - started)
    return True


def _ensure_ollama(host: str) -> bool:
    if _ping_ollama(host):
        return True
    exe = shutil.which("ollama")
    if not exe:
        return False
    logger.info("Starting Ollama so the first command is not waiting on a cold server")
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    try:
        subprocess.Popen(
            [exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except OSError as error:
        logger.info("Could not start Ollama: %s", error)
        return False
    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline:
        if _ping_ollama(host):
            return True
        time.sleep(0.4)
    return False


def _ping_ollama(host: str) -> bool:
    if not host:
        return False
    try:
        requests.get(f"{host}/api/tags", timeout=1.5)
        return True
    except (requests.RequestException, OSError):
        return False


def _ollama_chat(
    messages: list[dict[str, str]],
    *,
    host: str,
    model: str,
    timeout: float = OLLAMA_TIMEOUT_SEC,
) -> str | None:
    if not host:
        return None

    chosen = _choose_model(host, model)
    if not chosen:
        return None

    try:
        body = {
            "model": chosen,
            "messages": messages,
            "stream": False,
            "keep_alive": OLLAMA_KEEP_ALIVE,
        }
        response = requests.post(
            f"{host}/api/chat",
            json={**body, "think": False},
            timeout=timeout,
        )
        if response.status_code == 400:
            response = requests.post(
                f"{host}/api/chat",
                json=body,
                timeout=timeout,
            )
        response.raise_for_status()
        payload = response.json()
        message = payload.get("message") or {}
        reply = str(message.get("content") or payload.get("response") or "")
        return _spoken_text(reply) or None
    except (requests.RequestException, OSError, ValueError, TypeError, KeyError) as error:
        # The user sees "General chat is offline" when this fires, so make the
        # reason findable in the terminal instead of buried at INFO.
        logger.warning("Ollama chat failed (model=%s): %s", chosen, error)
        return None


def _choose_model(host: str, requested: str) -> str:
    """Pick the model to talk to.

    Listing installed models only exists to resolve loose names like "gemma3"
    onto "gemma3:4b". It is an optimisation, so a slow or refused /api/tags
    must not decide that chat is offline: fall back to the configured name and
    let /api/chat be the thing that succeeds or fails.
    """
    global _resolved_model
    if _resolved_model:
        return _resolved_model
    want = str(requested or "").strip()
    try:
        installed = _ollama_models(host)
    except (requests.RequestException, OSError, ValueError, TypeError, KeyError) as error:
        logger.info("Could not list Ollama models, trying %r as configured: %s", want, error)
        _resolved_model = want
        return want
    chosen = resolve_ollama_model(installed, want) if installed else want
    _resolved_model = chosen
    return chosen


def _ollama_models(host: str) -> list[str]:
    response = requests.get(f"{host}/api/tags", timeout=OLLAMA_TAGS_TIMEOUT_SEC)
    response.raise_for_status()
    models = response.json().get("models") or []
    names: list[str] = []
    for item in models:
        name = str(item.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _spoken_text(reply: str) -> str:
    cleaned = _THINK_BLOCK.sub("", reply).strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()
