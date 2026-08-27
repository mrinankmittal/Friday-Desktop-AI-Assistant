"""Synthesize one utterance with edge-tts.

Eel runs under gevent, so asyncio edge-tts cannot run in the app process.
This module is launched as ``python -m friday.providers.edge_speak``.
Text arrives on stdin (UTF-8); argv is ``voice outfile rate``.
"""

from __future__ import annotations

import asyncio
import sys


async def _save(text: str, voice: str, dest: str, rate: str) -> None:
    import edge_tts

    last_error: BaseException | None = None
    for attempt in range(2):
        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            await communicate.save(dest)
            return
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                await asyncio.sleep(0.5)
    assert last_error is not None
    raise last_error


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print("usage: edge_speak VOICE OUTFILE [RATE]", file=sys.stderr)
        return 2
    voice, dest = args[0], args[1]
    rate = args[2] if len(args) > 2 else "-8%"
    text = sys.stdin.buffer.read().decode("utf-8").strip()
    if not text:
        return 0
    asyncio.run(_save(text, voice, dest, rate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
