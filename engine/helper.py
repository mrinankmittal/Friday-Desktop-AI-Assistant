import re

# Dropped only from the *start* of a WhatsApp request so the message body
# can still contain words like "call" or "please".
COMMS_FILLER_WORDS = {
    "a",
    "call",
    "make",
    "message",
    "phone",
    "please",
    "send",
    "text",
    "to",
    "video",
    "voice",
    "whatsapp",
}

_MESSAGE_LEADINS = frozenset({"say", "saying", "that"})


def extract_yt_term(command: str) -> str:
    # Define a regular expression pattern to capture the song name
    pattern = r'play\s+(.*?)\s+on\s+youtube'
    # Use re.search to find the match in the command
    match = re.search(pattern, command, re.IGNORECASE)
    # Always return a string so callers never receive None.
    return match.group(1).strip() if match else ""

def remove_words(input_string, words_to_remove):
    excluded_words = {str(word).lower() for word in words_to_remove}
    return " ".join(
        word for word in input_string.split()
        if word.lower() not in excluded_words
    )


def comms_search_text(query: str, extra_words: set[str] | None = None) -> str:
    """Drop leading command filler. Words after the contact name are left intact."""
    excluded = set(COMMS_FILLER_WORDS)
    if extra_words:
        excluded.update(str(word).lower() for word in extra_words if str(word).strip())
    tokens = str(query).split()
    index = 0
    while index < len(tokens) and tokens[index].lower().strip(".,!?") in excluded:
        index += 1
    return " ".join(tokens[index:]).strip()


def _strip_message_leadin(message: str) -> str:
    tokens = str(message).split()
    if tokens and tokens[0].lower().strip(".,!?") in _MESSAGE_LEADINS:
        return " ".join(tokens[1:]).strip()
    return str(message).strip()


def match_named_contact(
    text: str,
    contacts: list[tuple[str, str]],
) -> tuple[str, str, str] | None:
    """Pick a contact from ``text``. Longer names win; leftover words are the message.

    Returns ``(name, mobile, message)`` or ``None``. Every contact competes equally.
    """
    haystack = " ".join(text.split()).strip()
    lowered = haystack.lower()
    if not lowered or not contacts:
        return None

    prefix_hit: tuple[int, str, str, str] | None = None
    for name, mobile in contacts:
        name_l = str(name).strip().lower()
        if not name_l:
            continue
        if lowered == name_l:
            candidate = (len(name_l), str(name), str(mobile), "")
        elif lowered.startswith(name_l + " "):
            remainder = _strip_message_leadin(haystack[len(name_l) :].strip())
            candidate = (len(name_l), str(name), str(mobile), remainder)
        else:
            continue
        if prefix_hit is None or candidate[0] > prefix_hit[0]:
            prefix_hit = candidate
    if prefix_hit:
        return prefix_hit[1], prefix_hit[2], prefix_hit[3]

    tokens = haystack.split()
    first = tokens[0].lower()
    rest = " ".join(tokens[1:])
    unique = [
        (str(name), str(mobile))
        for name, mobile in contacts
        if str(name).strip().lower() == first
        or str(name).strip().lower().startswith(first)
    ]
    exact = [
        pair
        for pair in unique
        if pair[0].strip().lower() == first
        or pair[0].strip().lower().split()[0] == first
    ]
    pool = exact or unique
    if len(pool) == 1:
        return pool[0][0], pool[0][1], _strip_message_leadin(rest)

    substring_hit: tuple[tuple[int, int], str, str, str] | None = None
    for name, mobile in contacts:
        name_l = str(name).strip().lower()
        if not name_l:
            continue
        index = lowered.find(name_l)
        if index < 0:
            continue
        if index > 0 and lowered[index - 1] != " ":
            continue
        end = index + len(name_l)
        if end < len(lowered) and lowered[end] != " ":
            continue
        remainder = _strip_message_leadin(haystack[end:].strip())
        score = (len(name_l), -index)
        if substring_hit is None or score > substring_hit[0]:
            substring_hit = (score, str(name), str(mobile), remainder)
    if substring_hit:
        return substring_hit[1], substring_hit[2], substring_hit[3]

    return None


def message_after_contact(
    query: str,
    contact_name: str,
    extra_words: set[str] | None = None,
) -> str:
    """Message body after a resolved contact name, if the user already said it."""
    text = comms_search_text(query, extra_words)
    matched = match_named_contact(text, [(contact_name, "")])
    if matched is None:
        return ""
    return matched[2].strip()
