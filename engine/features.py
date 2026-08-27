import os
import re
import json
import time
import uuid
from pathlib import Path
from time import sleep
from urllib.parse import urlencode, urljoin, urlparse
from playsound import playsound
import eel
import logging
import sqlite3
import threading
import pyautogui
import requests
import pywhatkit as kit
from engine.command import speak
from engine.helper import comms_search_text, extract_yt_term, match_named_contact
from engine.config import ASSISTANT_NAME


_chatbot_client = None
_chatbot_lock = threading.Lock()
_huggingface_skip = False
# Playing assistant sound function

@eel.expose
def playAssistantSound():
    music_file = (
        Path(__file__).resolve().parent.parent
        / "www"
        / "assets"
        / "audio"
        / "ps5_start.mp3"
    )
    playsound(str(music_file))

def openCommand(query):
    query = query.replace(ASSISTANT_NAME, "")
    query = query.replace("open", "")
    query = query.strip().lower()
    app_name = query.strip()

    if not app_name:
        speak("Please specify an application or website.")
        return False

    try:
        from friday.os_adapters import get_os_adapter
        from friday.os_adapters.apps import (
            INCOMPLETE_OPEN_TARGETS,
            execute_open,
            lookup_open_target,
        )

        if app_name in INCOMPLETE_OPEN_TARGETS:
            speak("Please specify an application or website.")
            return False

        kind, target = lookup_open_target(app_name)
        if not target:
            speak("Please specify an application or website.")
            return False
        speak(f"Opening {app_name}")
        opened = execute_open(kind, target, get_os_adapter())
        if not opened:
            speak(f"Unable to open {app_name}.")
            return False
        return True

    except sqlite3.Error:
        logging.exception("Database error while looking up %r", app_name)
        speak("I couldn't access the command database.")

    except (FileNotFoundError, OSError):
        logging.exception("Could not open %r", app_name)
        speak(f"I couldn't find {app_name}.")

    except Exception:
        logging.exception("Unexpected error while opening %r", app_name)
        speak("Something went wrong while opening that command.")

    return False


def PlayYoutube(query: str) -> None:
    search_term = extract_yt_term(query)

    if not search_term:
        speak("Please tell me what you want to play on YouTube")
        return

    speak("Playing " + search_term + " on YouTube")
    kit.playonyt(search_term) # type: ignore
    

def hotword(activation_event=None, command_queue=None) -> None:
    from friday.providers.wake import run_wake_loop

    run_wake_loop(activation_event, command_queue=command_queue)

def _normalize_phone_number(value: object) -> str:
    """Return a WhatsApp-compatible international phone number."""
    raw_number = str(value).strip()
    has_country_prefix = raw_number.startswith("+")
    digits = re.sub(r"\D", "", raw_number)

    if has_country_prefix:
        return f"+{digits}" if digits else ""

    # Treat 10-digit local numbers and 0-prefixed local numbers as Indian.
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"

    return ""


# WhatsApp message and call contact lookup.
def _list_contacts() -> list[tuple[str, str]]:
    db_path = Path(__file__).resolve().parent.parent / "friday.db"
    with sqlite3.connect(db_path) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT name, mobile_no FROM contacts WHERE name IS NOT NULL")
        return [(str(name), str(mobile or "")) for name, mobile in cursor.fetchall()]


def findContact(query: str) -> tuple[str, str] | tuple[int, int]:
    search_text = comms_search_text(query, {ASSISTANT_NAME})

    if not search_text:
        speak("Please tell me the contact name.")
        return 0, 0

    try:
        contacts = _list_contacts()
    except sqlite3.Error:
        logging.exception("Database error while listing contacts")
        speak("I couldn't access your contacts database.")
        return 0, 0

    matched = match_named_contact(search_text, contacts)
    if matched is not None:
        matched_name, stored_number, _inline_message = matched
        mobile_number = _normalize_phone_number(stored_number)
        if not mobile_number:
            logging.warning("Invalid phone number stored for contact %r", matched_name)
            speak(f"The phone number for {matched_name} is not valid.")
            return 0, 0
        logging.info("Contact matched: %s", matched_name)
        return mobile_number, str(matched_name)

    # Fallback: partial name, still using the same table for every contact.
    db_path = Path(__file__).resolve().parent.parent / "friday.db"
    lookup_term = search_text.split()[0]

    try:
        with sqlite3.connect(db_path) as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT name, mobile_no
                FROM contacts
                WHERE name = ? COLLATE NOCASE
                   OR name LIKE ? COLLATE NOCASE
                ORDER BY
                    CASE WHEN name = ? COLLATE NOCASE THEN 0 ELSE 1 END,
                    LENGTH(name),
                    name
                LIMIT 1
                """,
                (lookup_term, f"%{lookup_term}%", lookup_term),
            )
            result = cursor.fetchone()

        if result is None:
            speak(f"I couldn't find {search_text} in your contacts.")
            return 0, 0

        matched_name, stored_number = result
        mobile_number = _normalize_phone_number(stored_number)

        if not mobile_number:
            logging.warning("Invalid phone number stored for contact %r", matched_name)
            speak(f"The phone number for {matched_name} is not valid.")
            return 0, 0

        logging.info("Contact matched: %s", matched_name)
        return mobile_number, str(matched_name)

    except sqlite3.Error:
        logging.exception("Database error while finding contact %r", search_text)
        speak("I couldn't access your contacts database.")
        return 0, 0

def _whatsapp_process_running() -> bool:
    """True when WhatsApp Desktop is already open (faster URI handoff)."""
    try:
        import subprocess

        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq WhatsApp.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
            creationflags=flags,
        )
        return "whatsapp.exe" in (completed.stdout or "").lower()
    except Exception:
        return False


def _whatsapp_launch_delay(explicit: float | None = None) -> float:
    """Seconds to wait after opening the WhatsApp URI before pressing Enter.

    Was hard-coded at 5s and made every send feel stuck. Prefer a short settle
    when Desktop is already running; override with FRIDAY_WHATSAPP_LAUNCH_DELAY.
    """
    if explicit is not None:
        return max(0.0, float(explicit))
    raw = os.environ.get("FRIDAY_WHATSAPP_LAUNCH_DELAY", "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return 0.7 if _whatsapp_process_running() else 1.4


def whatsapp(
    mobile_no: object,
    message: object,
    flag: str,
    name: object,
    launch_delay: float | None = None,
) -> bool:
    """Send a WhatsApp message or start a call through WhatsApp Desktop."""
    action = str(flag).strip().lower()
    contact_name = str(name).strip() or "the contact"
    phone_number = _normalize_phone_number(mobile_no)

    if action not in {"message", "call", "video"}:
        logging.error("Unsupported WhatsApp action: %r", flag)
        speak("I don't recognize that WhatsApp action.")
        return False

    if not phone_number:
        speak(f"The phone number for {contact_name} is not valid.")
        return False

    message_text = str(message).strip() if action == "message" else ""
    if action == "message" and not message_text:
        speak("Please tell me the message you want to send.")
        return False

    # WhatsApp expects an international number containing digits only.
    query_parameters = {"phone": phone_number.lstrip("+")}
    if message_text:
        query_parameters["text"] = message_text
    whatsapp_url = "whatsapp://send?" + urlencode(query_parameters)

    try:
        os.startfile(whatsapp_url)
        sleep(_whatsapp_launch_delay(launch_delay))

        if action == "message":
            # The URI opens the chat with the message already filled in.
            pyautogui.press("enter")
            success_message = f"Message sent successfully to {contact_name}."
        else:
            # WhatsApp has no stable public voice/video-call URI. These tab
            # counts target the call controls in the current desktop layout.
            tabs_to_control = 6 if action == "call" else 5
            pyautogui.hotkey("ctrl", "f")
            pyautogui.press("tab", presses=tabs_to_control, interval=0.1)
            pyautogui.press("enter")
            success_message = (
                f"Call initiated to {contact_name}."
                if action == "call"
                else f"Starting a video call with {contact_name}."
            )

        speak(success_message)
        return True

    except (OSError, pyautogui.FailSafeException):
        logging.exception(
            "Unable to perform WhatsApp action %r for %r",
            action,
            contact_name,
        )
        speak("I couldn't complete the WhatsApp action.")
        return False

# chat bot
_HF_HUB_HOST = "huggingface.co"
_HF_CHAT_URL = "https://huggingface.co/chat"
_HF_TOKEN_COOKIE = "token"
_HF_CHAT_COOKIE = "hf-chat"


class HuggingChatAuthError(RuntimeError):
    """Raised when Cookie-Editor Hugging Face cookies cannot authenticate HuggingChat."""


def _cookie_domain(cookie: dict) -> str:
    domain = str(cookie.get("domain") or _HF_HUB_HOST).strip().lower()
    return domain.lstrip(".")


def _is_huggingface_cookie(cookie: dict) -> bool:
    return _cookie_domain(cookie).endswith(_HF_HUB_HOST)


def _cookie_expiration(cookie: dict) -> float | None:
    expiration = cookie.get("expirationDate")
    if not isinstance(expiration, (int, float)) or expiration <= 0:
        return None
    # Cookie-Editor sometimes exports Chrome timestamps in milliseconds.
    if expiration > 1_000_000_000_000:
        expiration = expiration / 1000
    return float(expiration)


def _cookie_is_expired(cookie: dict) -> bool:
    expiration = _cookie_expiration(cookie)
    return expiration is not None and expiration < time.time()


def _normalize_cookie_records(raw_cookies: object) -> list[dict]:
    """Accept Cookie-Editor JSON (list) or HugChat login JSON (name/value map)."""
    if isinstance(raw_cookies, dict):
        nested = raw_cookies.get("cookies")
        if isinstance(nested, list):
            raw_cookies = nested
        elif all(isinstance(value, str) for value in raw_cookies.values()):
            return [
                {
                    "domain": _HF_HUB_HOST,
                    "name": str(name),
                    "path": "/",
                    "value": value,
                }
                for name, value in raw_cookies.items()
                if name and value
            ]
        else:
            return []

    if not isinstance(raw_cookies, list):
        return []

    records: list[dict] = []
    for cookie in raw_cookies:
        if not isinstance(cookie, dict):
            continue
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None or value == "":
            continue
        records.append(cookie)
    return records


def _load_huggingface_cookies(cookie_path: Path) -> list[dict]:
    """Load a Cookie-Editor or HugChat cookie export."""
    try:
        raw_cookies = json.loads(cookie_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        logging.warning("Unable to read Hugging Face cookie file: %s", cookie_path)
        return []

    return [
        cookie
        for cookie in _normalize_cookie_records(raw_cookies)
        if _is_huggingface_cookie(cookie)
    ]


def _find_cookie(cookies: list[dict], name: str) -> dict | None:
    for cookie in cookies:
        if cookie.get("name") != name:
            continue
        if _cookie_is_expired(cookie):
            continue
        if cookie.get("value"):
            return cookie
    return None


def _has_huggingface_cookies(cookie_path: Path) -> bool:
    """Return whether the Cookie-Editor export includes a live Hugging Face Hub token."""
    cookies = _load_huggingface_cookies(cookie_path)
    token = _find_cookie(cookies, _HF_TOKEN_COOKIE)
    if token is None:
        expired_token = next(
            (
                cookie
                for cookie in cookies
                if cookie.get("name") == _HF_TOKEN_COOKIE and _cookie_is_expired(cookie)
            ),
            None,
        )
        if expired_token is not None:
            logging.warning("Hugging Face token cookie has expired; session needs a refresh.")
        return False
    return True


def _save_huggingface_cookies(cookie_path: Path, cookies: list[dict]) -> None:
    cookie_path.write_text(
        json.dumps(cookies, indent=4) + "\n",
        encoding="utf-8",
    )


def _upsert_cookie(cookies: list[dict], name: str, value: str, domain: str = _HF_HUB_HOST) -> list[dict]:
    record = {
        "domain": domain if domain.startswith(".") or name != _HF_TOKEN_COOKIE else domain,
        "expirationDate": time.time() + 14 * 24 * 60 * 60,
        "hostOnly": name == _HF_TOKEN_COOKIE,
        "httpOnly": True,
        "name": name,
        "path": "/",
        "sameSite": "no_restriction",
        "secure": True,
        "session": False,
        "storeId": None,
        "value": value,
    }
    if name == _HF_CHAT_COOKIE:
        record["domain"] = "." + _HF_HUB_HOST if not domain.startswith(".") else domain
        record["hostOnly"] = False

    updated = False
    next_cookies: list[dict] = []
    for cookie in cookies:
        if cookie.get("name") == name and _is_huggingface_cookie(cookie):
            next_cookies.append(record)
            updated = True
        else:
            next_cookies.append(cookie)
    if not updated:
        next_cookies.append(record)
    return next_cookies


def _huggingface_session(cookies: list[dict]) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            # HugChat's default headers request brotli. requests cannot decode
            # `br` unless the brotli package is installed, which made a valid
            # Cookie-Editor export look like an expired session.
            "Accept-Encoding": "gzip, deflate",
            "Origin": "https://huggingface.co",
            "Referer": _HF_CHAT_URL,
        }
    )
    # Use a name/value map. Setting explicit domains in RequestsCookieJar
    # often drops the Hub `token` cookie on later hops, which sends
    # HuggingChat OAuth to /login instead of authorizing the chat app.
    session.cookies.update(
        {
            str(cookie.get("name")): str(cookie.get("value"))
            for cookie in cookies
            if cookie.get("name") and cookie.get("value")
        }
    )
    return session


def _absolute_huggingface_url(location: str | None, current: str) -> str | None:
    if not location:
        return None
    return urljoin(current, location)


def _html_form_action_and_fields(html: str, current_url: str) -> tuple[str | None, dict[str, str]]:
    form_match = re.search(r"<form\b[^>]*>.*?</form>", html or "", flags=re.I | re.S)
    if not form_match:
        return None, {}

    form_html = form_match.group(0)
    action_match = re.search(r'action=["\']([^"\']*)["\']', form_html, flags=re.I)
    action = _absolute_huggingface_url(
        action_match.group(1) if action_match else current_url,
        current_url,
    )

    fields: dict[str, str] = {}
    for tag in re.findall(r"<input\b[^>]*>", form_html, flags=re.I):
        name_match = re.search(r'\bname=["\']([^"\']+)["\']', tag, flags=re.I)
        if not name_match:
            continue
        value_match = re.search(r'\bvalue=["\']([^"\']*)["\']', tag, flags=re.I)
        fields[name_match.group(1)] = value_match.group(1) if value_match else ""
    return action, fields


def _obtain_hf_chat_cookie(session: requests.Session) -> str | None:
    """Complete HuggingChat OAuth using the Hub `token` from Cookie-Editor."""
    if _huggingface_chat_user(session) is not None:
        return session.cookies.get(_HF_CHAT_COOKIE)

    current = f"{_HF_CHAT_URL}/login"
    for _ in range(15):
        if _huggingface_chat_user(session) is not None:
            return session.cookies.get(_HF_CHAT_COOKIE)

        response = session.get(current, allow_redirects=False, timeout=30)
        logging.info(
            "HuggingChat login hop %s %s",
            response.status_code,
            urlparse(current).path,
        )

        if response.status_code in {301, 302, 303, 307, 308}:
            next_url = _absolute_huggingface_url(response.headers.get("Location"), current)
            if not next_url:
                break
            current = next_url
            continue

        if response.status_code != 200:
            break

        if _huggingface_chat_user(session) is not None:
            return session.cookies.get(_HF_CHAT_COOKIE)

        action, fields = _html_form_action_and_fields(response.text or "", current)
        if not action or not fields:
            break

        response = session.post(
            action,
            data=fields,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://huggingface.co",
                "Referer": current,
            },
            allow_redirects=False,
            timeout=30,
        )
        next_url = _absolute_huggingface_url(response.headers.get("Location"), action)
        if not next_url:
            break
        current = next_url

    session.get(_HF_CHAT_URL, allow_redirects=True, timeout=30)
    if _huggingface_chat_user(session) is None:
        return None
    return session.cookies.get(_HF_CHAT_COOKIE)


def _huggingface_chat_user(session: requests.Session) -> object | None:
    response = session.get(
        f"{_HF_CHAT_URL}/api/v2/user",
        headers={"Accept": "application/json", "Accept-Encoding": "gzip, deflate"},
        timeout=30,
    )
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, dict) and "json" in payload:
        payload = payload.get("json")
    return payload


def _merge_session_cookies(cookies: list[dict], session: requests.Session) -> list[dict]:
    merged = list(cookies)
    for jar_cookie in session.cookies:
        domain = str(jar_cookie.domain or _HF_HUB_HOST).lstrip(".")
        if (
            jar_cookie.name == _HF_TOKEN_COOKIE
            or not domain.endswith(_HF_HUB_HOST)
            or not jar_cookie.value
        ):
            continue
        merged = _upsert_cookie(merged, jar_cookie.name, jar_cookie.value, f".{domain}")
        if jar_cookie.expires:
            for cookie in merged:
                if cookie.get("name") == jar_cookie.name:
                    cookie["expirationDate"] = jar_cookie.expires
                    break
    return merged


def _hub_session_is_valid(session: requests.Session) -> bool:
    try:
        response = session.get(
            "https://huggingface.co/api/whoami-v2",
            headers={"Accept": "application/json", "Accept-Encoding": "gzip, deflate"},
            timeout=30,
        )
    except requests.RequestException:
        return False
    return response.status_code == 200


def _ensure_huggingface_chat_cookies(cookie_path: Path) -> list[dict]:
    """Turn a huggingface.co Cookie-Editor export into a HuggingChat session."""
    cookies = _load_huggingface_cookies(cookie_path)
    if _find_cookie(cookies, _HF_TOKEN_COOKIE) is None:
        raise HuggingChatAuthError(
            "Chatbot authentication is invalid. Export your logged-in "
            "Hugging Face cookies to engine/cookies.json and try again."
        )

    session = _huggingface_session(cookies)
    if _huggingface_chat_user(session) is not None:
        return cookies

    if not _hub_session_is_valid(session):
        raise HuggingChatAuthError(
            "The Hugging Face token cookie is no longer valid. Log in at "
            "huggingface.co/chat, then export cookies again with Cookie-Editor."
        )

    hf_chat = _obtain_hf_chat_cookie(session)
    if not hf_chat or _huggingface_chat_user(session) is None:
        raise HuggingChatAuthError(
            "HuggingChat login did not complete. Log in at huggingface.co/chat "
            "and export a fresh Cookie-Editor JSON file."
        )

    cookies = _merge_session_cookies(cookies, session)
    try:
        _save_huggingface_cookies(cookie_path, cookies)
    except OSError:
        logging.warning("Unable to write HuggingChat cookie back to %s", cookie_path)
    return cookies


def _parse_huggingface_payload(response: requests.Response) -> object:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("HuggingChat returned a non-JSON response.") from exc
    if isinstance(payload, dict) and "json" in payload:
        nested = payload.get("json")
        if nested is not None:
            return nested
    return payload


def _read_chat_stream(response: requests.Response) -> str:
    chunks: list[str] = []
    final_text = ""
    for line in response.iter_lines(decode_unicode=True):
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and "json" in event and isinstance(event.get("json"), dict):
            event = event["json"]
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "stream":
            chunks.append(str(event.get("token") or ""))
        elif event_type == "finalAnswer":
            final_text = str(event.get("text") or "")
        elif event_type == "status" and event.get("status") == "error":
            raise RuntimeError(str(event.get("message") or "HuggingChat returned an error."))
    return (final_text or "".join(chunks)).strip()


class _HuggingChatClient:
    """Minimal HuggingChat Omni client that accepts Cookie-Editor cookies."""

    def __init__(self, cookies: list[dict]) -> None:
        self.session = _huggingface_session(cookies)
        self.conversation_id: str | None = None
        self.root_message_id: str | None = None

    def chat(self, text: str) -> str:
        if not self.conversation_id:
            self._create_conversation()
        return self._send_message(text)

    def _create_conversation(self) -> None:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://huggingface.co",
            "Referer": _HF_CHAT_URL,
        }
        response = self.session.post(
            f"{_HF_CHAT_URL}/conversation",
            headers=headers,
            json={"model": "omni"},
            timeout=30,
        )
        if response.status_code == 401 or (
            response.headers.get("content-type", "").startswith("text/html")
        ):
            raise HuggingChatAuthError(
                "HuggingChat session is not logged in. Export cookies from "
                "huggingface.co/chat with Cookie-Editor."
            )
        if response.status_code != 200:
            raise RuntimeError(
                f"Unable to start a HuggingChat conversation ({response.status_code})."
            )

        payload = _parse_huggingface_payload(response)
        conversation = payload
        if isinstance(payload, dict) and "conversation" in payload:
            conversation = payload.get("conversation")
            if isinstance(conversation, str):
                try:
                    conversation = json.loads(conversation)
                except json.JSONDecodeError:
                    conversation = {}
            if isinstance(conversation, dict) and "json" in conversation:
                conversation = conversation.get("json")

        conversation_id = None
        root_message_id = None
        if isinstance(payload, dict):
            conversation_id = payload.get("conversationId") or payload.get("id")
        if isinstance(conversation, dict):
            conversation_id = conversation_id or conversation.get("id")
            root_message_id = conversation.get("rootMessageId")

        if not conversation_id:
            raise RuntimeError("HuggingChat did not return a conversation id.")

        self.conversation_id = str(conversation_id)
        self.root_message_id = str(root_message_id) if root_message_id else None
        if self.root_message_id is None:
            self._load_conversation_root()

    def _load_conversation_root(self) -> None:
        response = self.session.get(
            f"{_HF_CHAT_URL}/api/v2/conversations/{self.conversation_id}",
            timeout=30,
        )
        if response.status_code != 200:
            return
        payload = _parse_huggingface_payload(response)
        if isinstance(payload, dict):
            root_message_id = payload.get("rootMessageId")
            if root_message_id:
                self.root_message_id = str(root_message_id)

    def _send_message(self, text: str) -> str:
        request_json = {
            "id": self.root_message_id or str(uuid.uuid4()),
            "inputs": text,
            "is_retry": False,
            "web_search": False,
            "tools": [],
        }
        response = self.session.post(
            f"{_HF_CHAT_URL}/conversation/{self.conversation_id}",
            files={"data": (None, json.dumps(request_json))},
            headers={
                "Origin": "https://huggingface.co",
                "Referer": f"{_HF_CHAT_URL}/conversation/{self.conversation_id}",
                "Accept": "*/*",
            },
            stream=True,
            timeout=120,
        )
        if response.status_code == 401:
            raise HuggingChatAuthError(
                "HuggingChat session expired. Export a fresh Cookie-Editor JSON file."
            )
        if response.status_code != 200:
            raise RuntimeError(f"HuggingChat request failed ({response.status_code}).")

        reply = _read_chat_stream(response)
        if not reply:
            raise RuntimeError("HuggingChat returned an empty reply.")
        return reply


def _llm_provider() -> str:
    from friday.providers.settings import LlmSettings

    return LlmSettings.from_env().provider


def _local_chat_reply(user_input: str) -> str | None:
    from friday.providers.llm import complete_chat
    from friday.providers.settings import LlmSettings

    return complete_chat(user_input, settings=LlmSettings.from_env())


def _is_huggingchat_outage(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(token in text for token in ("402", "credit", "deplet", "quota"))


def chatbot(query: object) -> str:
    """Answer with Ollama by default. HuggingChat is only used if configured."""
    global _chatbot_client, _huggingface_skip

    user_input = str(query or "").strip()
    if not user_input:
        return "Please enter a message for the chatbot."

    provider = _llm_provider()
    if provider in {"ollama", "local", "auto"} or _huggingface_skip:
        return _local_chat_reply(user_input) or (
            "I could not reach Ollama. Start Ollama and try again."
        )

    cookie_path = Path(__file__).with_name("cookies.json")
    if not cookie_path.is_file() or not _has_huggingface_cookies(cookie_path):
        if not cookie_path.is_file():
            logging.error("Hugging Face cookie file was not found at %s", cookie_path)
        else:
            logging.warning(
                "Cookie-Editor export is missing a live Hugging Face token cookie"
            )
        local = _local_chat_reply(user_input)
        if local:
            return local
        if not cookie_path.is_file():
            return "Chatbot authentication is not configured."
        return (
            "Chatbot authentication is invalid. Export your logged-in "
            "Hugging Face cookies to engine/cookies.json and try again."
        )

    try:
        with _chatbot_lock:
            if _chatbot_client is None:
                cookies = _ensure_huggingface_chat_cookies(cookie_path)
                _chatbot_client = _HuggingChatClient(cookies)

            return _chatbot_client.chat(user_input)
    except HuggingChatAuthError as exc:
        _chatbot_client = None
        _huggingface_skip = True
        logging.warning("HuggingChat authentication failed: %s", exc)
        return _local_chat_reply(user_input) or str(exc)
    except (IndexError, ValueError, TypeError, json.JSONDecodeError) as exc:
        _chatbot_client = None
        _huggingface_skip = True
        logging.warning("HuggingChat payload was invalid: %s", exc)
        return _local_chat_reply(user_input) or (
            "Chatbot authentication has expired. Please export fresh Hugging Face cookies "
            "from huggingface.co/chat with Cookie-Editor."
        )
    except Exception as exc:
        _chatbot_client = None
        if _is_huggingchat_outage(exc):
            _huggingface_skip = True
            logging.warning(
                "HuggingChat unavailable (%s); using local fallback", exc
            )
        else:
            logging.exception("HuggingChat request failed")
        return _local_chat_reply(user_input) or (
            "Sorry, I could not reach the chatbot right now."
        )
