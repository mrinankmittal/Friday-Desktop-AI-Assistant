"""Devanagari → Latin so English SAPI voices can speak Hindi replies.

This machine only has David/Zira. They stay silent on Devanagari, but they
can read Hinglish. A Hindi SAPI voice still gets the original script.
"""

from __future__ import annotations

import re

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")

_INDEPENDENT = {
    "अ": "a",
    "आ": "aa",
    "इ": "i",
    "ई": "ee",
    "उ": "u",
    "ऊ": "oo",
    "ऋ": "ri",
    "ए": "e",
    "ऐ": "ai",
    "ओ": "o",
    "औ": "au",
}

_MATRA = {
    "ा": "aa",
    "ि": "i",
    "ी": "ee",
    "ु": "u",
    "ू": "oo",
    "ृ": "ri",
    "े": "e",
    "ै": "ai",
    "ो": "o",
    "ौ": "au",
}

_CONS = {
    "क": "k",
    "ख": "kh",
    "ग": "g",
    "घ": "gh",
    "ङ": "ng",
    "च": "ch",
    "छ": "chh",
    "ज": "j",
    "झ": "jh",
    "ञ": "ny",
    "ट": "t",
    "ठ": "th",
    "ड": "d",
    "ढ": "dh",
    "ण": "n",
    "त": "t",
    "थ": "th",
    "द": "d",
    "ध": "dh",
    "न": "n",
    "प": "p",
    "फ": "ph",
    "ब": "b",
    "भ": "bh",
    "म": "m",
    "य": "y",
    "र": "r",
    "ल": "l",
    "व": "v",
    "श": "sh",
    "ष": "sh",
    "स": "s",
    "ह": "h",
}

_NUKTA_CONS = {
    "फ": "f",
    "ज": "z",
    "ड": "d",
    "ढ": "dh",
    "क": "q",
    "ख": "kh",
    "ग": "gh",
}

_VIRAMA = "\u094d"
_NUKTA = "\u093c"
_ANUSVARA = "\u0902"
_CANDRA = "\u0901"
_VISARGA = "\u0903"

_ASSISTANT = (
    ("\u092b\u094d\u0930\u093e\u092f \u0921\u0947", "Friday"),  # फ्राय डे
    ("\u092b\u094d\u0930\u093e\u0907\u0921\u0947", "Friday"),  # फ्राइडे
    ("\u092b\u094d\u0930\u093e\u092f\u0921\u0947", "Friday"),  # फ्रायडे
    ("\u092b\u094d\u0930\u093e\u0908\u0921\u0947", "Friday"),  # फ्राईडे
)


def has_devanagari(text: str) -> bool:
    return bool(_DEVANAGARI.search(text or ""))


def romanize_devanagari(text: str) -> str:
    """Turn Hindi script into speakable Hinglish. Latin text is left as-is."""
    if not text or not has_devanagari(text):
        return text
    sample = str(text)
    for source, dest in _ASSISTANT:
        sample = sample.replace(source, dest)
    out: list[str] = []
    i = 0
    while i < len(sample):
        char = sample[i]
        if char in _INDEPENDENT:
            out.append(_INDEPENDENT[char])
            i += 1
            i = _take_nasal(sample, i, out)
            continue
        if char in _CONS:
            cons = _CONS[char]
            i += 1
            if i < len(sample) and sample[i] == _NUKTA:
                cons = _NUKTA_CONS.get(char, cons)
                i += 1
            if i < len(sample) and sample[i] == _VIRAMA:
                out.append(cons)
                i += 1
                continue
            if i < len(sample) and sample[i] in _MATRA:
                out.append(cons + _MATRA[sample[i]])
                i += 1
            else:
                out.append(cons + "a")
            i = _take_nasal(sample, i, out)
            continue
        if char == "।":
            out.append(".")
        elif char == "॥":
            out.append(".")
        elif char not in _MATRA and char not in {_VIRAMA, _NUKTA}:
            out.append(char)
        i += 1
    roman = "".join(out)
    roman = re.sub(r"\s+", " ", roman).strip()
    return roman


def _take_nasal(sample: str, index: int, out: list[str]) -> int:
    if index >= len(sample):
        return index
    mark = sample[index]
    if mark == _ANUSVARA or mark == _CANDRA:
        out.append("n")
        return index + 1
    if mark == _VISARGA:
        out.append("h")
        return index + 1
    return index
