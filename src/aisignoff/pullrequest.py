"""The check of a pull request before it is merged (lint --declare-from, --base): what its description
declares must be complete on its own, the rules of the branch it goes into apply, and it can't change
those rules itself.

These rules apply to the check before the merge only. How landed commits are read is unchanged, so
existing history and snapshots keep their levels."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import FILENAME, Config, ConfigError, load_text
from .model import AI_REVIEWED, AIR

_RESPONSIBLE = re.compile(r"^\s*Responsible person:\s*@?([A-Za-z0-9][A-Za-z0-9-]*(?:\[bot\])?)\s*$", re.I)


def is_bot(login: str) -> bool:
    """A GitHub App or bot account, such as github-actions[bot] or dependabot[bot]."""
    return login.strip().lower().endswith("[bot]")


def responsible_person(text: str) -> str | None:
    """The login on a "Responsible person: @login" line outside code blocks and comments."""
    from .history import _prose_lines
    for line in _prose_lines(text):
        m = _RESPONSIBLE.match(line)
        if m:
            return m.group(1)
    return None


def reviewer(text: str, author: str) -> tuple[str, list[str], list[str]]:
    """Who the human review of a ticked template is by: the pull request's author, or for a pull
    request opened by a bot, the "Responsible person" it names. Returns (name, problems, notes)."""
    named = responsible_person(text)
    if author and is_bot(author):
        if named is None:
            return author, [f"the pull request was opened by the bot account {author}, which can't take "
                            "responsibility: add a line \"Responsible person: @login\" naming the human who does"], []
        if is_bot(named):
            return author, [f"the responsible person {named} is a bot account; name a human"], []
        return named, [], []
    if named and author and named.lower() != author.lower():
        return author, [], [f"\"Responsible person: @{named}\" is only read for pull requests opened by bots; "
                            f"the responsible human is the author, {author}"]
    return author, [], []


@dataclass
class BaseRules:
    """SIGNOFF.toml of the branch a pull request goes into, and how the pull request changes it."""

    config: Config | None  # None: that branch has no SIGNOFF.toml
    changed: list[str] = field(default_factory=list)  # protected settings the pull request changes
    # declarations that read differently only because the pull request changes 'version' to 4
    unconverted: list[str] = field(default_factory=list)


def _show(root: Path, rev: str, name: str) -> str | None:
    """A file of commit REV, relative to ROOT (which may be a subfolder of the repository)."""
    from .history import _git
    return _git(root, "show", f"{rev}:./{name}", check=False)


def base_rules(root: Path, base: str, head: Config) -> BaseRules:
    """The rules of the base branch BASE, and which protected settings HEAD's SIGNOFF.toml changes:
    [policy], [review], exclude, [history] and version (which decides the scale the AI review levels
    are read on). A repository's first SIGNOFF.toml changes nothing."""
    text = _show(root, base, FILENAME)
    if text is None:
        return BaseRules(None)
    config = load_text(text, Path(f"{FILENAME} on {base}"))
    changed = []
    if config.policy.rules != head.policy.rules:
        changed.append("[policy]")
    if set(config.exclude) != set(head.exclude):
        changed.append("exclude")
    if config.history != head.history:
        changed.append("[history]")
    if config.recheck != head.recheck:
        changed.append("[review]")
    unconverted = []
    if config.version_3 != head.version_3:
        changed.append("version")
        # the change to version 4 rewrites the levels (examples/convert-to-version-4.py): an entry that
        # is still there must read as before, or the change would raise its AI review by itself
        for what, key in (("annotations", "paths"), ("commits", "commit"), ("attestations", "blob")):
            before = {getattr(e, key): e.values.get(AIR) for e in getattr(config, what)}
            for e in getattr(head, what):
                was = before.get(getattr(e, key))
                now = e.values.get(AIR)
                if was and now and was != now:
                    name = ", ".join(e.paths) if what == "annotations" else getattr(e, key)[:12]
                    unconverted.append(f"{FILENAME} changes to version {4 if config.version_3 else 3} without converting "
                                       f"its levels: the entry for {name} read {AIR} {was} before and reads {now} now. "
                                       "Convert the file with examples/convert-to-version-4.py, and raise levels "
                                       "in another change")
    return BaseRules(config, changed, unconverted)


_REPORT_PATH = re.compile(r"[\w./@+-]*[\w@+-]\.md\b", re.I)
_REPORT_HIGHEST = re.compile(r"Highest finding in this change[\s:*_`]*(none|trivial|minor|major|critical)\b", re.I)
_REPORT_OUTSIDE = re.compile(r"^#+\s*Outside this change\b", re.I | re.M)


def review_problems(root: Path, piece, findings: str | None, recheck: str) -> list[str]:
    """The check before the merge of a pull request that declares A2 or A3 (PIECE, its AI review):
    the "AI-Review-Findings:" line FINDINGS, and the review report that AI-Reviewed-by names, which
    is in the change, follows the template (examples/review-report.md) and says the same severity."""
    from .model import FINDINGS, findings_problems
    level = piece.level if piece else None
    problems = findings_problems(level, findings, recheck, required=True)
    if level not in ("A2", "A3"):
        return problems
    paths = [m.group(0).removeprefix("./") for name in piece.names for m in _REPORT_PATH.finditer(name)]
    if not paths:
        return problems + [f"{level} needs its review report in {AI_REVIEWED}: the path of the Markdown file "
                           "(after the model: \"GPT Sol (OpenAI), reviews/pull12.md\")"]
    found = [p for p in paths if (root / p).is_file()]
    if not found:
        return problems + [f"the review report {paths[0]} isn't in this change: commit it with the pull request"]
    text = (root / found[0]).read_text(encoding="utf-8", errors="replace")
    highest = _REPORT_HIGHEST.search(text)
    if not highest or not _REPORT_OUTSIDE.search(text):
        problems.append(f"the review report {found[0]} doesn't follow the template (examples/review-report.md): it needs "
                        "the line \"Highest finding in this change: …\" and the section \"Outside this change\"")
    elif findings and highest.group(1).lower() != findings.strip().lower():
        problems.append(f"the review report {found[0]} says \"Highest finding in this change: {highest.group(1).lower()}\", "
                        f"but the description says {FINDINGS}: {findings}")
    return problems


def description_problems(pieces: dict, policy) -> list[str]:
    """What is missing from a pull request description, checked on its own: every axis with the names
    its level needs, the built-in rules and the policy, whether or not the change has lines to declare."""
    from .history import combine
    from .model import validate
    d = combine([pieces.get(i) for i in range(3)])
    if d.source == "none" and not d.problems:
        return ["it declares nothing: fill in the AI declaration of the template (or \"Key: value\" lines)"]
    return validate(d, policy)
