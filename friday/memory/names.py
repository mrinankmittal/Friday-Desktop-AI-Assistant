"""Parse and format personal name memories for anyone, not only the user."""

from __future__ import annotations

import re

_PREFIX = r"(?:please\s+|friday\s+|can you\s+)*"

_ALIASES = {
    "friend": "friend",
    "friends": "friend",
    "buddy": "friend",
    "mom": "mom",
    "mum": "mom",
    "mummy": "mom",
    "mother": "mom",
    "dad": "dad",
    "daddy": "dad",
    "papa": "dad",
    "pa": "dad",
    "father": "dad",
    "brother": "brother",
    "bro": "brother",
    "sister": "sister",
    "sis": "sister",
    "girlfriend": "girlfriend",
    "boyfriend": "boyfriend",
    "wife": "wife",
    "husband": "husband",
    "son": "son",
    "daughter": "daughter",
    "teacher": "teacher",
    "boss": "boss",
    "uncle": "uncle",
    "aunt": "aunt",
    "grandma": "grandma",
    "grandmother": "grandma",
    "grandpa": "grandpa",
    "grandfather": "grandpa",
}

_OWN = frozenset({"", "my", "me", "i", "mine", "own"})
_NAME_KINDS = frozenset({"first", "last", "full", "real", "middle"})
_RELATION_CANONICALS = frozenset(_ALIASES.values())
_SKIP_SUBJECTS = frozenset({"the", "a", "an", "this", "that", "his", "her", "their", "your"})

_NAME_ASK = re.compile(
    r"^\s*"
    + _PREFIX
    + r"(?:"
    r"do you know (?:what )?(?P<know>.+?)(?:'s|s)?\s+name(?:\s+is)?|"
    r"what(?:'s|s| is)\s+(?P<what>.+?)(?:'s|s)?\s+name|"
    r"tell me\s+(?P<tell>.+?)(?:'s|s)?\s+name|"
    r"(?P<whoami>who am i|do you know who i am)|"
    r"(?P<bare>my name)"
    r")\s*\??\s*$",
    flags=re.IGNORECASE,
)
_NAME_NEEDLE = re.compile(
    r"^\s*(?:do you know (?:what )?)?(?P<who>.+?)(?:'s|s)?\s+name(?:\s+is)?\s*$",
    flags=re.IGNORECASE,
)
_NAME_FACT = re.compile(
    r"^\s*(?P<who>.+?)(?:'s|s)?\s+name is\s+(?P<name>.+?)\s*$",
    flags=re.IGNORECASE,
)


def alias_token(token: str) -> str:
    lowered = token.lower()
    if lowered in _ALIASES:
        return _ALIASES[lowered]
    if lowered.endswith("s") and lowered[:-1] in _ALIASES:
        return _ALIASES[lowered[:-1]]
    return lowered


def canonical_subject(phrase: str) -> str:
    text = phrase.lower().replace("'", " ")
    text = re.sub(r"\bmy\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text in _OWN:
        return "own"
    if text in _ALIASES:
        return _ALIASES[text]
    if text.endswith("s") and text[:-1] in _ALIASES:
        return _ALIASES[text[:-1]]
    parts = [alias_token(part) for part in text.split() if part]
    if not parts:
        return "own"
    return " ".join(parts)


def _is_relation(subject: str) -> bool:
    if not subject:
        return False
    return subject.split()[-1] in _RELATION_CANONICALS


def stored_name_fact(subject: str, name: str) -> str:
    cleaned = name.strip().rstrip(".")
    if subject == "own":
        return f"my name is {cleaned}"
    if subject in _NAME_KINDS:
        return f"my {subject} name is {cleaned}"
    if _is_relation(subject):
        return f"my {subject}'s name is {cleaned}"
    return f"{subject}'s name is {cleaned}"


def search_query_for(subject: str) -> str:
    if subject == "own":
        return "my name"
    if subject in _NAME_KINDS:
        return f"my {subject} name"
    if _is_relation(subject):
        return f"my {subject}'s name"
    return f"{subject}'s name"


def parse_name_fact(content: str) -> tuple[str, str] | None:
    match = _NAME_FACT.match(content.strip())
    if match is None:
        return None
    who = match.group("who").strip()
    name = match.group("name").strip().rstrip(".")
    if not who or not name:
        return None
    if who.lower() in {"the", "a", "an", "this", "that"}:
        return None
    if re.search(
        r"\b(remember|note|forget|please|friday|search|ingest)\b",
        who,
        flags=re.IGNORECASE,
    ):
        return None
    return canonical_subject(who), name


def parse_name_question(text: str) -> str | None:
    match = _NAME_ASK.match(text.strip())
    if match is None:
        return None
    if match.group("whoami") or match.group("bare"):
        return "own"
    phrase = next(
        (
            value
            for value in (match.group("know"), match.group("what"), match.group("tell"))
            if value
        ),
        "",
    )
    if not phrase.strip():
        return "own"
    subject = canonical_subject(phrase)
    if subject in _SKIP_SUBJECTS:
        return None
    return subject


def name_subject(query: str) -> str | None:
    text = query.strip()
    asked = parse_name_question(text)
    if asked is not None:
        return asked
    lowered = text.lower()
    if lowered in {"name", "who am i"}:
        return "own"
    match = _NAME_NEEDLE.match(text)
    if match is None:
        return None
    subject = canonical_subject(match.group("who"))
    if subject in _SKIP_SUBJECTS:
        return None
    return subject


def restore_casing(original: str, fragment: str) -> str:
    needle = fragment.strip()
    if not needle:
        return fragment
    found = original.lower().find(needle.lower())
    if found < 0:
        return fragment
    return original[found : found + len(needle)]


def normalize_name_content(content: str, original: str = "") -> str:
    parsed = parse_name_fact(content)
    if parsed is None:
        return content.strip()
    subject, name = parsed
    if original:
        name = restore_casing(original, name)
    return stored_name_fact(subject, name)


def found_name_reply(subject: str, name: str) -> str:
    cleaned = name.strip().rstrip(".")
    if subject == "own":
        return f"Yes. Your name is {cleaned}."
    if subject in _NAME_KINDS:
        return f"Yes. Your {subject} name is {cleaned}."
    if _is_relation(subject):
        return f"Yes. Your {subject}'s name is {cleaned}."
    titled = cleaned[:1].upper() + cleaned[1:] if cleaned else cleaned
    label = subject[:1].upper() + subject[1:] if subject else subject
    return f"Yes. {label}'s name is {titled}."


def missing_name_reply(subject: str) -> str:
    if subject == "own":
        return (
            "I don't have your name yet. "
            "Say remember that my name is, then your name."
        )
    if subject in _NAME_KINDS:
        label = f"your {subject} name"
        hint = f"my {subject} name is"
    elif _is_relation(subject):
        label = f"your {subject}'s name"
        hint = f"my {subject}'s name is"
    else:
        label = f"{subject}'s name"
        hint = f"{subject}'s name is"
    return (
        f"I don't have {label} yet. "
        f"Say remember that {hint}, then the name."
    )


def name_from_hit(text: str, subject: str) -> str | None:
    parsed = parse_name_fact(text)
    if parsed is None:
        return None
    fact_subject, name = parsed
    if fact_subject != subject:
        return None
    return name
