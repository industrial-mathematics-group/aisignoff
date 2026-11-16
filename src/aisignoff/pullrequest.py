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
    ignore_revs: str | None = None  # the blame ignore file, when the pull request changes its entries


def _show(root: Path, rev: str, name: str) -> str | None:
    """A file of commit REV, relative to ROOT (which may be a subfolder of the repository)."""
    from .history import _git
    return _git(root, "show", f"{rev}:./{name}", check=False)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _revs(text: str | None) -> set[str]:
    """The entries of a .git-blame-ignore-revs file, without comments and blank lines."""
    return {line.split("#", 1)[0].strip() for line in (text or "").splitlines()} - {""}


def base_rules(root: Path, base: str, head: Config) -> BaseRules:
    """The rules of the base branch BASE, and which protected settings HEAD's SIGNOFF.toml changes:
    [policy], [review], exclude, [history] and version (which decides the scale the AI review levels
    are read on), and the entries of .git-blame-ignore-revs (or [history] ignore-revs-file), which
    give lines back to other commits. A repository's first SIGNOFF.toml changes nothing."""
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
    ignore, ignored = head.history.ignore_revs_file or ".git-blame-ignore-revs", None
    if _revs(_show(root, base, ignore)) != _revs(_read(root / ignore)):
        # its entries give lines back to the commits before them: they steer resolution as [history] does
        ignored = ignore
    unconverted = []
    if config.version_3 != head.version_3:
        changed.append("version")
        # the change to version 4 rewrites the levels (examples/convert-to-version-4.py): an entry that
        # is still there must read as before, or the change would raise its AI review by itself
        from .history import _git

        def commit(rev: str) -> str:  # "3f1c9e0" and its full hash are the same entry
            return (_git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False) or rev).strip()
        for what, key in (("annotations", "paths"), ("commits", "commit"), ("attestations", "blob")):
            spell = commit if what == "commits" else (lambda v: v)
            before = {spell(getattr(e, key)): e.values.get(AIR) for e in getattr(config, what)}
            for e in getattr(head, what):
                was = before.get(spell(getattr(e, key)))
                now = e.values.get(AIR)
                if was and now and was != now:
                    name = ", ".join(e.paths) if what == "annotations" else getattr(e, key)[:12]
                    unconverted.append(f"{FILENAME} changes to version {4 if config.version_3 else 3} without converting "
                                       f"its levels: the entry for {name} read {AIR} {was} before and reads {now} now. "
                                       "Convert the file with examples/convert-to-version-4.py, and raise levels "
                                       "in another change")
    return BaseRules(config, changed, unconverted, ignored)


_REPORT_LINK = re.compile(r"https?://[^\s,;()<>]+", re.I)
_REPORT_PATH = re.compile(r"[\w./@+-]*[\w@+-]\.[A-Za-z][\w]*|[\w.@+-]+(?:/[\w.@+-]+)+")
_REPORT_SUFFIXES = (".md", ".txt", ".pdf", ".rst", ".html", ".ipynb", ".tex", ".org", ".adoc")


def change_files(root: Path, base: str | None) -> set[str] | None:
    """The files a change adds or modifies since BASE (paths from the top of the repository): its
    commits, what isn't committed yet and new files that aren't ignored. None: no base is known."""
    from .history import _git
    if not base:
        return None
    changed = _git(root, "diff", "--name-only", "-z", "--no-renames", "--diff-filter=d", base, "--", check=False)
    if changed is None:
        return None
    new = _git(root, "ls-files", "--others", "--exclude-standard", "--full-name", "-z", check=False) or ""
    return {f for f in (changed + "\0" + new).split("\0") if f}


def _report_paths(root: Path, item: str) -> list[str]:
    """The paths an item of AI-Reviewed-by names: the whole item when it is a file ("reviews/pull
    7.md"), else its words that look like paths."""
    item = item.strip()
    if item and (root / item).is_file():
        return [item]
    return [m.group(0) for m in _REPORT_PATH.finditer(item)]


def review_problems(root: Path, piece, findings: str | None, recheck: str, changed: set[str] | None = None) -> list[str]:
    """The check before the merge of a pull request that declares A2 or A3 (PIECE, its AI review):
    the "AI-Review-Findings:" line FINDINGS, and that AI-Reviewed-by names the reviewing model and
    the review's report: a link, or a file inside the repository that the change adds or modifies
    (CHANGED, from change_files; None: any file of the repository). What the report says is never
    read: its form is the repository's business."""
    from .history import _git
    from .model import findings_problems
    level = piece.level if piece else None
    problems = findings_problems(level, findings, recheck, required=True)
    if level not in ("A2", "A3"):
        return problems
    items = [i.strip() for n in piece.names for i in n.split(",") if i.strip()]
    if items and (_REPORT_LINK.match(items[0]) or _report_paths(root, items[0]) == [items[0]]
                  and ("/" in items[0] or items[0].lower().endswith(_REPORT_SUFFIXES))):
        problems.append(f"{AI_REVIEWED} names the report, but not the reviewing model before it "
                        "(\"GPT Sol (OpenAI), reviews/pull12.md\")")
    if any(_REPORT_LINK.search(i) for i in items):
        return problems
    top = Path((_git(root, "rev-parse", "--show-toplevel", check=False) or str(root)).strip()).resolve()
    found, outside, old = False, None, None
    paths = [p for i in items for p in _report_paths(root, i)]
    for p in paths:
        full = (root / p).resolve()
        if not full.is_relative_to(top):
            outside = outside or p
            continue
        if not full.is_file():
            continue
        if changed is None or full.relative_to(top).as_posix() in changed:
            found = True
            break
        old = old or p
    if found:
        return problems
    if outside:
        return problems + [f"the review report {outside} is outside the repository: commit this review's report "
                           "with the pull request, or link it"]
    if old:
        return problems + [f"the review report {old} isn't part of this change: it was there before, so it is "
                           "an earlier review's. Commit this review's report with the pull request"]
    named = [p for p in paths if p.lower().endswith(_REPORT_SUFFIXES)]
    if named:
        return problems + [f"the review report {named[0]} isn't in this change: commit it with the pull request"]
    return problems + [f"{level} needs its review report in {AI_REVIEWED}: the path of a file in this change, or a "
                       "link (after the model: \"GPT Sol (OpenAI), reviews/pull12.md\")"]


def description_problems(pieces: dict, policy) -> list[str]:
    """What is missing from a pull request description, checked on its own: every axis with the names
    its level needs, the built-in rules and the policy, whether or not the change has lines to declare."""
    from .history import combine
    from .model import validate
    d = combine([pieces.get(i) for i in range(3)])
    if d.source == "none" and not d.problems:
        return ["it declares nothing: fill in the AI declaration of the template (or \"Key: value\" lines)"]
    return validate(d, policy)
