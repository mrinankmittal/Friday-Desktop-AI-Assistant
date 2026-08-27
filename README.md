# Friday 2.0

A Windows desktop voice assistant. It runs as a local Python process that hosts
its own UI in Microsoft Edge, listens for the wake word "Friday", and routes
what you say through an orchestrator to one of 61 tools — opening apps,
searching the web, reading the screen, remembering facts, managing files and
notes, researching topics, and sending messages after you confirm.

Everything runs on your machine. The only network calls are speech recognition,
the chat model, and any integration you explicitly connect.

## Requirements

- **Windows 10 or 11.** Several agents use Windows-only APIs (SAPI speech,
  Windows OCR, DPAPI secret storage, Win32 window and clipboard access).
- **Python 3.11.**
- **Microsoft Edge**, which hosts the UI.
- **A microphone**, for anything voice.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

`PyAudio` ships prebuilt wheels for Python 3.11 on Windows. If it fails to
build, install a wheel matching your Python version rather than compiling it.

To reproduce the exact environment this build was verified against, including
every transitive package, use the lockfile instead:

```bash
python -m pip install -r requirements-lock.txt
```

| File | What it holds |
| --- | --- |
| `requirements.txt` | Declared runtime dependencies, pinned. Start here. |
| `requirements-lock.txt` | `pip freeze` of the verified environment. |
| `requirements-optional.txt` | Local wake word (needs `models/friday.onnx`). |
| `requirements-dev.txt` | Test runner only. Not needed to use Friday. |

## Run

```bash
python run.py
```

That starts two processes: the Eel application, which opens the UI in Edge, and
a hotword listener. Say **"Friday"** to activate, or click the microphone. Type
into the chat box if you would rather not talk. You can speak Hindi, English,
or a mix of both; Friday answers in the same language.

To close it, close the UI window or press `Ctrl+C` in the terminal.

### A Windows shortcut

`friday.bat` launches the app with the virtual environment already activated,
so you can double-click it or pin it to the taskbar. To make a Start Menu
shortcut, right-click `friday.bat`, choose **Send to → Desktop (create
shortcut)**, then drag that shortcut into your Start Menu folder.

## Talking to it

Phrasing matters — the router matches command shapes, and anything it does not
recognise becomes a chat message.

| Say | What happens |
| --- | --- |
| `open chrome`, `open spotify`, `open whatsapp`, `open calendar` | Launches the app (`open calendar` opens One Calendar; say `open outlook calendar` for Outlook) |
| `play music`, `pause`, `next`, `previous`, `stop music` | Media controls (opens Spotify first if nothing is playing) |
| `play <song> on youtube` | Plays the first result |
| `list of windows`, `list of processes` | Reads them back |
| `take a screenshot`, `show me the screenshot` | Captures, then opens it |
| `search the web for <thing>`, `go to <site>`, `click <button>`, `fill <field> with <text>` | Browser agent |
| `research <topic>`, `write a report on <topic>`, `search my documents for <topic>` | Research brief (web or ingested docs) |
| `describe the screen`, `read the screen`, `find <text> on screen` | Vision / OCR |
| `system info`, `what's my IP`, `am I online` | Safe laptop / network facts |
| `copy the file <name> to <folder>`, `create a folder named <name> on the desktop` | File agent |
| `explain <file>`, `what does this code do in <file>` | Coding agent |
| `add a task <text>`, `list my tasks`, `mark task <text> done` | Local tasks |
| `remember that <fact>`, `do you know my name` | Long-term memory |
| `make a cpp file named calculator`, `show me the file`, `compile and run` | Writes that file on the Desktop, opens it, speaks the code; compile/run uses MinGW g++ |
| `what's the weather`, `weather in mumbai` | Live India forecast in Celsius (defaults to New Delhi) |
| `what's the news`, `sports news`, `news about cricket` | Live headlines (India, world, tech, sports, and searches) |
| `copy that`, `paste`, `type hello`, `write how are you doing`, `press ctrl s` | Types or presses keys in the focused app |
| `open word and write hello`, `write hello in chrome`, `in whatsapp write hi` | Opens that app if needed, then types into it |
| `add a note <text>`, `remind me to <task>` | Notes and reminders |
| `send message to <contact>`, `call <contact>` | WhatsApp, after you confirm |
| `send email to <contact or address> saying <text>` | Gmail, after you confirm (import contacts first for names) |
| `exit`, or the STOP button | Stops voice control |
| `क्रोम खोलो`, `chrome kholo`, `मौसम बताओ`, `गाना चलाओ` | Same commands in Hindi or Hinglish |

Sends always wait for a spoken "yes" / **हाँ** or the Send button. That is on
by default and is the one setting worth leaving alone.

Friday listens and answers in English. Say **Friday** to wake it, then give the
command. Speaking uses the Windows English voice (Zira). To turn Hindi back on,
set `FRIDAY_STT_LANGUAGE=hi-IN,en-IN`, `FRIDAY_WAKE_LANGUAGE=en-IN,hi-IN`, and
`FRIDAY_TTS_PROVIDER=auto` in `.env`.

## Teaching it your apps

`open <app>` looks the app up in a small catalog. To fill that catalog with
everything installed on this laptop, run `scan-apps.bat` once (or `python -m
friday.os_adapters.app_scan`). It reads the same list Windows' **All apps** shows
— including Microsoft Store apps like Spotify and WhatsApp, which have no Start
Menu shortcut and are otherwise invisible — and after it finishes, `open spotify`,
`open whatsapp`, and `open <anything installed>` all work.

- Safe to re-run: existing entries are kept, only newly installed apps are added.
  Run it again whenever you install something new.
- You can say the short name. "chrome" finds "Google Chrome"; "code" finds
  "Visual Studio Code".

## Emailing people by name

You can dictate a full address (`send email to rahul@gmail.com saying hi`, or
even spoken as `rahul at gmail dot com`). To email a contact by name
(`send email to Kabir saying hi`), Friday needs that contact's email on file.

Export your contacts from Google Contacts as a CSV, save it as `contacts (1).csv`
in the project folder (keep the **E-mail 1 - Value** column), and run
`import-contacts.bat` (or `python -m engine.db`). It imports names, phone
numbers, and emails, and it is safe to re-run — existing contacts are kept and
only get their email filled in.

- If a contact has no email yet, Friday says so by name instead of sending.
- Gmail sending still needs `FRIDAY_GMAIL_APP_PASSWORD`; see Configuration.

## Playing music

Opening Spotify does not press play, so there are separate media commands:
`play music`, `pause`, `next`, `previous`, and `stop music`. They send the
keyboard's media keys, which control whatever app owns the current media
session — Spotify, or a browser playing YouTube.

- `play music` launches Spotify first if nothing is playing yet, waits a moment
  for it to start, then presses play (so it resumes your last playlist). If a
  player is already open it just toggles play.
- No login, and it works with free Spotify. It resumes what was last playing; it
  can't pick a specific song by name.
- `play` and `pause` are the same hardware toggle, so if playback ends up
  inverted, just say the other one.
- Spotify slow to wake on your machine? Set `FRIDAY_SPOTIFY_WARMUP_SEC` (default
  `3.5`) higher.

## Signing in to sites

Friday drives Microsoft Edge for anything web related. It keeps its own browser
profile in `.edge-profile`, separate from your personal Edge, so a login you do
once is still there for later commands.

To sign in to a site, run `edge-signin.bat` (or `python -m friday.browser login
https://github.com`). Edge opens on Friday's profile, you sign in normally, and
closing the window saves the session. After that, `go to github.com` reaches
your signed-in account.

A few things worth knowing:

- Only cookies with an expiry survive. Sites that issue session-only cookies
  will ask you to sign in again after a restart; that is Chromium's rule, not
  Friday's.
- Edge locks a profile while it is open. If two browser commands overlap, the
  second quietly browses signed out rather than failing.
- `.edge-profile` holds live session cookies. It is gitignored, and the file,
  code, and ingest tools are blocked from reading anything inside it.
- To wipe every saved login, delete the `.edge-profile` folder. To turn the
  whole thing off, set `FRIDAY_BROWSER_PERSIST=false`.

## Configuration

Settings are read from a `.env` file in the project root, or from real
environment variables. Every key is optional; the defaults below are what runs
if you set nothing.

| Key | Default | Purpose |
| --- | --- | --- |
| `FRIDAY_REQUIRE_CONFIRM_SEND` | `true` | Require confirmation before email / Slack / Discord sends |
| `FRIDAY_WHATSAPP_CONFIRM` | `false` | WhatsApp "say send it" step; `false` sends right after the message |
| `FRIDAY_WHATSAPP_LAUNCH_DELAY` | auto | Seconds to wait after opening WhatsApp (empty ≈ 0.7–1.4) |
| `FRIDAY_STT_PROVIDER` | `google` | Speech to text |
| `FRIDAY_STT_LANGUAGE` | `en-IN` | Recognition language (add `hi-IN` for Hindi) |
| `FRIDAY_STT_PAUSE_THRESHOLD` | `1.15` | Seconds of silence before the mic stops (raise if commands get cut off) |
| `FRIDAY_STT_PHRASE_LIMIT` | `20` | Max seconds for one spoken command |
| `FRIDAY_STT_LISTEN_TIMEOUT` | `30` | How long to wait for you to start speaking |
| `FRIDAY_STT_ATTEMPTS` | `4` | Listen passes before giving up (each pass also retries internally) |
| `FRIDAY_TTS_PROVIDER` | `sapi` | English Windows voice; `auto` enables Hindi voices |
| `FRIDAY_TTS_NEURAL_HI` | `hi-IN-SwaraNeural` | Cloud Hindi fallback when TTS is `auto` |
| `FRIDAY_TTS_VOICE_HI` / `FRIDAY_TTS_VOICE_EN` | unset | Optional SAPI voice name (e.g. Hemant, Zira) |
| `FRIDAY_WAKE_PROVIDER` | `auto` | Wake word; uses Google until a model exists |
| `FRIDAY_WAKE_LANGUAGE` | `en-IN` | Hotword language (`Friday`) |
| `FRIDAY_LLM_PROVIDER` | `ollama` | Chat backend |
| `FRIDAY_LLM_MODEL` | `gemma3:4b` | Chat model |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Where Ollama listens |
| `FRIDAY_DATA_DIR` | project root | Where `friday.db` lives |
| `FRIDAY_ALLOW_PATHS` | Documents, Desktop, Downloads, Pictures, home | Folders the file agent may touch |
| `FRIDAY_WORKSPACE` | project root | Folder the coding agent may read and patch |
| `FRIDAY_BROWSER_PROVIDER` | `auto` | `playwright` or the OS browser |
| `FRIDAY_BROWSER_PERSIST` | `true` | Keep logins in a saved browser profile |
| `FRIDAY_BROWSER_PROFILE` | `.edge-profile` | Where that profile is stored |
| `FRIDAY_VISION_PROVIDER` | `auto` | Windows OCR or off |
| `FRIDAY_USER_EMAIL`, `FRIDAY_GMAIL_APP_PASSWORD` | unset | Gmail sending |
| `FRIDAY_SLACK_BOT_TOKEN`, `FRIDAY_DISCORD_WEBHOOK_URL` | unset | Slack and Discord |

Never commit `.env`. It is gitignored, as are `friday.db`, `cookies.json`, and
`friday.secrets.json`. Integration tokens are wrapped with Windows DPAPI and
stored outside SQLite; the database only keeps a reference.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

588 tests. You can run one area at a time by marker:

```bash
python -m pytest -m router        # spoken phrase reaches the right tool
python -m pytest -m tools         # tool specs and schemas
python -m pytest -m permissions   # confirm gate, file allowlist, secrets
python -m pytest -m integration   # full multi-turn sessions
```

The original suite still runs under the standard library runner:

```bash
python -m unittest discover -s tests
```

## Troubleshooting

**It cannot hear me.** Speech recognition needs the network. Check that the
right microphone is the Windows default. Friday waits, retries, and asks you to
repeat before giving up — if it asks twice, the input device is usually wrong.
If commands are cut off halfway, raise `FRIDAY_STT_PAUSE_THRESHOLD` (try `1.3`)
or `FRIDAY_STT_PHRASE_LIMIT` (try `25`) in `.env`.

**The UI does not open.** Edge must be installed. Friday picks a free port
starting at 8000 and binds to `127.0.0.1` only.

**The browser agent does nothing.** It drives Edge by default and only needs
`python -m playwright install chromium` as a last-resort fallback if neither
Edge nor Chrome is present.

## Agent coverage (what works vs deferred)

Agents are tool tags plus voice intents — not separate processes.

| Area | Works now | Deferred (by design) |
| --- | --- | --- |
| Research | Web report (`research …`, `write a report on …`); docs summary from ingested files | External citation databases |
| Browser | Search, open, read, click, fill, download (allowlisted), tabs | Arbitrary uploads to random sites |
| Files | Search, read, write, move, copy, mkdir, run source | Paths outside the allowlist |
| Coding | Read, patch, unittest, explain | Free shell / arbitrary commands |
| Productivity | Notes, reminders, local tasks | Google/Outlook calendar OAuth |
| System / computer | Screenshot, windows, clipboard, automate type/hotkeys/apps, `os.info`, `os.network` | Unrestricted desktop mouse RPA, free terminal |
| Vision | Describe, OCR, verify / find text on screen | ML object detection |

Calendar remains deferred until OAuth is designed in.

**A site keeps asking me to sign in.** Run `edge-signin.bat`, sign in, and close
the window. If it still forgets, that site issues session-only cookies, which
Chromium never writes to disk.

**Chat replies say it is offline.** The default backend is Ollama on
`127.0.0.1:11434`. Start Ollama, or point `FRIDAY_LLM_PROVIDER` elsewhere.
Memory and tool commands keep working while chat is down.

**A command became a chat message.** The router matches specific shapes. Check
the table above for the wording it expects.

**Where did that go wrong?** The terminal button in the UI opens the Developer
log: one line per task with a shared `task_id` across the tool calls it made.

## Layout

| Path | Role |
| --- | --- |
| `run.py` | Starts the UI and hotword processes |
| `main.py` | Eel server; serves `www/` |
| `engine/` | Speech in and out, and the Friday 1.0 features |
| `friday/orchestrator/` | Intent classification and task planning |
| `friday/tools/` | The 61 tools, their schemas and risk levels |
| `friday/runtime/` | Voice worker thread that keeps the UI responsive |
| `friday/memory/`, `friday/rag/`, `friday/db/` | SQLite memory and retrieval |
| `friday/security/` | Confirm gate, file allowlist, secret wrapping |
| `www/` | The UI |
| `docs/FRIDAY_2_ARCHITECTURE.md` | Design and phase-by-phase history |

For how any of this fits together, and what is deliberately not built yet, read
[the architecture document](docs/FRIDAY_2_ARCHITECTURE.md).
