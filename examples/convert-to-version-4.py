#!/usr/bin/env python3
"""Rewrite SIGNOFF.toml from version 3 to version 4, the AI review scale of aisignoff 1.0.0rc6.

Version 4 changes what the AI review levels mean (docs/levels.md):

    version 3                                   version 4
    A1  self-check by the generating session    A0  (no independent AI review; AI-Reviewed-by is dropped)
    A2  review by a new session                 A1  context-free check
    A3  review or benchmark by another model    A3  (unchanged: check that it meets today's A3, or lower it)

and [policy] loses the built-in rules: 'ai = "A1"' was the self-check that G1-G3 always needed
(now A0, so nothing), and for G0 it meant a new session (now A1).

aisignoff 1.0.0rc6 and later read a version-3 file as exactly what this script writes, so the
reported levels don't change. With [history], the commit messages so far are on the old scale
too: for each commit of the default branch whose AI review reads differently on today's scale,
the script adds a [[commits]] entry with the level as it was meant (a template's old boxes are read
that way without one). Run it with aisignoff installed, at the repository root:

    python convert-to-version-4.py            # or: --dry-run to see the change only

Then change the AI review boxes of your pull request template in the same pull request. The full
steps are in docs/migrating.md.
"""
import difflib
import json
import re
import sys
import tomllib
from pathlib import Path

from aisignoff import config

NAME = "SIGNOFF.toml"
HEADER = re.compile(r"^\s*\[\[?\s*([^\]\s]+)\s*\]?\]")
LEVEL = re.compile(r'^(\s*"?AI-Review"?\s*=\s*)"(A[0-3])"')
NAMES = re.compile(r'^\s*"?AI-Reviewed-by"?\s*=')
POLICY = re.compile(r'^\s*"?(\*|G[0-3])"?\s*=\s*\{')
MINIMUM = re.compile(r'(\bai\s*=\s*)"(A[0-3])"')


def _blocks(lines):
    """The lines of the file in blocks: what comes before the first table, then one block per table."""
    blocks = [("", [])]
    for line in lines:
        m = HEADER.match(line)
        if m:
            blocks.append((m.group(1), []))
        blocks[-1][1].append(line)
    return blocks


def _without_names(lines):
    """A table's lines without its AI-Reviewed-by, which may be an array over several lines."""
    out, value = [], None
    for line in lines:
        if value is None and not NAMES.match(line):
            out.append(line)
            continue
        # the value ends with the line that makes it valid TOML ("#" and "]" may be inside a string)
        value = (value or "") + line
        try:
            tomllib.loads("x =" + value.split("=", 1)[1])
            value = None
        except tomllib.TOMLDecodeError:
            pass
    return out


def convert(text: str) -> str:
    out = []
    for table, lines in _blocks(text.splitlines(keepends=True)):
        if table == "":
            lines = [re.sub(r"^(\s*version\s*=\s*)3\b", r"\g<1>4", line) for line in lines]
        elif table in ("annotations", "commits", "attestations"):
            level = next((m.group(2) for m in map(LEVEL.match, lines) if m), None)
            if level == "A1":   # the self-check: no review now, and A0 names no reviewer
                lines = [LEVEL.sub(r'\g<1>"A0"', line) for line in _without_names(lines)]
            elif level == "A2":
                lines = [LEVEL.sub(r'\g<1>"A1"', line) for line in lines]
        elif table == "policy":
            keys = {m.group(1): line for line in lines if (m := POLICY.match(line))}
            new = []
            for line in lines:
                m = POLICY.match(line)
                if m and m.group(1) == "G0":
                    line = MINIMUM.sub(lambda a: a.group(1) + ('"A1"' if a.group(2) == "A2" else f'"{a.group(2)}"'), line)
                elif m:
                    line = MINIMUM.sub(lambda a: a.group(1) + {"A1": '"A0"', "A2": '"A1"'}.get(a.group(2), f'"{a.group(2)}"'),
                                       line)
                new.append(line)
                star = m and m.group(1) == "*" and MINIMUM.search(keys["*"])
                if star and star.group(2) == "A1":   # for hand-written content, A1 meant a new session
                    g0 = keys.get("G0")
                    if g0 is None:
                        new.append('G0  = { ai = "A1" }   # version 3: a minimum of A1 meant a new session for G0\n')
                    elif not MINIMUM.search(g0):
                        sys.exit(f'{NAME}: add ai = "A1" to the G0 line of [policy] by hand (in version 3, the "*" '
                                 "minimum of A1 meant a new session for G0), then run this script again")
            lines = new
        out += lines
    return "".join(out)


def commit_entries(root: Path, before, after) -> str:
    """[[commits]] entries that keep the AI review of each commit of the default branch as the old
    scale meant it, where today's scale would read its message otherwise."""
    if not before.history.enabled:
        return ""
    from aisignoff.history import History, unavailable_reason
    from aisignoff.model import AI_REVIEWED
    if unavailable_reason(root):
        sys.exit("[history] is enabled, but the whole git history isn't here (a shallow clone?): fetch it first, so "
                 "that the commit messages can be kept as they were meant")
    old = History(root, before)
    new = History(root, after)
    corrected = {old._resolve(c.commit) for c in before.commits if "AI-Review" in c.values}
    out = []
    for sha in sorted(old.order, key=old.order.get):
        was, now = old._trailers.get(sha, {}).get(2), new._trailers.get(sha, {}).get(2)
        if was is None or sha in corrected or (now is not None and (now.level, now.names) == (was.level, was.names)):
            continue
        out.append(f'\n[[commits]]   # {old.describe(sha)}: its AI review on the scale before version 4\n'
                   f'commit = "{sha}"\nAI-Review = "{was.level}"\n'
                   + (f"{AI_REVIEWED} = {json.dumps(list(was.names), ensure_ascii=False)}\n" if was.names else ""))
    return "".join(out)


def main(argv):
    dry = "--dry-run" in argv
    path = Path(NAME)
    if not path.is_file():
        sys.exit(f"no {NAME} here: run this at the repository root")
    old = path.read_text(encoding="utf-8")
    before = config.load_text(old, path)
    if not before.version_3:
        sys.exit(f"{NAME} is not version 3: nothing to convert")
    new = convert(old)
    try:
        after = config.load_text(new, path)
    except config.ConfigError:
        after = None
    same = after is not None and all(getattr(before, key) == getattr(after, key)
               for key in ("annotations", "policy", "commits", "attestations", "exclude", "history"))
    if not same or after.version_3:
        sys.exit(f"{NAME} has a layout this script can't convert (nothing was written). Edit it by hand: "
                 "see the table at the top of this script, or docs/migrating.md")
    new += commit_entries(Path("."), before, after)
    sys.stdout.writelines(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                               NAME, NAME + " (version 4)"))
    if not dry:
        path.write_text(new, encoding="utf-8")
        print(f"\nWrote {NAME} as version 4.")
    print("\nNext: change the AI review boxes of your pull request template (docs/history.md), and check that "
          "every A3 meets today's A3 (docs/levels.md).")


if __name__ == "__main__":
    main(sys.argv[1:])
