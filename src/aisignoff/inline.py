"""Inline declarations: a block of tag lines in a comment near the top of a file.

    # AI-Generation: G2
    # Human-Review: H2
    # AI-Review: A2
    # Assisted-by: Claude Opus 5.5 (Anthropic)
    # AI-Reviewed-by: Claude Opus 5.5 (Anthropic), fresh session
    # Reviewed-by: Jane Doe

Rules that keep documentation from being mistaken for a declaration:

* only file types with a known comment syntax are read, and only their first
  ``HEADER_LINES`` lines;
* a tag must be in a comment of the file's own syntax (``<!-- -->`` in Markdown, ``#`` in
  Julia, ...) and start at the beginning of the line (``*`` continuation lines of
  ``/* */`` comments may be indented); in Markdown, fenced code blocks are skipped;
* tag lines only count as a contiguous block, and the block must contain a valid
  level line (``AI-Generation: G0``–``G3``, ``Human-Review: H0``–``H3`` or
  ``AI-Review: A0``–``A3``).
"""
from __future__ import annotations

import re
from pathlib import Path

from .model import GEN, KEYS, LEVELS, LIST_KEYS, Declaration, canonical_key

HEADER_LINES = 30
BOM = "﻿"

# Comment styles: name -> regex for the opening token
_STYLES = {
    "#": r"#=?",
    "//": r"//",
    "/*": r"/\*+|[ \t]*\*(?!/)",
    "%": r"%+",
    "--": r"--",
    ";": r";+",
    "<!--": r"<!--",
    "(*": r"\(\*",
}
# Comment syntax by file extension; the first entry is used when writing tags.
COMMENT_STYLES = {
    ".jl": ["#"], ".py": ["#"], ".sh": ["#"], ".bash": ["#"], ".zsh": ["#"], ".r": ["#"],
    ".toml": ["#"], ".yml": ["#"], ".yaml": ["#"], ".rb": ["#"], ".pl": ["#"], ".cfg": ["#"],
    ".cmake": ["#"], ".mk": ["#"], ".ps1": ["#"], ".nix": ["#"],
    ".c": ["//", "/*"], ".h": ["//", "/*"], ".cc": ["//", "/*"], ".cpp": ["//", "/*"],
    ".hpp": ["//", "/*"], ".cu": ["//", "/*"], ".js": ["//", "/*"], ".mjs": ["//", "/*"],
    ".ts": ["//", "/*"], ".jsx": ["//", "/*"], ".tsx": ["//", "/*"], ".java": ["//", "/*"],
    ".go": ["//", "/*"], ".rs": ["//", "/*"], ".swift": ["//", "/*"], ".kt": ["//", "/*"],
    ".scala": ["//", "/*"], ".cs": ["//", "/*"], ".glsl": ["//", "/*"], ".typ": ["//", "/*"],
    ".css": ["/*"],
    ".tex": ["%"], ".sty": ["%"], ".cls": ["%"], ".bib": ["%"], ".m": ["%"],
    ".lua": ["--"], ".sql": ["--"], ".hs": ["--"],
    ".el": [";"], ".lisp": [";"], ".scm": [";"], ".ini": [";", "#"], ".asm": [";"],
    ".md": ["<!--"], ".markdown": ["<!--"], ".qmd": ["<!--"], ".rmd": ["<!--"],
    ".html": ["<!--"], ".htm": ["<!--"], ".xml": ["<!--"], ".svg": ["<!--"], ".vue": ["<!--"],
    ".ml": ["(*"],
}
_NAME_STYLES = {
    "Makefile": ["#"], "Dockerfile": ["#"], "Project.toml": ["#"], "Manifest.toml": ["#"],
    ".gitignore": ["#"], ".gitattributes": ["#"], ".editorconfig": ["#", ";"],
}
_FRONT_MATTER = {".md", ".markdown", ".qmd", ".rmd"}
_FENCED = _FRONT_MATTER

_KEY_RE = "|".join(re.escape(k) for k in sorted(KEYS, key=len, reverse=True))
_CLOSERS = r"(?:-->|\*/|=#|\*\))"
_LINE_BREAK = re.compile(r"\r\n|\n|\r")


def _styles_for(path: Path) -> list[str] | None:
    """Comment styles of a file type; None means the type has no known comment syntax."""
    if path.name in _NAME_STYLES:
        return _NAME_STYLES[path.name]
    return COMMENT_STYLES.get(path.suffix.lower())


def comment_style(path: Path) -> str | None:
    styles = _styles_for(path)
    return styles[0] if styles else None


def _tag_regex(styles: list[str]) -> re.Pattern:
    openers = "|".join(_STYLES[s] for s in styles)
    return re.compile(rf"^(?:{openers})[ \t]*({_KEY_RE})[ \t]*:[ \t]*(.*?)[ \t]*{_CLOSERS}?[ \t]*$",
                      re.IGNORECASE)


def split_lines(text: str) -> list[str]:
    """Split on \\r\\n, \\n or \\r only (str.splitlines also splits on \\f, U+2028, ...)."""
    if not text:
        return []
    lines = _LINE_BREAK.split(text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def read_head(path: Path) -> list[str] | None:
    """First HEADER_LINES lines of a text file, or None for binary or unreadable files."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(16384)
    except OSError:
        return None
    if b"\x00" in chunk:
        return None
    text = chunk.decode("utf-8", errors="replace").removeprefix(BOM)
    return split_lines(text)[:HEADER_LINES]


def _is_anchor(key: str, value: str) -> bool:
    return key in LEVELS and (value in LEVELS[key] or value == "TODO")  # TODO: placeholder for a person


def find_blocks(path: Path, lines: list[str]) -> list[list[tuple[int, str, str]]]:
    """Declaration blocks: runs of adjacent tag lines that contain a valid level line."""
    styles = _styles_for(path)
    if styles is None:
        return []
    regex = _tag_regex(styles)
    fenced = path.suffix.lower() in _FENCED
    fence = None  # the marker (``` or ~~~) of the open fenced code block
    blocks, current = [], []
    for i, line in enumerate(lines):
        if fenced:
            m_fence = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
            if m_fence:
                marker = m_fence.group(1)
                if fence is None:
                    fence = marker
                elif marker[0] == fence[0] and len(marker) >= len(fence):
                    fence = None
                    continue
        in_fence = fence is not None
        m = None if in_fence else regex.match(line)
        if m:
            current.append((i, canonical_key(m.group(1)), m.group(2).strip()))
            continue
        if current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return [b for b in blocks if any(_is_anchor(k, v) for _, k, v in b)]


def parse_values(path: Path) -> tuple[dict, list[str]] | None:
    """Raw values of the inline block, or None if there is none."""
    lines = read_head(path)
    if not lines:
        return None
    blocks = find_blocks(path, lines)
    if not blocks:
        return None
    values: dict = {}
    problems = []
    if len(blocks) > 1:
        problems.append("more than one inline declaration block")
    for _, key, value in blocks[0]:
        if key in LIST_KEYS:
            if value:
                values.setdefault(key, []).append(value)
        elif key in values:
            problems.append(f"inline {key} given more than once")
        else:
            values[key] = value
    return values, problems


def parse(path: Path) -> Declaration | None:
    """The inline declaration of a file, or None if it has none."""
    found = parse_values(path)
    if found is None:
        return None
    values, problems = found
    d = Declaration.from_mapping(values, source="inline")
    d.problems.extend(problems)
    return d


def render(style: str, values: dict) -> list[str]:
    """Header lines for `values` in the given comment style."""
    pairs = []
    for key in KEYS:
        v = values.get(key)
        if not v:
            continue
        for item in ([v] if isinstance(v, str) else v):
            pairs.append(f"{key}: {item}")
    if style == "<!--":
        return [f"<!-- {p} -->" for p in pairs]
    if style == "/*":
        return [f"/* {p} */" for p in pairs]
    if style == "(*":
        return [f"(* {p} *)" for p in pairs]
    return [f"{style} {p}" for p in pairs]


_PEP263 = re.compile(r"^[ \t\f]*#.*?coding[:=]")


def _insert_position(path: Path, lines: list[str]) -> int:
    """Skip lines that must stay first: shebang, encoding line, XML declaration and
    (Markdown/Quarto only) YAML front matter."""
    at = 0
    if lines and lines[0].startswith("#!"):
        at = 1
    if at < len(lines) and _PEP263.match(lines[at]):
        at += 1
    if at < len(lines) and lines[at].startswith("<?xml"):
        at += 1
    if path.suffix.lower() in _FRONT_MATTER and at < len(lines) and lines[at].strip() == "---":
        for j in range(at + 1, len(lines)):
            if lines[j].strip() in ("---", "..."):
                return j + 1
    return at


def write(path: Path, values: dict) -> None:
    """Insert or replace the inline declaration block at the top of a text file.

    Line endings, a byte-order mark and every other line of the file are kept as they are.
    """
    style = comment_style(path)
    if style is None:
        raise ValueError(f"{path}: no known comment syntax; declare it in SIGNOFF.toml instead")
    raw = path.read_bytes()
    if b"\x00" in raw[:16384]:
        raise ValueError(f"{path}: binary file; declare it in SIGNOFF.toml instead")
    text = raw.decode("utf-8")
    bom = BOM if text.startswith(BOM) else ""
    text = text.removeprefix(BOM)
    # keep each line's own ending
    pieces = re.findall(r"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+$", text)
    newline = "\r\n" if "\r\n" in text else ("\r" if "\r" in text and "\n" not in text else "\n")
    content = [p.rstrip("\r\n") for p in pieces]

    blocks = find_blocks(path, content[:HEADER_LINES])
    new = [l + newline for l in render(style, values)]
    if blocks:
        old = {i for b in blocks for i, _, _ in b}
        at = min(old)
        pieces = [p for i, p in enumerate(pieces) if i not in old]
    else:
        at = _insert_position(path, content)
        if at < len(content) and content[at].strip():
            new.append(newline)
        if at > 0 and at == len(pieces) and not pieces[-1].endswith(("\n", "\r")):
            pieces[-1] += newline  # file without final newline: don't glue the tag to the last line
    n_tags = len(render(style, values))
    if at + n_tags > HEADER_LINES:
        raise ValueError(f"{path}: the declaration would not fit into the first {HEADER_LINES} lines "
                         "(long front matter?); declare it in SIGNOFF.toml instead")
    pieces[at:at] = new
    original = raw
    path.write_bytes((bom + "".join(pieces)).encode("utf-8"))

    expected = Declaration.from_mapping(values, source="inline").as_dict()
    check = parse(path)
    if check is None or check.as_dict() != expected or check.problems:
        path.write_bytes(original)
        raise ValueError(f"{path}: the written header could not be read back; file left unchanged. "
                         "Declare it in SIGNOFF.toml instead")
