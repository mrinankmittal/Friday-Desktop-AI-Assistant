"""Synthesize one Hindi utterance with Google Translate TTS.

Eel runs under gevent, so this module is launched as
``python -m friday.providers.gtts_speak``. Text arrives on stdin (UTF-8);
argv is ``outfile [lang]``.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: gtts_speak OUTFILE [LANG]", file=sys.stderr)
        return 2
    dest = args[0]
    lang = args[1] if len(args) > 1 else "hi"
    text = sys.stdin.buffer.read().decode("utf-8").strip()
    if not text:
        return 0
    from gtts import gTTS

    gTTS(text=text, lang=lang, tld="co.in", slow=False).save(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
