"""Synthesize Hindi with Windows OneCore voices (Kalpana / Hemant).

Classic SAPI cannot play those voices. WinRT can. Eel uses gevent, so this
module runs as ``python -m friday.providers.winrt_speak``.
Text arrives on stdin (UTF-8); argv is ``outfile``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


def pick_hindi_voice(voices: list):
    ranked: list = []
    for voice in voices:
        language = (getattr(voice, "language", "") or "").lower()
        name = (getattr(voice, "display_name", "") or "").lower()
        if not (language.startswith("hi") or "hindi" in name):
            continue
        rank = 2
        if "kalpana" in name:
            rank = 0
        elif "hemant" in name:
            rank = 1
        ranked.append((rank, voice))
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1] if ranked else None


async def _save(text: str, dest: str) -> None:
    from winrt.windows.media.speechsynthesis import SpeechSynthesizer
    from winrt.windows.storage.streams import DataReader

    synth = SpeechSynthesizer()
    voice = pick_hindi_voice(list(SpeechSynthesizer.all_voices))
    if voice is not None:
        synth.voice = voice
    stream = await synth.synthesize_text_to_stream_async(text)
    size = int(stream.size)
    if size < 32:
        raise RuntimeError("WinRT Hindi TTS produced no audio")
    reader = DataReader(stream)
    await reader.load_async(size)
    payload = bytearray(size)
    reader.read_bytes(payload)
    Path(dest).write_bytes(bytes(payload))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: winrt_speak OUTFILE", file=sys.stderr)
        return 2
    dest = args[0]
    text = sys.stdin.buffer.read().decode("utf-8").strip()
    if not text:
        return 0
    asyncio.run(_save(text, dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
