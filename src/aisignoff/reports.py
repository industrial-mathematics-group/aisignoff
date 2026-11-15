"""The committed reports of AI reviews (docs/levels.md, "The record of a review").

A report lists its findings one per list item or heading that starts with the severity:

    - **minor:** the error message names the wrong file. Fixed in 3f1c9e0.
    ### [major] wrong result for an empty input

A fix for a finding from [review] recheck on needs a new review, whose report replaces this one.
So a report that lists such a finding is a review that no longer stands, and lint fails on it.
"""
from __future__ import annotations

import re
from pathlib import Path

from .globbing import matches
from .model import SEVERITIES

_FINDING = re.compile(r"^\s*(?:[-*+]|\d+[.)]|#{1,6})\s+(?:\*\*|\[)?\s*(%s)\s*(?::|\*\*|\])" % "|".join(SEVERITIES), re.I)
_FENCE = re.compile(r"^\s*(```|~~~)")


def findings(text: str) -> list[tuple[int, str]]:
    """(line number, severity) of each finding a report lists, outside fenced code blocks."""
    out, fence = [], None
    for number, line in enumerate(text.splitlines(), start=1):
        m = _FENCE.match(line)
        if m and fence in (None, m.group(1)):
            fence = None if fence else m.group(1)
            continue
        if fence:
            continue
        m = _FINDING.match(line)
        if m:
            out.append((number, m.group(1).lower()))
    return out


def problems(root: Path, files: list[str], globs: tuple[str, ...], recheck: str) -> list[str]:
    """One problem per finding from the severity `recheck` on in the Markdown files that match `globs`."""
    out = []
    for name in files:
        if not name.lower().endswith(".md") or not any(matches(g, name) for g in globs):
            continue
        try:
            text = (root / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, severity in findings(text):
            if SEVERITIES.index(severity) >= SEVERITIES.index(recheck):
                out.append(f"{name} line {number}: the review report lists a {severity} finding, and a fix for a finding "
                           f"from {recheck} on needs a new review ([review] recheck). Fix it, have the change reviewed "
                           "again, and commit the new report in place of this one")
    return out
