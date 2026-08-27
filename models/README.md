# Friday wake-word model

Friday's hotword is **`Friday`**.

## What runs today

The hotword process (`run.py` → `engine.features.hotword`) uses a **voice provider**:

| `FRIDAY_WAKE_PROVIDER` | Behavior |
| --- | --- |
| `auto` (default) | openWakeWord if the model file exists, otherwise Google STT |
| `google` | Google Speech Recognition (needs network), same as Friday 1.0 |
| `openwakeword` | Local openWakeWord; **falls back to Google** if the model is missing |

Command listening (`takecommand`) uses `FRIDAY_STT_PROVIDER` (`google` default, or `faster_whisper` if installed). Default `FRIDAY_STT_LANGUAGE=hi-IN,en-IN` so Hindi and English are both recognized. Spoken replies use `FRIDAY_TTS_PROVIDER=sapi` (Windows SAPI via pyttsx3), with a Hindi voice when one is installed.

## Required file for local wake word

Place a trained openWakeWord ONNX model here with this exact name:

`models/friday.onnx`

`friday` is **not** a stock openWakeWord model. A custom model must be trained and exported first. Until this file exists, Friday keeps using Google for “Friday”.

## How to train `friday.onnx`

High-level (see the [openWakeWord training docs](https://github.com/dscripka/openWakeWord)):

1. Collect or synthesize clips of the word **Friday** (and hard negatives).
2. Train with the openWakeWord training script / notebook.
3. Export ONNX and copy the file to `models/friday.onnx`.
4. Restart `python run.py`. Logs should say `openWakeWord model friday.onnx`.

Optional env:

```
FRIDAY_WAKE_PROVIDER=auto
FRIDAY_WAKE_THRESHOLD=0.5
FRIDAY_STT_PROVIDER=google
FRIDAY_TTS_PROVIDER=sapi
```

Do not commit trained models or biometric samples. `*.onnx` is gitignored.
