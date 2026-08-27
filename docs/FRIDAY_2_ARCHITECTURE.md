# Friday 2.0 Architecture and Migration Plan

**Status:** Phase 15 complete. All fifteen planned phases are implemented; what remains is the definition-of-done list in section 14, not new plumbing.  
**Date:** 2026-08-21  
**Constraint:** Preserve working Friday 1.0 behavior. Grow a modular core around it. Do not replace the app in one jump.

This document is the source of truth for migrating the current desktop assistant to Friday 2.0. Implementation proceeds one phase at a time after this plan is accepted.

---

## 1. Friday 1.0 as it exists

Friday 1.0 is a **Windows desktop voice assistant**, not a multi-service backend. It is a Python process that hosts a local web UI in Microsoft Edge via [Eel](https://github.com/python-eel/Eel).

### 1.1 Repository map (application code only)

| Path | Role |
| --- | --- |
| `run.py` | Process supervisor. Spawns UI process + hotword process. |
| `main.py` | Eel server. Serves `www/`, opens Edge, bridges hotword → UI. |
| `engine/command.py` | Speech-to-text, text-to-speech, **keyword command router**. |
| `engine/features.py` | Feature implementations: open apps, YouTube, WhatsApp, hotword, HuggingChat. |
| `engine/db.py` | CSV → SQLite contact import. |
| `engine/helper.py` | String helpers for YouTube and contact-name cleanup. |
| `engine/config.py` | `ASSISTANT_NAME = "Friday"`. |
| `engine/cookies.json` | Hugging Face session cookies (secret; gitignored). |
| `www/` | Orb UI, chat drawer, Eel JS bridge. `orb.js` renders the F.R.I.D.A.Y. orb; `engine/command.py` pushes it through idle → listening → thinking → speaking. SiriWave was removed. |
| `friday.db` | SQLite: contacts, catalogs, memories, documents, notes, reminders, integrations metadata, task runs, audit logs, event logs |
| `friday/browser/` | Playwright browser agent (search / open URL / read page). |
| `friday/observability/` | JSON task traces (`friday.events`) and SQLite `event_logs` for the Developer log panel. |
| `friday/memory/` | Long-term facts, conversation rows, episodic task runs, Settings Eel bridge. |
| `friday/files/` | Allowlisted file search / read / write / move. |
| `friday/code/` | Workspace-scoped read / patch / unittest (no free-form shell). |
| `friday/productivity/` | Spoken reminder due-time parsing. |
| `friday/integrations/` | Gmail / Slack / Discord OAuth, sidecar secrets, confirmed sends. |
| `friday/rag/` | Chunk, local hashed embeddings, extract TXT/MD/CSV/code (PDF/DOCX if packages exist). |
| `friday/db/` | Numbered SQL migrations plus `pool.py`, the single-writer session (per-path lock, WAL, migrate once). |
| `friday/runtime/` | One voice worker thread. Exposed Eel functions queue work here instead of blocking the bridge. |
| `tests/conftest.py` | Shared pytest fixtures: throwaway SQLite, fake desktop/browser/screen/phone/LLM, one-session helper. |
| `pytest.ini` | pytest config: `testpaths`, markers (`router`, `tools`, `permissions`, `integration`). |
| `requirements.txt` | Declared runtime dependencies, pinned: 10 core plus 5 feature agents. |
| `requirements-lock.txt` | `pip freeze` of the verified environment, transitives included. |
| `requirements-optional.txt` | Local wake word (`openwakeword`, `onnxruntime`); inert without `models/friday.onnx`. |
| `requirements-dev.txt` | Test-only dependency (`pytest`). |
| `README.md` | Install, launch, the command table, every env var, and troubleshooting. |
| `friday.bat` | Double-clickable launcher; picks `.venv` if present, holds the window open on failure. |
| `edge-signin.bat` | Opens the saved Edge profile so a login can be captured once (`python -m friday.browser login`). |
| `.edge-profile/` | Persistent Edge profile. Gitignored, and blocked from the file/code/ingest tools because it holds live session cookies. |
| `models/README.md` | Placeholder for a custom `friday.onnx` wake-word model (not present, not wired). |
| `contacts (1).csv` | Google Contacts export used by `engine/db.py`. |

There is **no** FastAPI/Flask API layer. Phase 2 added `friday.orchestrator`. Phase 3 added `friday.tools`. Phase 4 added `friday.os_adapters`. Phase 5 added `friday.providers` (Google STT + SAPI TTS behind interfaces; openWakeWord waits for `models/friday.onnx`). Phase 6 added `friday.browser` (Playwright worker; Bing search / open URL / read page). Phase 7 added `friday.providers.vision` (Windows OCR describe/read/verify). Phase 8 added `friday.memory` / `friday.rag` / `friday.db`. Phase 9 added `friday.files`, `friday.code`, and `friday.productivity` (SQLite notes/reminders). Phase 10 added `friday.integrations` (Gmail / Slack / Discord). Phase 12 added `friday.observability` (JSON task traces). Phase 13 added `pytest.ini`, `tests/conftest.py`, and `requirements-dev.txt`. Phase 14 added `friday.runtime` (voice worker thread) and `friday.db.pool` (single-writer sessions). Phase 15 added `requirements.txt`, `requirements-lock.txt`, `requirements-optional.txt`, `README.md`, and `friday.bat`. `.env` is loaded if present.

OpenCV was installed in the venv (`opencv-python`, `opencv-contrib-python`). Face-auth files under `engine/auth/` were started in the editor but are **not part of the running app**.

### 1.2 Runtime data flow today

```
Microphone (hotword process)
  → Google Speech Recognition
  → match "friday"
  → multiprocessing.Event
  → Eel TriggerVoiceControl()
  → orb switches to "listening" (the view never changes; the orb has states)
  → eel.allCommands()  (queues, returns at once; bridge stays free for STOP)
  → FridayVoice worker thread
  → takecommand() (second Google STT pass)
  → _run_command()
  → friday.orchestrator.handle_user_request()
       ├ classify (keyword fast path; LLM hook unused)
       └ ToolRegistry.invoke(...)
            ├ media.youtube_play      → PlayYoutube
            ├ apps.open               → openCommand → os adapter
            ├ os.windows.list/focus
            ├ os.processes.list
            ├ os.screenshot
            ├ os.clipboard.get/set
            ├ contacts.lookup         → findContact
            ├ comms.whatsapp_message  → whatsapp(flag=message)
            ├ comms.whatsapp_call     → whatsapp(flag=call|video)
            ├ llm.chat                → chatbot → speak()
            ├ browser.search/open/read → Playwright (OS browser fallback)
            ├ vision.describe_screen / ocr / verify → screenshot + Windows OCR
            ├ memory.remember / list / forget
            ├ memory.ingest / rag.search → SQLite chunks
            ├ files.search / read / write / move
            ├ code.read / patch / test (workspace unittest only)
            ├ notes.add / list · reminders.add / list
            ├ integrations.status / connect / disconnect
            ├ email.send / email.list · slack.send · discord.send
            └ session.stop            → end loop
  → pyttsx3 SAPI5 + UI chat bubbles
```

### 1.3 What currently works (keep)

- Dual-process launch (`run.py`) and clean shutdown.
- Local Edge UI with text input, mic, chat drawer.
- Spoken replies printed to the terminal and shown in the UI.
- SQLite contact lookup with Indian-number normalization.
- WhatsApp Desktop deep links for message / voice / video (fragile, but used).
- YouTube playback via `pywhatkit`.
- App/site open via `sys_command` / `web_command` and the Windows OS adapter.
- HuggingChat Omni client that accepts Cookie-Editor JSON (optional; chat defaults to Ollama).
- Hotword process isolation so the UI can keep running.
- Explicit web search (`search the web for …`, `google …`) via Playwright, not HuggingChat.
- Screen describe / OCR / “is X on the screen” via Windows OCR.
- Remember / list / forget facts in SQLite; ingest local notes; search them by voice.
- Find / read / write / move files in allowed folders; run workspace tests.
- Add and list notes and reminders (stored in SQLite; no calendar push yet).
- Connect Gmail / Slack / Discord (OAuth loopback, or Slack bot token / Discord webhook in `.env`). Email, Slack, Discord, and WhatsApp sends ask for a spoken yes or the Send button.
- Settings gear lists memories, documents, notes, reminders, integrations, allowed folders, and recent activity (status + disconnect only; no tokens).

### 1.4 Broken, incomplete, or high-risk

| Issue | Why it matters |
| --- | --- |
| Keyword router is the “brain” | Fast path owns known tools. Unmatched utterances still go to chat. `open` is command-shaped (`open chrome`), not a substring, so `don't open chrome` stays chat. |
| Google STT for hotword **and** commands | Requires network. Two processes compete for the microphone. Command listen retries on unknown/timeout, keeps the full phrase window, and asks you to repeat if it still misses. |
| `openWakeWord` is installed but unused | `models/friday.onnx` is missing; hotword still uses Google until that file exists. |
| HuggingChat auth is a browser session cookie | Tokens expire/revoke; not an API key; easy to leak if logged. Chat defaults to Ollama. |
| WhatsApp calls use `pyautogui` tab counts | Breaks when WhatsApp UI changes. Sends wait for confirm. |
| USB phone/SMS automation was added then **removed** | Phone never enumerated over ADB. Do not reintroduce until a real device is visible. |
| Circular import `command` ↔ `features` | Lazy imports paper over a real design smell. |
| Eel worker thread + blocking STT/TTS | Fixed in Phase 14. `allCommands()` now queues a job on the `FridayVoice` worker thread and returns, so STOP and UI callbacks are delivered while the mic is open. One worker, so speaking still finishes before listening resumes and two sessions cannot open two microphones. |
| Settings confirm UI | Gear lists memories, documents, notes, reminders, integrations, allowed folders, and recent activity. Terminal button opens the Developer log (task traces). Email / Slack / Discord / WhatsApp use spoken yes or the Send button. |
| Secrets hygiene | `cookies.json` and `friday.secrets.json` gitignored. SQLite `integrations` rows store provider + `secret_ref` only, never tokens. DPAPI wrap on Windows. |
| Broader test matrix | `python -m pytest` runs 588 tests; `python -m unittest discover -s tests` runs 354. Router, tool-spec, and permission tables are parametrized, plus one multi-step session test. |
| Emailing a person by name failed | Fixed. Dictated addresses ("… to rahul@gmail.com", or spoken "john at gmail dot com") always worked, but "send email to Kabir" replied "I need a full email address" — the `contacts.email` column existed yet was never filled or read. The CSV importer (`engine/db.py`) now pulls Google's `E-mail N - Value` columns and backfills the email of contacts already imported; `friday/integrations/contacts.py` resolves a spoken name to that stored address; and the send path validates the recipient *before* asking for the body, so a known-but-emailless contact gets a named prompt and an unknown name is told to say the address. Re-runnable via `import-contacts.bat`. Note: the CSV currently in the repo has no email column, so the user must re-export from Google Contacts to populate it. |
| Opening an app never played it | Fixed. `open spotify` launches Spotify but does not press play, which surprised users. Added a `media.control` tool plus a narrow `IntentName.MEDIA` router: "play music", "pause", "next", "previous", "stop music" send the Windows media transport keys (`keybd_event` on `VK_MEDIA_*`), which drive whatever owns the current media session — Spotify or a browser. "play music" launches Spotify first when nothing is running so the toggle has a session to resume (`FRIDAY_SPOTIFY_WARMUP_SEC`, default 3.5s). The classifier is deliberately narrow so it never steals "play … on youtube", bare "stop" (still stops voice control), or an ordinary chat line. No login and works with free Spotify; it resumes the last context and cannot pick a named track (that needs the Web API path the user declined). Tool count 42 → 43. |
| App catalog was almost empty | Fixed. `open <app>` reads a `sys_command`/`web_command` catalog that shipped with ~5 hand-added rows, so "open spotify" or "open whatsapp" failed even though both were installed. `friday/os_adapters/app_scan.py` now populates the catalog from `Get-StartApps` (the same list Windows' "All apps" shows), which is the *only* place Store apps like Spotify and WhatsApp appear — they have no Start Menu `.lnk`. Every entry, Win32 or UWP, is stored as `shell:AppsFolder\<AppID>` and launches through the existing `os.startfile`. The sync is additive (hand-curated rows survive) and re-runnable via `scan-apps.bat` after installing new apps. `lookup_open_target` gained a whole-word fuzzy fallback so "chrome" resolves "Google Chrome" and "code" resolves "Visual Studio Code". |
| One-word replies were silently dropped | Fixed. Google Web Speech returns *no result at all* for a bare interjection — "yes", "sure", "yeah", "yep", "ok", "no", "nope" — even from a clean 1.1s clip, while content words of the same length ("stop", "cancel", "hello", "time") transcribe fine, so it is not a capture or duration problem. Every spoken confirmation therefore died before reaching the router, which had always matched these words correctly. A short clip that comes back unknown is now re-sent once as the same clip twice with a 0.4s gap; that returns "yes yes", which is collapsed back to "yes". Costs one extra request only on a failed short clip. |
| Undeclared dependencies | Fixed in Phase 15. The venv had 90 packages and the repo had no `requirements.txt`, so nobody could tell what the app needed from what someone once tried. `requirements.txt` now declares only what is imported, and a test re-derives that list from the source on every run. |
| SQLite connection churn | Fixed in Phase 14. `connect()` used to re-scan migrations and leak a connection on every call (`with sqlite3.connect(...)` commits but never closes). It now takes a per-path lock, applies migrations once, and closes on exit. Suite runtime fell from 48s to 31s. |

### 1.5 Security snapshot (current)

- **Authentication:** none at app start. Face auth is not implemented in the running path.
- **Authorization:** none. Every exposed Eel function is callable from the local webview.
- **Secrets:** Hugging Face cookies on disk; OAuth/bot tokens in DPAPI-wrapped `friday.secrets.json` (gitignored), referenced from SQLite by `secret_ref` only. Google STT uses the public web API. The saved Edge profile (`.edge-profile/`) holds live session cookies in extension-less Chromium files, which `extract_text()` would otherwise read as text; since the project sits under Desktop (an allowed folder), `is_blocked()` rejects any path with `.edge-profile` in it.
- **Audit:** SQLite `audit_logs` (tool name, hash, ok/error; no tokens or message bodies). Shown in Settings.
- **Task traces:** SQLite `event_logs` plus JSON on logger `friday.events` (`task_id`, intent, tool names, truncated request). Developer log panel only; no voice command. Arguments, tokens, and message bodies are dropped. The request itself is scrubbed (`scrub_request`) so `send message to papa <body>` traces as `send message to papa <redacted>`; long digit runs are masked.
- **Conversation memory (deliberate, not a leak):** `task_runs.request` and the conversation rows do store the utterance as spoken, because episodic memory and chat history are the point of Phase 8. The redaction guarantees above are scoped to `audit_logs` and `event_logs`, which are debug surfaces, not memory.
- **Destructive actions:** `os.startfile` can launch anything in `sys_command`. WhatsApp, email, Slack, and Discord sends require a spoken yes or the Send button.
- **Eel surface:** localhost-only, which is acceptable for a personal desktop app if the permission layer lives in Python, not in JS.

Do not treat Eel as an internet-facing API. Keep the server bound to `127.0.0.1`.

---

## 2. Friday 2.0 goal

Friday 2.0 is the same **personal Windows assistant**, with a real brain:

User → Voice/Text UI → Input processing → **Orchestrator** → Intent / Planner → Agent router → Agent → Tool registry → Execute → Observe → Verify → Memory → Response → Voice/Text

The orchestrator **does not** implement YouTube, files, or WhatsApp itself. It selects agents and tools.

The first versions stay **in-process Python modules**. Splitting into microservices would add operational cost without helping a single-user desktop app.

---

## 3. Target architecture

### 3.1 Logical layers

```
┌─────────────────────────────────────────────────────────────┐
│  Presentation                                                │
│  www/ (Eel)  → later optional FastAPI + local web UI         │
└──────────────────────────┬──────────────────────────────────┘
                           │ IPC / eel.expose / later REST
┌──────────────────────────▼──────────────────────────────────┐
│  API / Session                                               │
│  Auth gate · permission prompts · emergency STOP             │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Orchestrator                                                │
│  classify → plan → route → track state → verify → respond    │
└─────────────┬───────────────────────────────┬───────────────┘
              │                               │
     ┌────────▼────────┐             ┌────────▼────────┐
     │ Agent layer     │             │ Memory / RAG    │
     │ Research        │             │ short-term      │
     │ Browser         │             │ long-term       │
     │ Computer        │             │ episodic        │
     │ File            │             │ semantic        │
     │ Coding          │             └────────┬────────┘
     │ Communication   │                      │
     │ Productivity    │             ┌────────▼────────┐
     │ Vision          │             │ Providers       │
     │ System          │             │ LLM STT TTS     │
     └────────┬────────┘             │ Embed Vision    │
              │                      └─────────────────┘
     ┌────────▼────────┐
     │ Tool registry   │
     │ schema · risk · │
     │ validate · run  │
     │ observe · log   │
     └────────┬────────┘
              │
     ┌────────▼────────┐
     │ OS adapters     │
     │ Windows/* nix   │
     └─────────────────┘
```

### 3.2 Proposed package layout (strangler fig)

Keep `run.py`, `main.py`, and `www/` as the shell. Move new code under `friday/` **without deleting** `engine/` until each feature is wrapped. Phase 6 added `friday/browser/`. Phase 8 added `friday/memory/`, `friday/rag/`, and `friday/db/`. Phase 9 added `friday/files/`, `friday/code/`, and `friday/productivity/`. Phase 10 added `friday/integrations/`. Phase 12 added `friday/observability/`.

```
friday/
  orchestrator/     # classify, plan, execute loop
  agents/           # one module per agent
  tools/            # registry + tool implementations
  providers/        # LLM, STT, TTS, embeddings, vision
  memory/           # SQLite facts, conversation rows, episodic task_runs
  rag/              # ingest, chunk, local embed, retrieve
  files/            # allowlisted search / read / write / move
  code/             # workspace read / patch / unittest only
  productivity/     # spoken reminder due-time parsing
  integrations/     # Gmail / Slack / Discord OAuth + confirmed send
  db/               # numbered SQL migrations
  security/         # permissions, confirm, secrets, audit
  os_adapters/      # Windows keyboard/mouse/windows/files/process
  observability/    # structured logs, task traces
engine/             # legacy adapters until fully wrapped
www/                # UI; evolve in place
```

Legacy functions become **tools**:

| Legacy function | Friday 2.0 home |
| --- | --- |
| `openCommand` | System agent → `apps.open` tool |
| `PlayYoutube` | System/browser agent → `media.youtube_play` |
| `whatsapp` | Communication agent → `comms.whatsapp_*` |
| `findContact` | Shared contact store tool |
| `chatbot` / HuggingChat | LLM provider + conversation agent |
| `hotword` | Voice pipeline (replace Google with openWakeWord when `friday.onnx` exists) |
| `speak` / `takecommand` | TTS / STT providers |

### 3.3 Technology choices (deliberate, not résumé-driven)

| Concern | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11+ | Matches the existing app. |
| UI host | Keep Eel + Edge for Phases 2–6 | Working shell. Replacing UI early is a rewrite. |
| Optional API | FastAPI on 127.0.0.1 later | Needed for a richer dashboard, not for v1 of the orchestrator. |
| Database | SQLite + SQL migrations | Already used; enough for one user. |
| Vectors | sqlite-vec **or** Chroma on disk | Local RAG without a vector server. |
| Browser | Playwright | Deterministic browser control vs pyautogui. |
| Desktop automation | `pywinauto` / Win32 first, pyautogui fallback | Structured UI when possible. |
| LLM | Provider interface: Ollama default, HuggingChat/OpenAI-compatible optional | Local-first; cookies are a fallback adapter, not the core. |
| STT | Provider interface: faster-whisper local, Google as fallback | Cuts hotword/command cloud dependency. |
| TTS | Provider interface: pyttsx3 now, Piper/Kokoro optional | Keep SAPI working on day one. |
| Wake word | openWakeWord + `models/friday.onnx` | Docs already describe this. |
| Vision | Screenshot + local/vision provider | OpenCV already in venv; use for capture/OCR helpers, not as the “AI brain”. |
| Config | pydantic-settings + `.env` | No hardcoded keys. |
| Tests | pytest | Start with orchestrator, tools, permissions. |

Avoid: Kubernetes, Kafka, custom RL, a separate agent per HTTP microservice.

---

## 4. Orchestrator

### 4.1 Responsibilities

1. Normalize input (text already transcribed, or text from the chat box).
2. Classify: **chat** vs **action** vs **mixed**.
3. If action: produce a task graph (steps, deps, timeouts).
4. For each step: pick agent + tool; check permission; optionally confirm.
5. Execute; capture observation.
6. Verify success criteria (file exists, window title, HTTP status, screenshot check).
7. Retry or replan on failure.
8. Write episodic memory.
9. Generate a user-facing summary.
10. Return text for TTS / UI.

### 4.2 Task state

Persist enough to resume after a crash:

- `task_id`, user request, status (`planned|running|waiting_confirm|succeeded|failed`)
- step list with agent, tool, input hash, observation, retry count
- confirmation token for high-risk steps

### 4.3 Confirmation policy

| Risk | Default |
| --- | --- |
| Low (read, search, screenshot, open known app) | Auto |
| Medium (write file in user folders, HTTP GET/POST to allowlisted hosts) | Auto with UI “activity” line; optional confirm in settings |
| High (delete, send message, install, shell, anything outside allowlisted dirs) | Spoken yes / send it, or the Send button. `FRIDAY_REQUIRE_CONFIRM_SEND=false` restores auto WhatsApp. |

Emergency STOP: UI button and hotkey cancel in-flight tool execution where possible (`KeyboardInterrupt` / process kill for subprocess tools).

---

## 5. Agents and tools

Agents are thin: they choose tools and interpret observations. Tools do I/O.

| Agent | First tools to ship | Notes |
| --- | --- | --- |
| System | `apps.open`, `apps.list`, `os.info`, `process.list` | Wrap `openCommand` + sqlite catalogs. |
| Communication | `contacts.lookup`, `comms.whatsapp_message`, `comms.whatsapp_call`, `email.send`, `email.list`, `slack.send`, `discord.send`, `integrations.*` | WhatsApp, email, Slack, and Discord require spoken yes or the Send button. Tokens never in SQLite. |
| Browser | `browser.open`, `browser.search`, `browser.read` | Playwright (Bing search; Edge/Chrome channel). YouTube stays pywhatkit. |
| File | `files.search`, `files.read`, `files.write`, `files.move` | User home / Documents / Downloads allowlists. |
| Computer | `input.hotkey`, `window.focus`, `screen.screenshot` | Win32 before pixel clicking. |
| Vision | `vision.describe_screen`, `vision.ocr`, `vision.verify` | Screenshot + Windows OCR. `verify_on_screen()` is the computer-agent hook. |
| Research | `web.search`, `web.fetch`, `docs.summarize` | After RAG or simple fetch+LLM. |
| Coding | `code.read`, `code.patch`, `code.test` | Workspace-scoped; no arbitrary shell. |
| Productivity | `notes.add`, `reminders.add` | SQLite first; calendar later via Graph/Google with OAuth. |

Each tool record:

- `name`, `description`, JSON Schema in/out
- `permission_level`, `risk_level`
- `validate()`, `execute()`, optional `rollback()`
- structured log on every call (no secret values)

The LLM sees **schemas**, not Python source.

---

## 6. Voice pipeline

Target:

```
Mic → VAD → STT provider → Orchestrator → TTS provider → Speaker
```

Hotword stays in its own process (keep `run.py`).

**Phase 5 order:**

1. Keep Google STT + SAPI TTS behind provider interfaces (behavior unchanged).
2. Add faster-whisper local STT.
3. Replace hotword Google loop with openWakeWord when `models/friday.onnx` is trained.
4. Optional Piper/Kokoro TTS.

Do not block orchestration work on new voice models.

---

## 7. Memory and RAG

| Store | Engine | Content |
| --- | --- | --- |
| Short-term | In-memory + conversation rows | Current chat, active task |
| Long-term | SQLite `memories` | User facts, preferences |
| Episodic | SQLite `task_runs` | What was tried and whether it worked |
| Semantic | Vector index + `documents` | Chunks from PDFs, notes, code |

User must be able to list / edit / delete memories from Settings.

RAG pipeline: ingest → chunk → embed → store → retrieve → optional rerank → grounded answer with paths.

Formats: PDF, DOCX, TXT, MD, CSV, code. Independent package `friday/rag`.

---

## 8. Database (target schema)

Evolve `friday.db` with numbered SQL migrations. Do not dump secrets into rows.

Core tables (additive; keep `contacts`, `sys_command`, `web_command`):

- `users` (single local profile is enough)
- `conversations`, `messages`
- `tasks`, `task_steps`
- `tool_executions` (redacted inputs)
- `memories`
- `documents`, `document_chunks` (or external vector files keyed by chunk id)
- `integrations` (provider name + encrypted secret ref, not raw keys)
- `permissions`, `audit_logs`
- `event_logs` (task traces: event, task_id, intent, tools; no arguments)

Secrets live in OS credential store or `.env` (never in git, never in frontend).

---

## 9. Frontend evolution

Keep the orb. Add, do not throw away:

- **Activity panel:** “Planning…”, agent name, tool name, step n of m
- **Permission modal:** high-risk confirm
- **STOP**
- **Settings:** STT/TTS/LLM provider, confirm policy, memory inspector
- Settings gear currently does nothing — wire it in the UI phase

Chat drawer already exists (`senderText` / `receiverText`). Reuse it as the conversation panel.

---

## 10. Configuration

Introduce `.env.example` in Phase 2 with variables such as:

- `FRIDAY_LLM_PROVIDER` (`ollama` \| `openai_compatible` \| `huggingface_chat`)
- `FRIDAY_LLM_MODEL`, `OLLAMA_HOST`
- `FRIDAY_STT_PROVIDER` (`google` \| `faster_whisper`)
- `FRIDAY_TTS_PROVIDER` (`sapi` \| `piper`)
- `FRIDAY_WAKE_PROVIDER` (`auto` \| `google` \| `openwakeword`)
- `FRIDAY_BROWSER_PROVIDER` (`auto` \| `playwright` \| `system`)
- `FRIDAY_BROWSER_HEADLESS`, `FRIDAY_BROWSER_TIMEOUT_MS`
- `FRIDAY_VISION_PROVIDER` (`auto` \| `windows` \| `none`)
- `FRIDAY_VISION_LANGUAGE`
- `FRIDAY_DATA_DIR`
- `FRIDAY_ALLOW_PATHS`
- `FRIDAY_REQUIRE_CONFIRM_SEND=true`

Never commit `.env`, cookies, tokens, or trained biometric data.

Expand `.gitignore` for `.env`, `*.pem`, `auth/samples/`, vector indexes.

---

## 11. Testing strategy

Start small; do not wait for Playwright to test the orchestrator.

| Layer | Tests |
| --- | --- |
| Tools | Fake OS adapter; validate schema and risk gates |
| Router | “play X on youtube” → youtube tool, not chatbot |
| Planner | Multi-step graph + dependency order |
| Permissions | High-risk tool blocked without confirm |
| Memory/RAG | Chunk + retrieve fixture docs |
| Voice | Provider fakes (no live mic in CI) |
| Integration | One golden path: open app from sqlite catalog |

Run `pytest` in CI later; locally after each phase.

---

## 12. Risks

| Risk | Mitigation |
| --- | --- |
| Big-bang rewrite kills a working assistant | Strangler fig; wrap `engine/` as tools. |
| LLM tool-calling is unreliable | Keyword router remains a **fast path** for known intents until the planner is trustworthy. |
| Computer control is dangerous | Allowlists, confirm, STOP, audit. |
| HuggingChat cookies die | LLM provider interface; Ollama as default for reasoning. |
| Two mics | Exclusive capture or push-to-talk after hotword. |
| Scope explosion | Ship phases; refuse to implement calendar+Slack+vision in one PR. |

---

## 13. Implementation phases

Do **not** implement this list in one session. After each phase: tests, run `python run.py`, fix, update this doc, then continue.

### Phase 1 — Analysis and architecture (this document)

- [x] Inspect repository
- [x] Record reuse vs replace
- [x] Publish this plan

### Phase 2 — Core backend and orchestration

- [x] `friday/` package
- [x] Intent classifier (rules first; optional LLM hook, not wired so chat behavior is unchanged)
- [x] Task state objects (`task_id`, status, one-step plan)
- [x] Legacy `_run_command` calls orchestrator, which delegates to existing `engine.features` functions
- [x] Fast path: existing keywords still work; `open` is command-shaped (`open chrome`), not a substring
- [x] Router tests (`python -m unittest discover -s tests`)
- [x] `.env.example` and tighter `.gitignore` (`.env` is not loaded yet)

### Phase 3 — Tool registry

- [x] Register open / youtube / whatsapp / chatbot as tools
- [x] JSON schemas, risk levels, logging
- [x] WhatsApp / email / Slack / Discord sends require confirm (`FRIDAY_REQUIRE_CONFIRM_SEND`, default on)
- [x] Tool tests (`python -m unittest discover -s tests`)

### Phase 4 — Laptop control adapter

- [x] Windows adapter: windows, processes, screenshot, clipboard
- [x] `openCommand` uses adapter
- [x] OS tools registered; keyword fast path for screenshot / windows / processes / clipboard / focus, including spoken “list of windows” / “list of processes”
- [x] Adapter tests (`python -m unittest discover -s tests`)

### Phase 5 — Voice providers

- [x] STT/TTS interfaces
- [x] Keep Google + SAPI wired; command STT retries on unknown/timeout, then asks you to repeat
- [x] Document openWakeWord model requirement (`models/README.md`)
- [x] Optional `faster_whisper` STT via `FRIDAY_STT_PROVIDER`
- [x] openWakeWord only when `models/friday.onnx` exists; otherwise Google hotword

### Phase 6 — Browser agent

- [x] Playwright driver (subprocess worker so Eel/gevent cannot block Chromium)
- [x] Tools: `browser.search`, `browser.open`, `browser.read`
- [x] Keyword fast path: search the web / google / go to URL / read this page
- [x] Unmatched questions go to Ollama (`FRIDAY_LLM_PROVIDER=ollama`, model `gemma3:4b`)
- [x] HuggingChat is optional (`FRIDAY_LLM_PROVIDER=huggingface_chat`); 402/auth failures fall back to Ollama
- [x] OS-browser fallback if Playwright is missing
- [x] Browser tests (`python -m unittest discover -s tests`)

### Phase 7 — Vision

- [x] Screenshot → describe/OCR provider (Windows OCR via `winocr`)
- [x] Tools: `vision.describe_screen`, `vision.ocr`, `vision.verify`
- [x] Keyword fast path: what's on my screen / read the screen / is X on the screen
- [x] `verify_on_screen()` hook for the computer agent
- [x] `take a screenshot` saves a PNG and opens it; `show me the screenshot` opens the latest file
- [x] Vision tests (`python -m unittest discover -s tests`)

### Phase 8 — Memory and RAG

- [x] SQLite `memories`, `documents`, `document_chunks`, `messages`, `task_runs` via numbered migrations
- [x] Tools: `memory.remember` / `list` / `forget`, `memory.ingest`, `rag.search`
- [x] Keyword fast path: remember that / what do you remember / forget that / ingest / search my documents
- [x] Chat prepends retrieved notes; if HuggingChat is down, speak the local hits
- [x] Settings gear: inspect/delete memories and ingested documents
- [x] Memory/RAG tests (`python -m unittest discover -s tests`)

### Phase 9 — Remaining specialized agents

- [x] File tools: `files.search` / `read` / `write` / `move` on allowlisted folders
- [x] Coding tools: `code.read` / `code.patch` / `code.test` (workspace unittest only; no arbitrary shell)
- [x] Productivity: `notes.add` / `notes.list`, `reminders.add` / `reminders.list` in SQLite
- [x] Keyword fast path: find file / read file / show me the file / open a file / write to file / run the tests / add a note / remind me to
- [x] Settings gear lists notes and reminders with delete; due reminders are spoken on the next command
- [x] Tests (`python -m unittest discover -s tests`)

### Phase 10 — External integrations

- [x] Email / Slack / Discord only with OAuth (or Slack bot token / Discord webhook in `.env`) and spoken confirm on send
- [x] SQLite `integrations` table + gitignored `friday.secrets.json` sidecar (`secret_ref` only in the DB)
- [x] Tools: `integrations.status` / `connect` / `disconnect`, `email.send` / `email.list`, `slack.send`, `discord.send` (42 tools total)
- [x] Keyword fast path: connect gmail / check my email / send an email to … saying … / Slack / Discord. Does not steal WhatsApp `send message` / `call papa`
- [x] Settings gear lists integration status with Disconnect (no tokens)
- [x] Do not resurrect ADB SMS/call
- [x] Tests (`python -m unittest discover -s tests`)

### Phase 11 — Security

- [x] Confirm UI (Send / Don't send) plus spoken yes / send it, including bare `send` while pending
- [x] WhatsApp message and call wait for confirm (same next-command path as email). Does not steal `send message to papa`
- [x] `FRIDAY_REQUIRE_CONFIRM_SEND` is read; default on
- [x] File allowlists listed in Settings (already enforced on file tools)
- [x] Secret store: DPAPI wrap of `friday.secrets.json` on Windows; SQLite still stores `secret_ref` only
- [x] SQLite `audit_logs` from tool calls (no tokens or message bodies); Settings lists recent rows
- [x] STOP on the listening screen
- [x] Do not resurrect ADB SMS/call; skip face unlock
- [x] Tests (`python -m unittest discover -s tests`)

### Phase 12 — Observability

- [x] Structured JSON logs with `task_id` (`friday.events` plus SQLite `event_logs`)
- [x] Developer log panel in UI (terminal button; no new tools, no voice intent)
- [x] Drop tokens, phone numbers, and message bodies from traces; do not persist tool arguments
- [x] Do not steal existing commands; still 42 tools
- [x] Tests (`python -m unittest discover -s tests`)

### Phase 13 — Testing

- [x] pytest config (`pytest.ini`, markers) and shared fixtures (`tests/conftest.py`)
- [x] Router suite: phrase → intent and phrase → tool tables, plus steal-guards (`tests/test_router_contract.py`)
- [x] Tools suite: every spec validated, manifest is JSON-only, schema and audit behaviour (`tests/test_tools_contract.py`)
- [x] Permissions suite: confirm gate, file allowlist, secret and trace redaction (`tests/test_permissions_contract.py`)
- [x] One multi-step integration test: eleven-turn session across router, tools, confirm, memory, traces (`tests/test_integration_multistep.py`)
- [x] Fixed a real leak the suite found: inline message bodies were reaching `event_logs` via the `request` field
- [x] Do not steal existing commands; still 42 tools
- [x] Tests (`python -m pytest`, and `python -m unittest discover -s tests` still green)

### Phase 14 — Performance

- [x] Non-blocking Eel: `friday.runtime.voice` single worker thread; `allCommands` / `confirm_send` queue and return
- [x] STOP is delivered while the microphone is open (`request_stop()` sets a `threading.Event` the worker polls)
- [x] One session at a time, in order, so two microphones never open at once
- [x] A failing command no longer takes the worker thread down with it
- [x] Single-writer SQLite: `friday.db.pool` per-path lock, WAL + `busy_timeout`, migrations applied once per path
- [x] Connections are closed after each block; the old `with sqlite3.connect(...)` leak is gone
- [x] Do not steal existing commands; still 42 tools, no new voice intent
- [x] Tests (`tests/test_phase14.py`, 23 cases; both runners green)

### Phase 15 — Packaging **(complete)**

- [x] `requirements.txt`: the 17 third-party modules the source actually imports, resolved to 15 pinned distributions (`PIL` → `pillow`, `docx` → `python-docx`, `win32crypt` → `pywin32`, `speech_recognition` → `SpeechRecognition`)
- [x] Split into core (10, app will not start without them) and feature agents (5, one agent degrades)
- [x] `requirements-lock.txt`: `pip freeze` of the verified environment, so a fresh machine can reproduce it exactly
- [x] `requirements-optional.txt`: `openwakeword` / `onnxruntime` kept out of the runtime set, since they are inert without `models/friday.onnx`
- [x] The venv held 90 packages; most were pywhatkit transitives (Flask, Mastodon.py, wikipedia) or stray installs (`boost`, `huggingface`, OpenCV). Only what is imported is declared.
- [x] `README.md`: install, `python run.py`, the command table, all 20 env vars with defaults, troubleshooting
- [x] `friday.bat` for a double-click or taskbar launch; `.venv` auto-detected, window held open on failure
- [x] All three requirements files verified resolvable with `pip install --dry-run`
- [x] Do not steal existing commands; still 42 tools, no new voice intent
- [x] Tests (`tests/test_phase15.py`, 15 cases; both runners green)

The dependency test is not a hand-written list. It walks `friday/`, `engine/`,
`main.py`, and `run.py` with `ast`, collects every import including the lazy
ones inside functions, drops stdlib and first-party names, maps what is left to
distributions via `packages_distributions()`, and fails if any of them is
absent from all three requirements files. Adding an import without declaring it
now breaks the suite instead of breaking a fresh install. `faster_whisper` is
the one documented exception: imported behind a `try`, deliberately not
installed.

---

## 14. Definition of done (product)

Friday 2.0 is done when these work **through the orchestrator** (plan → tool → verify → speak), not only via hidden if/else:

- Open Chrome and search
- Find a file downloaded yesterday
- Summarize a PDF
- Open VS Code on this repo
- Explain a Python error in-project
- Organize Downloads (with confirm)
- Web research report saved to Documents
- Play requested music
- Send WhatsApp after confirm
- Calendar (when an integration is configured)
- Multi-step app workflow
- Describe what is on screen

Until then, Friday 1.0 behavior must keep working.

---

## 15. Next action

All fifteen phases are implemented. There is no Phase 16; the remaining work is the definition-of-done list in section 14, not new plumbing.

The honest gaps, in the order worth closing:

1. **Wake word.** `models/friday.onnx` does not exist, so the hotword still round-trips to Google. Train or source the model, then `pip install -r requirements-optional.txt` and the provider switches itself.
2. **Chat depends on Ollama.** With Ollama stopped, chat answers that it is offline. Tools and memory keep working, but the assistant feels dead to anyone who only chats. A *running* Ollama no longer reports offline just because it is busy: `/api/tags` is now advisory (a failed listing falls back to the configured model), its budget went 5s → 20s, and `keep_alive=30m` stops the ~16s cold load from recurring every five idle minutes.
3. **A real end-to-end pass on a clean machine.** Every phase is green here, but `requirements.txt` has only been dry-run resolved, never installed into an empty venv. That is the one claim in this document still untested against reality.

Do not resurrect ADB SMS/call until a device is actually attached.
