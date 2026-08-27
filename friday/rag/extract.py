from __future__ import annotations

from pathlib import Path

_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".py",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".ts",
    ".tsx",
    ".json",
    ".html",
    ".css",
    ".sql",
    ".log",
    ".ini",
    ".cfg",
    ".toml",
    ".yaml",
    ".yml",
    ".rst",
}

_BLOCKED_NAMES = {".env", "cookies.json"}
_BLOCKED_SUFFIXES = {".pem", ".onnx", ".key", ".exe", ".dll", ".bin"}
# The saved browser profile holds live session cookies, and Chromium stores
# them in extension-less files that extract_text() would happily read as text.
# The project lives under Desktop, which is an allowed folder, so the whole
# directory is off limits to the file, code and ingest tools.
_BLOCKED_DIR_NAMES = {".edge-profile"}
MAX_BYTES = 2_000_000


def is_blocked(path: Path) -> bool:
    name = path.name.lower()
    if name in _BLOCKED_NAMES:
        return True
    if any(part.lower() in _BLOCKED_DIR_NAMES for part in path.parts):
        return True
    return path.suffix.lower() in _BLOCKED_SUFFIXES


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _TEXT_SUFFIXES or suffix == "":
        return _read_text(path)
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix == ".docx":
        return _read_docx(path)
    raise ValueError(f"I can't ingest {suffix or 'that file type'} yet.")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise ValueError(
            "PDF ingest needs the pypdf package. Save the file as .txt or .md instead."
        ) from error
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    text = "\n".join(pages).strip()
    if not text:
        raise ValueError("That PDF has no readable text.")
    return text


def _read_docx(path: Path) -> str:
    try:
        import docx
    except ImportError as error:
        raise ValueError(
            "Word ingest needs the python-docx package. Save the file as .txt instead."
        ) from error
    document = docx.Document(str(path))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
    if not text:
        raise ValueError("That Word file has no readable text.")
    return text
