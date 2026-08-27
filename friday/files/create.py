"""Spoken 'make a cpp file' → a filename and starter text."""

from __future__ import annotations

import re

_KIND_SUFFIX = {
    "c plus plus": ".cpp",
    "c++": ".cpp",
    "c + +": ".cpp",
    "cpp": ".cpp",
    "see plus plus": ".cpp",
    "c": ".c",
    "python": ".py",
    "py": ".py",
    "java": ".java",
    "javascript": ".js",
    "js": ".js",
    "text": ".txt",
    "txt": ".txt",
    "markdown": ".md",
    "md": ".md",
    "html": ".html",
    "css": ".css",
}

_KIND_LABELS = frozenset(
    {
        *(_KIND_SUFFIX.keys()),
        "c_plus_plus",
        "cplusplus",
        "source",
        "file",
        "program",
        "code",
    }
)

_NAME_LEAD = re.compile(
    r"^(?:a |an |the |file |named |called |of |for |about )+",
    re.IGNORECASE,
)
_CPP_SPOKEN = re.compile(
    r"(?:(?<=\s)|^)(?:c\s*\+\s*\+|c\s+plus\s+plus|see\s+plus\s+plus)(?=\s|$)",
    re.IGNORECASE,
)


def normalize_make_utterance(text: str) -> str:
    """Collapse STT spellings of C++ so 'c + + file' matches like 'cpp file'."""
    return _CPP_SPOKEN.sub("cpp", " ".join(text.lower().split()))


def is_kind_label(raw: str) -> bool:
    """True when the spoken 'name' is just a language word like 'c plus plus'."""
    text = " ".join(raw.strip().lower().replace("_", " ").split())
    text = _CPP_SPOKEN.sub("cpp", text)
    return text in _KIND_LABELS or text.replace(" ", "") in {
        item.replace(" ", "") for item in _KIND_LABELS
    }


def suffix_for_kind(kind: str) -> str | None:
    return _KIND_SUFFIX.get(" ".join(kind.lower().split()))


def clean_file_stem(raw: str, *, fallback: str = "") -> str:
    text = _NAME_LEAD.sub("", " ".join(raw.strip().split()))
    text = re.sub(r"[^\w.-]+", "_", text).strip("._")
    if "." in text:
        text = text.rsplit(".", 1)[0]
    return text or fallback


def starter_text(suffix: str, title: str) -> str:
    label = title.replace("_", " ").strip() or "Hello"
    if suffix == ".cpp":
        return (
            "#include <iostream>\n\n"
            "int main() {\n"
            f'    std::cout << "{label}" << std::endl;\n'
            "    return 0;\n"
            "}\n"
        )
    if suffix == ".c":
        return (
            "#include <stdio.h>\n\n"
            "int main(void) {\n"
            f'    printf("{label}\\n");\n'
            "    return 0;\n"
            "}\n"
        )
    if suffix == ".py":
        return f'print("{label}")\n'
    if suffix == ".java":
        class_name = re.sub(r"[^A-Za-z0-9]", "", label.title()) or "Main"
        if class_name[0].isdigit():
            class_name = "App" + class_name
        return (
            f"public class {class_name} {{\n"
            "    public static void main(String[] args) {\n"
            f'        System.out.println("{label}");\n'
            "    }\n"
            "}\n"
        )
    if suffix == ".js":
        return f'console.log("{label}");\n'
    if suffix == ".html":
        return (
            "<!DOCTYPE html>\n<html>\n<head><title>"
            f"{label}</title></head>\n<body>\n<h1>{label}</h1>\n"
            "</body>\n</html>\n"
        )
    if suffix == ".md":
        return f"# {label}\n"
    return f"{label}\n"


_SAYS_SPLIT = re.compile(
    r"\s+(?:that |which |where it )?(?:shows|prints|says|displays)\s+",
    re.IGNORECASE,
)


def split_name_and_says(raw: str) -> tuple[str, str]:
    """Split 'calculator where it shows hello' into name and printed text."""
    text = " ".join(raw.split())
    match = _SAYS_SPLIT.search(text)
    if not match:
        return text, ""
    return text[: match.start()].strip(), text[match.end() :].strip()


def plan_new_file(
    *,
    kind: str = "",
    name: str = "",
    says: str = "",
) -> tuple[str, str]:
    """Return ``(filename, text)``. Empty filename means ask for a name."""
    raw_name, found_says = split_name_and_says(name)
    printed_source = says or found_says
    suffix = suffix_for_kind(kind) if kind else ""
    raw_name = " ".join(raw_name.split())
    if raw_name and "." in raw_name.split()[-1]:
        filename = raw_name.split()[-1]
        if not suffix:
            suffix = "." + filename.rsplit(".", 1)[-1].lower()
        stem = clean_file_stem(filename)
        if not stem:
            return "", starter_text(suffix or ".txt", printed_source or "Hello")
        filename = f"{stem}{suffix}" if suffix else filename
    else:
        if not suffix:
            suffix = ".txt"
        if is_kind_label(raw_name):
            return "", starter_text(suffix, printed_source or "Hello")
        stem = clean_file_stem(raw_name)
        if not stem:
            return "", starter_text(suffix, printed_source or "Hello")
        filename = f"{stem}{suffix}"
    printed = " ".join((printed_source or stem.replace("_", " ") or "Hello").split())
    return filename, starter_text(suffix, printed)
