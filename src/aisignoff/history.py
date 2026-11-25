"""Line-level declarations from git history (the [history] table of SIGNOFF.toml).

Each line has one owner, and the owner declares it:

1. The owner is the commit that landed the line on the default branch
   ('git blame --first-parent'): a commit made there directly, a squash commit, or the merge
   commit of a pull request. Its message declares the levels with "Key: value" lines
   (AI-Generation, Human-Review, ...) or the ticked checkboxes of a pull request template; a
   [[commits]] entry corrects it. Commits and pull requests inside it declare nothing.
2. One exception, for generation only: inside a merge commit that declares its lines, the
   commit that wrote a line can say a higher AI-Generation for it (an agent's commit in a pull
   request declared G1). A lower one (a hand-written commit in an AI-written pull request)
   takes a [[commits]] entry for that commit.
3. A review is the higher of the owner's level (or the file level's, where that declares the
   line) and an [[attestations]] entry of the file whose content (a git blob) already contained
   the line.
4. An owner that declares nothing leaves its lines to the file-level declaration (the annotations of
   SIGNOFF.toml), or fails lint with undeclared = "error". One that declares some
   axes but not all, or leaves the template unfilled, is an error.

Lines that aren't on the default branch yet (a feature branch, a pull request's merge preview,
uncommitted changes) are the diff against it. They take the declaration given for the change
(the pull request description); without one they are shown with the generation their commits
say, and nothing about them fails. 'landed' (lint --landed, a merge queue's run) says that HEAD
is a commit of the default branch as it is.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from .globbing import matches
from .model import (AXES, FINDINGS, FINDINGS_REVIEWS, LEVEL_KEYS, LIST_KEYS, TODO, Declaration,
                    canonical_key, findings_problems, findings_value, from_version_3, mentions_self_check, valid_findings,
                    validate, worst_findings)

UNCOMMITTED = "0" * 40
REVERT = re.compile(r"^This reverts commit ([0-9a-f]{7,64})", re.M)
# GitHub's Revert button: the pull request's description, and the subject of its commits
REVERT_PR = re.compile(r"^Reverts ([\w.-]+/[\w.-]+#\d+)", re.M)
REVERT_SUBJECT = re.compile(r'^Revert "')
# the subject GitHub gives a pull request's merge commit, and (by default) its squash commit
PULL_REQUEST = re.compile(r"^Merge pull request #\d+ |\(#\d+\)$")
QUEUE_REF = "refs/heads/gh-readonly-queue/"  # GITHUB_REF of a merge queue's run: HEAD is what will land
BINARY_PROBE = 16384


class HistoryError(Exception):
    pass


# git with the settings that change what aisignoff reads pinned to git's defaults, so that a
# personal or system config (another diff algorithm, other output formats; for an ignore-revs
# file of one's own, see _blame) can't make one machine work out other levels than another
GIT = ["git", "-c", "blame.markIgnoredLines=false",
       "-c", "blame.markUnblamableLines=false", "-c", "diff.algorithm=myers", "-c", "diff.renames=true",
       "-c", "diff.noprefix=false", "-c", "diff.mnemonicPrefix=false", "-c", "diff.relative=false",
       "-c", "diff.external=", "-c", "core.quotePath=true", "-c", "log.showSignature=false", "-c", "color.ui=false",
       "-c", "diff.indentHeuristic=true", "-c", "diff.interHunkContext=0"]

# the oldest git that aisignoff runs with: older ones lack options it needs (--diff-merges, --path-format)
# and would read some of the history wrong without saying so. 2.34 is Ubuntu 22.04's git.
MIN_GIT = (2, 34)
_git_version_cache: list = []


def git_version() -> tuple[int, ...] | None:
    """The version of git, as (major, minor, patch); None if git isn't installed or can't say."""
    if not _git_version_cache:
        try:
            out = subprocess.run(["git", "--version"], capture_output=True, text=True, env=git_env()).stdout
        except FileNotFoundError:
            out = ""
        m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", out)
        _git_version_cache.append(tuple(int(g or 0) for g in m.groups()) if m else None)
    return _git_version_cache[0]


def check_git() -> None:
    """Stop (a configuration error) when git is missing or older than MIN_GIT."""
    version = git_version()
    if version is None:
        raise HistoryError("git is not installed (or 'git --version' says no version)")
    if version[:2] < MIN_GIT:
        raise HistoryError(f"git {'.'.join(map(str, version))} is too old: aisignoff needs git "
                           f"{'.'.join(map(str, MIN_GIT))} or later to read the history")


def comparable(declaration: dict) -> str:
    """A declaration's levels and names as text to compare: not its source, which only says
    where they came from, in words that may change between versions."""
    return json.dumps({k: v for k, v in declaration.items() if k != "source"}, sort_keys=True, ensure_ascii=False)


def git_env() -> dict[str, str]:
    """The environment for git: English messages, since a few of them are read (ambiguous hashes)."""
    # GIT_NO_REPLACE_OBJECTS: refs/replace/ are local to a clone, so they'd make one machine see another history
    # GIT_DIFF_OPTS would replace --unified=0, whose hunks are read as the changed lines
    env = {k: v for k, v in os.environ.items() if k != "GIT_DIFF_OPTS"}
    return {**env, "LC_ALL": "C", "LANGUAGE": "", "GIT_NO_REPLACE_OBJECTS": "1"}


def _event_default_branch() -> list[str]:
    """The repository's default branch as GitHub Actions' event names it, if it does."""
    name = os.environ.get("GITHUB_EVENT_PATH")
    if not name:
        return []
    try:
        with open(name, encoding="utf-8") as f:
            branch = (json.load(f).get("repository") or {}).get("default_branch")
    except (OSError, ValueError, AttributeError):
        return []
    return [branch] if isinstance(branch, str) and branch else []


def _git(root: Path, *args: str, check: bool = True, stdin: bytes | None = None) -> str | None:
    try:
        r = subprocess.run([*GIT, "-C", str(root), *args], env=git_env(), capture_output=True, input=stdin)
    except FileNotFoundError:
        raise HistoryError("git is not installed")
    if r.returncode != 0:
        if check:
            raise HistoryError(f"git {args[0]} failed: {r.stderr.decode('utf-8', 'replace').strip()}")
        return None
    return r.stdout.decode("utf-8", "surrogateescape")


def _git_bytes(root: Path, *args: str, stdin: bytes | None = None) -> bytes | None:
    """git's output as bytes (a blob's content); None if it fails."""
    try:
        r = subprocess.run([*GIT, "-C", str(root), *args], env=git_env(), capture_output=True, input=stdin)
    except FileNotFoundError:
        raise HistoryError("git is not installed")
    return r.stdout if r.returncode == 0 else None


def _git_error(root: Path, *args: str) -> str:
    try:
        r = subprocess.run([*GIT, "-C", str(root), *args], env=git_env(), capture_output=True)
    except FileNotFoundError:
        return ""
    return r.stderr.decode("utf-8", "replace") if r.returncode else ""


def present(root: Path, path: str) -> bool:
    """Whether the work tree has this file as git tracks it: a file, or a symlink, which git keeps
    as its target text whether or not the target exists (never follow it)."""
    full = root / path
    return full.is_symlink() or full.is_file()


def hash_file(root: Path, path: str) -> str | None:
    """The blob git would store for the work tree's file: for a symlink, the blob of its target
    text, as git stores it (hash-object would read what it points to, or fail when that's missing)."""
    full = root / path
    if full.is_symlink():
        try:
            target = os.fsencode(os.readlink(full))
        except OSError:
            return None
        out = _git(root, "hash-object", "-t", "blob", "--stdin", check=False, stdin=target)
    else:
        out = _git(root, "hash-object", "--", path, check=False)
    return out.strip() or None if out else None


def unavailable_reason(root: Path) -> str | None:
    """Why history can't be used here (None if it can)."""
    inside = _git(root, "rev-parse", "--is-inside-work-tree", check=False)
    if inside is None or inside.strip() != "true":
        return "not a git work tree"
    if (_git(root, "rev-parse", "--is-shallow-repository", check=False) or "").strip() == "true":
        return "shallow clone (check out with fetch-depth: 0)"
    return None


@dataclass(frozen=True)
class Piece:
    """One axis of a declaration (its level and names) and where it comes from."""

    level: str | None
    names: tuple[str, ...]
    source: str
    kind: str  # commit | branch | attestation | file | declared | required
    problems: tuple[str, ...] = ()
    # the AI review axis only: its AI-Review-Findings value ("none", "minor", ...), None: none given
    findings: str | None = None


@dataclass
class Part:
    """The lines of a file that share one combined declaration."""

    declaration: Declaration
    errors: list[str]
    lines: int
    runs: list[list[int]]  # [first, last] line numbers, 1-based and inclusive
    kinds: tuple[str | None, ...]  # per axis: where its level comes from (None: nowhere)
    # lines that aren't on the default branch yet and have no declaration for the change: shown,
    # but their errors fail nothing
    advisory: bool = False


def short(sha: str) -> str:
    return sha[:7]


def pieces_from_values(values: dict, source: str, kind: str) -> dict[int, Piece]:
    """Axis index -> Piece for the axes whose level is given (names travel with their level)."""
    out = {}
    for i, (level, names) in enumerate(AXES):
        if values.get(level) is not None:
            v = values.get(names) or ()
            out[i] = Piece(values[level], tuple([v] if isinstance(v, str) else v), source, kind)
    findings = values.get(FINDINGS)
    if 2 in out and isinstance(findings, str) and valid_findings(findings):
        out[2] = replace(out[2], findings=findings_value(findings))
    return out


_FENCE = re.compile(r"^\s*(```+|~~~+)")
_KEY_LINE = re.compile(r"^([A-Za-z][A-Za-z-]*):[ \t]*(.*?)\s*$")


_CODE_SPAN = re.compile(r"(`+)(?!`).*?(?<!`)\1(?!`)")


def _prose_lines(text: str) -> list[str]:
    """The lines of a message outside fenced code blocks and HTML comments: a template or an
    example quoted in a message declares nothing. A backtick line whose info string has a
    backtick (inline code at the start of a line) opens no block, as in CommonMark, and a
    `<!--` inside inline code opens no comment. A block or comment that is never closed isn't
    one: its opening line counts as text, the blocks before it stay blocks (so a stray fence
    or comment can neither hide the declaration after it nor make a quoted example count)."""
    plain: set[int] = set()  # openers that are never closed
    while True:
        out, opener = _prose_pass(text.splitlines(), plain)
        if opener is None:
            return out
        plain.add(opener)


def _prose_pass(lines: list[str], plain: set[int]) -> tuple[list[str], int | None]:
    out, fence, comment, opened = [], None, False, None
    for n, line in enumerate(lines):
        if comment:
            if "-->" not in line:
                continue
            comment, line = False, line.split("-->", 1)[1]
        m = _FENCE.match(line) if n not in plain else None
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip()[len(m.group(1)):]:
                fence = None
            continue
        if m and not (m.group(1)[0] == "`" and "`" in line.strip()[len(m.group(1)):]):
            fence, opened = m.group(1), n
            continue
        if n not in plain:
            rest = _CODE_SPAN.sub(lambda c: "\0" * len(c.group(0)), line)  # code spans hold no comment
            while "<!--" in rest:  # a comment, also one opened mid-line
                i = rest.index("<!--")
                j = rest.find("-->", i + 4)
                if j >= 0:
                    line, rest = line[:i] + line[j + 3:], rest[:i] + rest[j + 3:]
                else:
                    line, rest, comment, opened = line[:i], rest[:i], True, n
        out.append(line)
    return out, opened if (fence or comment) else None


def parse_trailers(text: str, source: str) -> dict[int, Piece]:
    """Axis pieces from 'Key: value' lines (AI-Generation: G2, Reviewed-by: ...) anywhere in a
    message body, outside code blocks. Not only git's trailer paragraph: a Co-authored-by
    paragraph after it, or GitHub's squash co-author block, would hide that silently. Names
    without their level are ignored (Reviewed-by is a common trailer on its own); conflicting
    levels are a problem."""
    levels: dict[str, str] = {}
    names: dict[str, list[str]] = {k: [] for k in LIST_KEYS}
    problems = []
    blank = []
    for line in _prose_lines(text):
        m = _KEY_LINE.match(line)
        if not m:
            continue
        key, v = canonical_key(m.group(1)), m.group(2)
        if key in LEVEL_KEYS and not v:
            blank.append(key)  # "Human-Review:" left empty: a template that wasn't filled in
        if key is None or not v:
            continue
        if key in LEVEL_KEYS:
            if key in levels and levels[key] != v:
                problems.append(f"{source} has conflicting {key} trailers ({levels[key]}, {v})")
            levels[key] = v
        elif v not in names[key]:
            names[key].append(v)
    for key in blank:
        levels.setdefault(key, TODO)
    return {i: Piece(levels[level], tuple(names[n]), source, "commit", tuple(problems))
            for i, (level, n) in enumerate(AXES) if level in levels}


_BOX = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.*)$")
_BOX_LEVEL = re.compile(r"^\*\*([GHA][0-3])\*\*")
_BOX_MODEL = re.compile(r"^\*\*([^*:]+)\*\*\s*(\([^()]*\))?$")
_BOX_OTHER = re.compile(r"^\*\*Other:\*\*\s*(.*)$")


def _boxes(text: str) -> list[tuple[bool, str]]:
    """The checkbox items of a Markdown text: (ticked, text), with wrapped lines joined."""
    items: list[list] = []
    joinable = False
    for line in _prose_lines(text):
        m = _BOX.match(line)
        if m:
            items.append([m.group(1) != " ", m.group(2).strip()])
            joinable = True
        elif joinable and line.strip() and not line.lstrip().startswith(("#", "-", "*", ">")):
            items[-1][1] += " " + line.strip()
        else:
            joinable = False
    return [(t, x) for t, x in items]


_OLD_A1_BOX = re.compile(r"its own work|self[- ]?check", re.I)


def _own_text(item: str) -> str:
    """A box's text as the template wrote it: without what was filled in after "Model ...:"."""
    return re.split(r"\bModel\b", item, maxsplit=1)[0]


def old_template(text: str) -> bool | None:
    """Whether the AI review boxes of a pull request template are of the scale before SIGNOFF.toml
    version 4: its A1 box was the self-check of the generating session. None: there is no A1 box."""
    for _, item in _boxes(text):
        if item.startswith("**A1**"):
            return mentions_self_check(_own_text(item), _OLD_A1_BOX)
    return None


_FINDINGS_LINE = re.compile(rf"^\s*(?:[-*+]\s+)?[*_]*{FINDINGS}[*_]*\s*:[*_]*[ \t]*(.*?)\s*$", re.I)


# a line meant as the findings line, misspelt: "AI-Review-Finding:", "AI Review Findings:", "AIReviewFindings:"
_FINDINGS_TYPO = re.compile(r"^\W*ai[\W_]*review[\W_]*finding\w*\W*:", re.I)


def findings_line(text: str) -> str | None:
    """The value of the "AI-Review-Findings:" line of a message ("" if it is left empty), outside
    code blocks and comments; with several lines, the most severe value (an invalid one first, so
    that it is reported), and a line left empty only when no other is filled in. The key may be in
    bold, as a template is often filled in. None: the message has no such line."""
    values = []
    for line in _prose_lines(text):
        m = _FINDINGS_LINE.match(line)
        if m:
            values.append(m.group(1).strip().strip("*_`").strip())
    return worst_findings(values) if values else None


def parse_checkboxes(text: str, author: str, source: str, version_3: bool = False) -> dict[int, Piece]:
    """Axis pieces from the ticked checkboxes of a pull request template in a commit message
    (a squash commit with the default message "Pull request title and description"):

        - [x] **G3** AI-autonomous: ...           the generation level (one)
        - [x] **Claude Opus** (Anthropic)         a model that wrote parts of it
        - [ ] **Other:** Some model               another one, if filled in
        - [x] **H1** I ran the tests ...          the highest ticked human review level
        - [x] **A2** A new AI session ... Model: X  the highest ticked AI review level

    The human review is the commit author's; the AI review names the model after "Model:", and
    for A1 otherwise the models that wrote the change (a new session of them). As in the template,
    no ticked AI review box means A0. version_3: the boxes are of the template before SIGNOFF.toml
    version 4 (parse_message takes its AI review over to today's scale); without it, a ticked A1
    box that says self-check is that old template, and a problem.
    Models count only between the generation and the human review boxes, and boxes in code
    blocks not at all. Generation or human review boxes that are there with none ticked are a
    template that wasn't filled in: TODO. Nothing is returned without any level box."""
    levels: dict[str, list[str]] = {"G": [], "H": [], "A": []}
    seen: set[str] = set()
    models: list[str] = []
    reviewer: dict[str, str] = {}
    old_box = False
    for ticked, item in _boxes(text):
        level = _BOX_LEVEL.match(item)
        if level:
            code = level.group(1)
            seen.add(code[0])
            if ticked:
                levels[code[0]].append(code)
                old_box = old_box or (code == "A1" and mentions_self_check(_own_text(item), _OLD_A1_BOX))
            if ticked and code[0] == "A" and "Model" in item:
                name = re.split(r"Model[^:]*:", item, maxsplit=1)[-1].strip()
                if name:
                    reviewer[code] = name
            continue
        if not ticked or "G" not in seen or "H" in seen:  # models are listed after the generation levels
            continue
        other = _BOX_OTHER.match(item)
        if other:
            if other.group(1).strip():
                models.append(other.group(1).strip())
            continue
        model = _BOX_MODEL.match(item)
        if model:
            models.append(model.group(1).strip() + (f" {model.group(2)}" if model.group(2) else ""))
    if not seen:
        return {}
    problems = []
    if len(levels["G"]) > 1:
        problems.append(f"{source} ticks more than one generation level ({', '.join(levels['G'])})")
    if old_box and not version_3:
        problems.append(f"{source} ticks an A1 box of the template before version 4 (the self-check of the "
                        "generating session, which is no AI-Review now: A0). Use the current template; for a "
                        "commit that has landed, say what was meant with a [[commits]] entry")
    out = {}
    names = {"G": tuple(models), "H": (author,) if author else ()}
    if "A" in seen and not levels["A"]:
        levels["A"] = ["A0"]  # "leave all unticked for A0"
    for letter in "GH":
        if letter in seen and not levels[letter]:
            levels[letter] = [TODO]
    for i, (letter, _) in enumerate(zip("GHA", AXES)):
        if not levels[letter]:
            continue
        top = max(levels[letter])
        if top == TODO:
            out[i] = Piece(TODO, (), f"{source}, pull request checkboxes", "commit", tuple(problems))
            continue
        if letter == "A":
            if top in reviewer:
                found = (reviewer[top],)
            elif version_3 and top == "A1":
                found = tuple(f"{m}, self-check by the generating session" for m in models)
            elif top == ("A2" if version_3 else "A1"):
                found = tuple(f"{m}, new session without the generating conversation" for m in models)
            else:  # A0, or a review by a different model without its name
                found = ()
        else:
            found = names[letter]
        out[i] = Piece(top, found, f"{source}, pull request checkboxes", "commit", tuple(problems))
    return out


def parse_message(body: str, author: str, source: str, version_3: bool = False,
                  landed: bool = False) -> tuple[dict[int, Piece], str | None]:
    """The declaration in a commit message body or a pull request description: its "Key: value"
    lines, or the ticked checkboxes of a pull request template. One or the other: with both, both
    count (the lines where they overlap) and the second value is the problem to report.
    version_3: the repository's SIGNOFF.toml says version 3, so the AI review is of the scale
    before version 4 and is taken over to today's; ticked boxes of today's template (its A1 box is
    no self-check) are read on today's scale all the same, so that a repository can take the new
    template before it changes over. landed: the message is of a commit of the default branch, which
    can't be changed any more: ticked boxes of the template before version 4 (its A1 box is the
    self-check) are read on that scale too, as what they meant then; elsewhere they are a problem
    (use the current template). The "AI-Review-Findings:" line is the caller's to check
    (findings_line)."""
    from_trailers = parse_trailers(body, source)
    old = old_template(body)
    old_boxes = (version_3 and old is not False) or (landed and old is True)
    from_boxes = parse_checkboxes(body, author.strip(), source, old_boxes)
    both = None
    if from_trailers and from_boxes:
        both = (f"{source} declares levels both as trailers and as ticked checkboxes; "
                "use one of them, or settle it with a [[commits]] entry")
    pieces = {**from_boxes, **from_trailers}
    if 2 in pieces and (old_boxes if 2 not in from_trailers else version_3):
        level, names = from_version_3(pieces[2].level, pieces[2].names)
        pieces[2] = replace(pieces[2], level=level, names=names)
    return pieces, both


_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _records(out: str) -> list[tuple[str, str, str, str, str]]:
    """(hash, parents, subject, author, message) of each commit in 'git log --format=FORMAT' output."""
    fields = out.split("\0")
    records = []
    for i in range(0, len(fields) - 4, 5):
        sha = fields[i].strip()
        if not _SHA.match(sha):
            raise HistoryError(f"unexpected git log output near {sha[:20]!r}")
        records.append((sha, fields[i + 1], fields[i + 2], fields[i + 3].strip(), fields[i + 4]))
    return records


def combine(pieces) -> Declaration:
    """A Declaration from one piece (or None) per axis."""
    values, sources, problems = {}, [], []
    for (level, names), p in zip(AXES, pieces):
        if p is None:
            continue
        for x in p.problems:
            if x not in problems:
                problems.append(x)
        if p.level is None:
            continue
        values[level], values[names] = p.level, list(p.names)
        if p.source not in sources:
            sources.append(p.source)
    if len(pieces) > 2 and pieces[2] is not None and pieces[2].level is not None and pieces[2].findings:
        values[FINDINGS] = pieces[2].findings
    if not values and not problems:
        return Declaration()
    d = Declaration.from_mapping(values, " + ".join(sources) or "history")
    d.problems = problems
    return d


def format_runs(runs: list[list[int]], limit: int = 3) -> str:
    text = ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs[:limit])
    more = "" if len(runs) <= limit else f" and {len(runs) - limit} more range(s)"
    return ("line " if len(runs) == 1 and runs[0][0] == runs[0][1] else "lines ") + text + more


class History:
    """Resolves the declaration of each line of a project's files from git history."""

    def __init__(self, root: Path, config, declared: dict[int, Piece] | None = None, base: str | None = None,
                 landed: bool = False, cache=None):
        """declared: the declaration of the change that isn't on the default branch yet (the pull
        request description), None when there is none. base: the commit that change starts from,
        when the caller knows it (aisignoff diff BASE, lint --base). landed: HEAD is a commit of
        the default branch, or will be one as it is (a merge queue's commit, a release branch).
        cache: the BlameCache to read the origins of earlier runs from and record this run's in."""
        check_git()
        self.root = Path(root)
        self.config = config
        self.policy = config.policy
        self.problems: list[str] = []
        self.notes: list[str] = []  # for the reader, never a failure
        self._warnings: list[str] = []
        self.order: dict[str, int] = {}  # the default branch's first-parent commits: sha -> ordinal (1 = oldest)
        self.subjects: dict[str, str] = {}
        self.parents: dict[str, list[str]] = {}
        self._trailers: dict[str, dict[int, Piece]] = {}
        self._both: dict[str, str] = {}  # commits with trailers and checkboxes: the problem
        self._reverts: dict[str, str] = {}  # commit -> the commit its message says it reverts
        self._ancestor: dict[tuple[str, str], bool] = {}
        self._side_cache: dict[str, tuple[bool, int, str | None]] = {}
        self._noted: set[str] = set()
        self._silent: list[str] = []  # commits that look like pull requests, own lines and declare nothing
        self._renames: list[tuple[str, str]] | None = None
        self.head = self._resolve("HEAD")
        if self.head is None:
            # no commit yet (an unborn branch), or a HEAD whose commit git can't read: the latter must not
            # pass for a repository without history
            ref = (_git(self.root, "rev-parse", "--verify", "--quiet", "HEAD", check=False) or "").strip()
            if ref:
                raise HistoryError(f"HEAD is {ref}, but git can't read that commit: "
                                   f"{_git_error(self.root, 'cat-file', '-t', ref).strip() or 'missing or corrupt'}")
        self.prefix = (_git(self.root, "rev-parse", "--show-prefix", check=False) or "").strip()
        self.declared = declared
        self.landed = landed
        self._declared_given, self._base_given = declared is not None, base is not None
        self.remote_tip: str | None = None  # origin's default branch, if there is one
        # landed, on a branch of its own (a release branch): its first-parent commits since the
        # default branch land its lines; what it has of the default branch is resolved as there
        self.release = False
        if not landed and os.environ.get("GITHUB_REF", "").startswith(QUEUE_REF):
            self.landed = True
            self.notes.append("this is a merge queue's run: HEAD is checked as the commit that lands on the "
                              "default branch")
        # the newest commit of the default branch that HEAD contains: what is landed
        self.base = self._find_base(base)
        self._load_chain()
        self.newest = len(self.order) + 1  # content that no commit of the default branch has yet
        # the commits of HEAD that aren't on the default branch yet
        self.pending: set[str] = set()
        if self.head and self.head != self.base:
            self.pending = set((_git(self.root, "rev-list", self.head, f"^{self.base}", check=False) or "").split())
        # with release: the first-parent commits of HEAD since the default branch, oldest = 1
        self.branch_order: dict[str, int] = {}
        if self.release and self.pending:
            chain = (_git(self.root, "rev-list", "--first-parent", self.head, f"^{self.base}", check=False) or "").split()
            self.branch_order = {sha: len(chain) - i for i, sha in enumerate(chain)}
        head_parents = (_git(self.root, "rev-parse", f"{self.head}^@", check=False) or "").split() if self.head else []
        # HEAD merges the change into the default branch: the merge preview of a pull request's CI run
        self.preview = self.head in self.pending and len(head_parents) == 2 and head_parents[0] == self.base
        self.head_files = self._tree("HEAD") if self.head else {}
        self.base_blobs = self._tree(self.base) if self.base else {}
        self.changes = self._load_changes()
        self.corrections = self._load_corrections()
        self._check_entries()
        self.since = self._ordinal_of_setting(config.history.require_trailers_since)
        self.blame_options = (["-w"] if config.history.ignore_whitespace else []) + ["--root"] + self._ignore_revs()
        self.cache = cache.open(self) if cache is not None and self.base else None
        self.converted = self._converted()  # before the files are resolved, which runs in threads
        self.gone: list = []  # attestations of files deleted since: they cover no line
        self.attestation_keys: list[tuple] = []  # (attestation, the file it is listed under, its tuple)
        self.origins: dict[str, set[tuple]] = {}  # the different origins of the lines of each file resolved
        self._ages: dict[tuple, float] = {}  # see _scoped_age
        self._blob_logs: dict[str, str] = {}  # see _blob_until
        self._excluded_touch: dict[str, bool] = {}  # see _may_cover_excluded
        self.attestations = self._load_attestations()
        self._check_signoff_commits()

    # ------------------------------------------------------------ the default branch
    def _default_tip(self) -> str | None:
        """The tip of the default branch: HEAD when it is checked out, else origin's (or the local
        one, when that is ahead of it or the only one)."""
        name = self.config.history.default_branch
        if name:
            names = [name]
        else:
            remote = (_git(self.root, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD", check=False) or "").strip()
            # actions/checkout sets no origin/HEAD: GitHub's event names the default branch
            names = ([remote.split("/", 1)[1]] if "/" in remote else []) + _event_default_branch() + ["main", "master"]
        current = (_git(self.root, "symbolic-ref", "--short", "-q", "HEAD", check=False) or "").strip()
        if current and current in names:
            self.remote_tip = self._resolve(f"refs/remotes/origin/{current}")
            return self.head
        # a pull request's run must know what has landed; so must --landed
        needed = bool(name) or self.landed or self._declared_given or self._base_given
        if self.landed:
            tip = self._branch_tip(names, report=needed)
            chain = set((_git(self.root, "rev-list", "--first-parent", self.head, check=False) or "").split())
            if tip is None or tip in chain or self.is_ancestor(self.head, tip):
                # a merge queue's commit (on top of the default branch, as it lands), or one of its commits
                return self.head
            self.release = True  # a branch of its own, which may have merged the default branch
            return tip
        return self._branch_tip(names, report=needed)

    def _branch_tip(self, names: list[str], report: bool = False) -> str | None:
        for n in names:
            remote, local = self._resolve(f"refs/remotes/origin/{n}"), self._resolve(f"refs/heads/{n}")
            if remote:
                self.remote_tip = remote
            if remote and local and self.is_ancestor(remote, local):
                return local  # commits that aren't pushed yet
            if remote or local:
                return remote or local
        if report:
            name = names[0]
            if self.config.history.default_branch:
                # a setting that names nothing: the configuration is wrong, whatever the command
                raise HistoryError(f"[history] default-branch: there is no branch {name} here (neither "
                                   f"origin/{name} nor {name}); fetch it (in CI: fetch-depth: 0), or correct the setting")
            else:
                self.problems.append("there is no default branch here (none of " + ", ".join(names) + " as origin/<name> "
                                     "or a local branch), so every commit of HEAD counts as landed and nothing is "
                                     "checked as the change. Set default-branch in [history] of SIGNOFF.toml, and "
                                     "fetch it in CI (fetch-depth: 0)")
        return None

    def _find_base(self, base: str | None) -> str | None:
        if self.head is None:
            return None
        tip = self._default_tip()
        landed = self.head
        if tip and tip != self.head:
            # the commits of the default branch that HEAD doesn't have, newest first: the one below them is it
            ahead = (_git(self.root, "rev-list", "--first-parent", tip, f"^{self.head}", check=False) or "").split()
            landed = (self._resolve(ahead[-1] + "^") if ahead else tip) or self.head
        if base is None or self.declared is None:
            return landed
        start = self._resolve(base)
        if start is None or not self.is_ancestor(start, self.head):
            self.problems.append(f"--declare: {short(base)} is not in the history of HEAD, so it's unclear which "
                                 "lines are new; the declaration was not applied")
            self.declared = None
            return landed
        if start != landed and self.is_ancestor(landed, start):
            # the change goes into a branch that isn't the default branch: a pull request into a pull request
            self.notes.append("this change doesn't go into the default branch: only the pull request that lands "
                              "its lines there declares them, so the declaration given for it was not applied")
            self.declared = None
            return landed
        if start != landed and self.is_ancestor(start, landed):
            # a stale base: the commits between it and what HEAD has of the default branch are that branch's own
            return landed
        return start

    def _tree(self, rev: str) -> dict[str, str]:
        """path (relative to root) -> blob of the files of a commit."""
        out = _git(self.root, "ls-tree", "-r", "-z", rev, check=False) or ""
        tree = {}
        for row in out.split("\0"):
            meta, _, name = row.partition("\t")
            if name:
                tree[name] = meta.split()[2]
        return tree

    def _load_changes(self) -> dict[str, tuple[str | None, list[int], list[int]]]:
        """path -> (its path on the default branch, the lines removed there, the lines added here)
        for the files that differ from the default branch: the change that hasn't landed."""
        if self.base is None:
            return {}
        from .diff import DiffError, changed_lines
        try:
            found = changed_lines(self.root, self.base, self.config.history.ignore_whitespace)
        except DiffError as e:
            raise HistoryError(str(e))
        return {new: (old, removed, added) for (old, new), (removed, added) in found.items() if new}

    # ------------------------------------------------------------ commits
    def _load_chain(self) -> None:
        if self.base is None:  # no commit yet
            return
        records = _records(_git(self.root, "log", "--first-parent", f"--format={self.FORMAT}", self.base))
        for i, record in enumerate(records):
            self.order[record[0]] = len(records) - i
            self._remember(*record)

    # hash, parents, subject, author and message, each ended by NUL, which a commit message can't
    # contain (unlike any other separator, so a message can't pass for another commit's record)
    FORMAT = "%H%x00%P%x00%s%x00%an <%ae>%x00%B%x00"

    def _remember(self, sha: str, parents: str, subject: str, author: str, message: str) -> None:
        """A commit's own declaration (its message, the subject line aside) and what else is needed of it."""
        self.subjects[sha] = subject.strip()
        self.parents[sha] = parents.split()
        body = message.split("\n", 1)[1] if "\n" in message else ""
        # an old template's boxes in a commit that has landed are read as they were meant then
        landed = sha in self.order or bool(self.base and old_template(body) and self.is_ancestor(sha, self.base))
        self._trailers[sha], both = parse_message(body, author, self.describe(sha), self.config.version_3, landed)
        ai = self._trailers[sha].get(2)
        if ai is not None and ai.level in FINDINGS_REVIEWS and not self.config.version_3:
            # the findings of the review travel with the AI review: they become the findings level of
            # the lines this commit lands (a commit without them leaves its lines at F-)
            value = findings_line(body)
            if value and valid_findings(value):
                self._trailers[sha][2] = replace(ai, findings=findings_value(value))
            elif value:
                self._trailers[sha][2] = replace(ai, problems=ai.problems + tuple(
                    f"{self.describe(sha)}: {w}" for w in findings_problems(ai.level, value)))
            elif value is None and sha in self.order:
                typo = next((line.strip() for line in _prose_lines(body) if _FINDINGS_TYPO.match(line)), None)
                if typo:
                    self._warnings.append(f"{self.describe(sha)} has a line {typo[:60]!r} that looks like "
                                          f"'{FINDINGS}:' but isn't, so it isn't read and its lines stay at F-; "
                                          "give the findings with a [[commits]] entry that restates its AI review")
        if both:
            self._both[sha] = both
        revert, pr = REVERT.search(body), REVERT_PR.search(body)
        if revert:
            self._reverts[sha] = short(revert.group(1))
        elif pr:
            self._reverts[sha] = pr.group(1)
        elif REVERT_SUBJECT.match(subject.strip()):
            self._reverts[sha] = "an earlier change"

    def describe(self, sha: str) -> str:
        subject = self.subjects.get(sha, "")
        if len(subject) > 48:
            subject = subject[:47] + "…"
        return f"commit {short(sha)}" + (f" ({subject})" if subject else "")

    def _resolve(self, rev: str) -> str | None:
        out = _git(self.root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False)
        return out.strip() if out else None

    def _load_corrections(self) -> dict[str, dict[int, Piece]]:
        out: dict[str, dict[int, Piece]] = {}
        for entry in self.config.commits:
            sha = self._resolve(entry.commit)
            where = f"{entry.filename} [[commits]] entry {entry.index}"
            if sha is None:
                err = _git_error(self.root, "rev-parse", "--verify", f"{entry.commit}^{{commit}}")
                what = "is ambiguous; give more digits" if "ambiguous" in err else "is not a commit of this repository"
                self.problems.append(f"{where}: {entry.commit} {what}")
                continue
            if sha not in self.order and not self.is_ancestor(sha, "HEAD"):
                self.problems.append(f"{where}: {entry.commit} is not in the history of HEAD (rebased or "
                                     "squashed away?), so it declares nothing")
                continue
            source = f"{entry.filename} [[commits]] {short(sha)}"
            pieces = pieces_from_values(entry.values, source, "commit")
            if sha not in self.order and sha not in self.pending and set(pieces) - {0}:
                self._warnings.append(f"{where}: {entry.commit} is a commit inside a pull request, so only its "
                                      "AI-Generation counts; reviews are declared by the commit that landed it "
                                      "on the default branch, or by an attestation")
            out.setdefault(sha, {}).update(pieces)
        return out

    def _check_entries(self) -> None:
        """Each [[commits]] entry of SIGNOFF.toml must be a valid declaration of its commit (the
        commit's message, corrected by the entry), under the built-in rules and the policy, also when
        the commit owns no line that is checked: a correction that breaks the rules isn't recorded
        quietly. An entry that leaves an axis undeclared is checked on the axes it has."""
        for entry in self.config.commits:
            sha = self._resolve(entry.commit)
            if sha is None or sha not in self.corrections:
                continue  # reported by _load_corrections
            d = combine([self.commit_pieces(sha).get(i) for i in range(3)])
            errors = [e for e in validate(d, self.policy) if not e.startswith("missing ")]
            for error in errors:
                self.problems.append(f"{entry.filename} [[commits]] entry {entry.index} ({entry.commit}): {error}")

    def _ignore_revs(self) -> list[str]:
        """--ignore-rev options from .git-blame-ignore-revs (or [history] ignore-revs-file).

        Each entry is resolved first: git blame stops at an entry it can't resolve (an
        abbreviated hash, a commit of other history), which must not pass for "not committed"."""
        self._ignored: list[tuple[str, str]] = []  # (sha, the file that lists it)
        name = self.config.history.ignore_revs_file
        if name is None:
            if not (self.root / ".git-blame-ignore-revs").is_file():
                return []
            name = ".git-blame-ignore-revs"
        try:
            text = (self.root / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            if self.config.history.ignore_revs_file is not None:  # a setting that names nothing
                raise HistoryError(f"[history] ignore-revs-file: {name} does not exist")
            return []
        options = []
        for line in text.splitlines():
            rev = line.split("#", 1)[0].strip()
            if not rev:
                continue
            sha = self._resolve(rev)
            if sha is None:
                self.problems.append(f"{name}: {rev} is not a commit of this repository; remove it, or give the full hash")
            else:
                options += ["--ignore-rev", sha]
                self._ignored.append((sha, name))
        return options

    def _ordinal_of_setting(self, rev: str | None) -> int | None:
        if rev is None:
            return None
        sha = self._resolve(rev)
        if sha is None or sha not in self.order:  # a setting that names nothing
            raise HistoryError(f"[history] require-trailers-since: {rev} is not a commit of the default branch")
        return self.order[sha]

    def commit_pieces(self, sha: str) -> dict[int, Piece]:
        """The declaration of a commit: its message, corrected axis by axis by [[commits]]."""
        if sha not in self._trailers:  # a commit that isn't on the default branch's first-parent chain
            out = _git(self.root, "log", "-1", f"--format={self.FORMAT}", sha, check=False) or ""
            self._remember(*(_records(out) or [(sha, "", "", "", "")])[0])
        pieces = dict(self._trailers[sha])
        if sha in self._both and sha not in self.corrections:
            pieces = {i: replace(p, problems=p.problems + (self._both[sha],)) for i, p in pieces.items()}
        pieces.update(self.corrections.get(sha, {}))
        return pieces

    def _side(self, merge: str) -> tuple[bool, int, str | None, list[tuple[str, str]]]:
        """Of the commits a merge commit brought in: whether one that isn't a merge says
        AI-Generation; how many of them look like they landed lines somewhere before (merges
        that declare something and commits that declare all three axes: pull requests that
        landed elsewhere first, as after a git pull); what one of them reverts, if any; and
        (commit, AI-Generation) of the merges among them that say one."""
        if merge not in self._side_cache:
            parents = self.parents.get(merge, [])
            says, declared, reverts, merges = False, 0, None, []
            if len(parents) > 1:
                for sha in self._brought_in(merge, parents[0]):
                    pieces = self.commit_pieces(sha)
                    reverts = reverts or self._reverts.get(sha)
                    if len(self.parents[sha]) > 1:
                        declared += bool(pieces)
                        if 0 in pieces and pieces[0].level:
                            merges.append((sha, pieces[0].level))
                    else:
                        says = says or 0 in pieces
                        declared += len(pieces) == len(AXES)
            self._side_cache[merge] = (says, declared, reverts, merges)
        return self._side_cache[merge]

    def _brought_in(self, merge: str, first: str) -> list[str]:
        """The commits a merge commit brought in (git log MERGE ^FIRST-PARENT, newest first), with
        their messages read. Which they are never changes, so the blame cache keeps the list; the
        messages of every listed commit are then read at once, the first time one is needed."""
        cache = self.cache
        shas = cache.side(merge) if cache is not None else None
        if shas is None:
            out = _git(self.root, "log", f"--format={self.FORMAT}", merge, f"^{first}", check=False) or ""
            shas = []
            for record in _records(out):
                if record[0] == merge:
                    continue
                if record[0] not in self._trailers:
                    self._remember(*record)
                shas.append(record[0])
            if cache is not None:
                cache.record_side(merge, shas)
            return shas
        if any(sha not in self._trailers for sha in shas):
            with cache.lock:
                wanted = [sha for sha in dict.fromkeys(cache.all_sides()) if sha not in self._trailers]
                if wanted:
                    out = _git(self.root, "log", "--no-walk=unsorted", "--stdin", f"--format={self.FORMAT}", check=False,
                               stdin="".join(f"{sha}\n" for sha in wanted).encode()) or ""
                    for record in _records(out):
                        if record[0] not in self._trailers:
                            self._remember(*record)
            if any(sha not in self._trailers for sha in shas):  # not all of them could be read: as without the cache
                cache.forget_side(merge)
                return self._brought_in(merge, first)
        return shas

    def is_ancestor(self, a: str, b: str) -> bool:
        if (a, b) not in self._ancestor:
            try:
                r = subprocess.run([*GIT, "-C", str(self.root), "merge-base", "--is-ancestor", a, b], env=git_env(),
                                   capture_output=True)
                self._ancestor[(a, b)] = r.returncode == 0
            except FileNotFoundError:
                raise HistoryError("git is not installed")
        return self._ancestor[(a, b)]

    def _hint(self, owner: str | None, writer: str | None) -> tuple[Piece | None, bool]:
        """The generation that the commit which wrote a line says for it (rule 3): only a commit
        that isn't a merge, and only a level. Also whether a [[commits]] entry says it: only then
        can it be lower than the owner's."""
        if not writer or writer == owner:
            return None, False
        pieces = self.commit_pieces(writer)
        if len(self.parents.get(writer, [])) > 1 or 0 not in pieces or _level_value(pieces[0].level) < 0:
            return None, False
        return replace(pieces[0], kind="branch"), 0 in self.corrections.get(writer, {})

    def _note_owner(self, sha: str, declares: bool, required: bool) -> None:
        """Warnings about a commit that owns lines without declaring them, where that is easy to miss."""
        if sha in self._noted:
            return
        self._noted.add(sha)
        owner = self.commit_pieces(sha) if declares else {}
        if 0 in owner and len(self.parents.get(sha, [])) > 1:
            # a pull request merged into this one said more AI than this one's description does
            higher = [(m, level) for m, level in self._side(sha)[3]
                      if _level_value(level) > _level_value(owner[0].level)]
            if higher:
                m, level = max(higher, key=lambda t: _level_value(t[1]))
                self._warnings.append(f"{self.describe(sha)} declares {owner[0].level}, but {self.describe(m)} "
                                      f"inside it declares {level}: the lines of both take {owner[0].level}. Declare "
                                      "the highest generation of what lands in the pull request's description, or "
                                      f'correct it with [[commits]] commit = "{sha[:12]}"')
        if declares or required:
            return
        merge = len(self.parents.get(sha, [])) > 1
        reverts = self._reverts.get(sha) or (self._side(sha)[2] if merge else None)
        if reverts:
            self._warnings.append(f"{self.describe(sha)} reverts {reverts} and declares nothing: the "
                                  "lines it restored take the file-level declaration. Declare it with the levels of "
                                  f'what it restored: [[commits]] commit = "{sha[:12]}"')
        elif PULL_REQUEST.search(self.subjects.get(sha, "")):
            self._silent.append(sha)
        elif merge and self._side(sha)[1]:
            self._warnings.append(f"{self.describe(sha)} is a merge that declares nothing, with {self._side(sha)[1]} "
                                  "commit(s) inside it that declare their levels (pull requests that a git pull "
                                  "brought in?): what is inside doesn't count, so its lines take the file-level "
                                  f'declaration. Declare it with [[commits]] commit = "{sha[:12]}"')

    def warnings(self) -> list[str]:
        """What lint shows without failing (lint --strict fails on them)."""
        out = list(dict.fromkeys(self._warnings))
        for sha, name in self._ignored:
            # the file is for reformatting: a commit that declares levels gives its lines back to
            # the commits before it, which is a quiet way to lower them
            declares = bool(self.commit_pieces(sha))
            parents = (_git(self.root, "rev-list", "--parents", "-n", "1", sha, check=False) or "").split()[1:]
            why = ("declares levels" if declares else "is a merge" if len(parents) > 1
                   else "looks like a pull request" if PULL_REQUEST.search(self.subjects.get(sha, "")) else None)
            if why:
                out.append(f"{name} lists {self.describe(sha)}, which {why}: blame gives the lines it changed to the "
                           "commits before it, with their levels. List only commits that reformat")
        # commits up to require-trailers-since are accepted as they are
        silent = [sha for sha in set(self._silent) if self.since is None or self.order.get(sha, 0) > self.since]
        if silent:
            silent = sorted(silent, key=lambda sha: -self.order.get(sha, 0))
            more = f" and {len(silent) - 2} more" if len(silent) > 2 else ""
            out.append(f"{len(silent)} commit(s) that look like pull requests declare nothing: "
                       f"{', '.join(self.describe(s) for s in silent[:2])}{more}. Their lines take the file-level "
                       "declaration. Declare them with [[commits]] entries, or accept them as they are with [history] "
                       "require-trailers-since = \"<a later commit>\", which requires a declaration from the commits "
                       "after it")
        return out

    # ------------------------------------------------------------ attestations
    def _load_attestations(self) -> dict[str | None, list[tuple]]:
        """Per file: (until, commit, pieces, blob, age, scope, seq, recorded) of each attestation (age: see
        _content_age). 'until' is the ordinal of the last commit of the default branch at which the
        file still was the checked content (newest: it is the file as it is now). The commit is set
        instead when no commit of the default branch had that content, only a merged branch or the
        change that hasn't landed (a pull request whose file the default branch changed meanwhile):
        then the attestation covers the lines whose commit the checked content contained.
        scope: for an attestation of a commit, the commit (its full hash): it covers the lines that
        commit landed on the default branch and that are still there, as they are now. Those without
        a path are listed under None: they cover the lines of every file.
        recorded: the commit of the default branch that recorded it (None: it hasn't landed yet).
        The order (seq) is the order they were recorded in: by the commit of the default branch that
        added the entry to SIGNOFF.toml or the record file to the review folder, whichever file it is
        in, those that haven't landed last. Of two reviews of the same content, the later one counts."""
        out: dict[str | None, list] = {}
        entries = self._recorded_order(list(self.config.attestations), self.config.review_attestations)
        for seq, (a, recorded, pending) in enumerate(entries):
            where = f"{a.filename} [[attestations]] entry {a.index}"
            if a in self.config.review_attestations:
                self._review_record(a, where, pending)
            elif pending:
                self._signoff_review(a, where)
            got = self._attestation(a, where, seq, self.problems, self._warnings)
            if got == "gone":
                self.gone.append(a)
            elif got is not None:
                path, t = got
                if recorded is None and not pending:
                    # landed, but the commit that recorded it can't be told (SIGNOFF.toml entries that
                    # aren't [[attestations]] tables): it was recorded at the commit it reviews or later
                    recorded = t[5]
                if t[5] is None and recorded is not None and path is not None:
                    # a review of the whole file: how new its content was when the review was recorded
                    t = t[:4] + (self._content_age(*self._blob_until(set(self._names_since(path)), path, t[3],
                                                                      at=self.order.get(recorded))),) + t[5:]
                got = (path, t + (recorded,))
                self.attestation_keys.append((a, got[0], got[1]))
                if got[1][2]:
                    out.setdefault(got[0], []).append(got[1])
        return out

    def _attestation(self, a, where: str, seq: int, problems: list, warnings: list):
        """(the file it is listed under, the tuple of _load_attestations) of one attestation, "gone"
        when the file it names was deleted (it covers no line any more, which is no error), or None
        when it is wrong, which is added to problems."""
        if a.commit:
            return self._scoped(a, where, seq, problems, warnings)
        names = self._names_since(a.path)  # the attested file's names, the current one last
        path = names[-1]
        moves = [(old, new) for old, new in self.renames() if a.path in (old, new)]
        if present(self.root, a.path) and moves and moves[-1][0] == a.path:
            problems.append(f"{where}: {a.path} was renamed to {moves[-1][1]}, and a new {a.path} created "
                            f"since; set the path of the file that was checked")
            return None
        if not present(self.root, path):
            if self._existed(path):
                return "gone"
            problems.append(f"{where}: {a.path} does not exist" + (f" (renamed to {path})" if path != a.path else ""))
            return None
        until, commit = self._blob_until(set(names), path, a.blob)
        if until is None:
            problems.append(f"{where}: the checked content of {a.path} ({a.blob[:7]}) is neither in the "
                            f"history of this file on this branch nor its current content; run 'aisignoff attest' "
                            f"again")
            return None
        annotation = self.config.match(path)
        if annotation is not None and annotation.precedence == "override":
            warnings.append(f'{where}: {path} is declared by an annotation with precedence = "override", '
                            "so the attestation doesn't count; change the annotation instead")
        pieces = pieces_from_values(a.values, f"{a.filename} attestation [{a.index}]", "attestation")
        if pieces.pop(0, None) is not None:
            warnings.append(f"{where}: an attestation records a review, so its AI-Generation doesn't "
                            "count; correct the generation of a commit with a [[commits]] entry")
        return path, (until, commit, pieces, a.blob, self._content_age(until, commit), None, seq)

    def _scoped(self, a, where: str, seq: int, problems: list, warnings: list):
        """An attestation of a commit: of the lines it landed on the default branch, in one file or all."""
        sha = self._resolve(a.commit)
        if sha is None or sha not in self.order:
            problems.append(f"{where}: {a.commit} isn't a commit of the default branch's history (the "
                            "merge or squash commit of a pull request, or a commit made there directly); an "
                            "attestation of a commit covers the lines that commit landed there")
            return None
        path = None
        if a.path is not None:
            path = self._names_since(a.path)[-1]
            if not present(self.root, path):
                if self._existed(path):
                    return "gone"
                problems.append(f"{where}: {a.path} does not exist" + (f" (renamed to {path})" if path != a.path else ""))
                return None
        pieces = pieces_from_values(a.values, f"{a.filename} attestation [{a.index}]", "attestation")
        if pieces.pop(0, None) is not None:
            warnings.append(f"{where}: an attestation records a review, so its AI-Generation doesn't "
                            "count; correct the generation of a commit with a [[commits]] entry")
        # how new the content it saw is depends on the file and on when it was recorded: see _scoped_age
        return path, (None, None, pieces, None, None, sha, seq)

    def _existed(self, path: str) -> bool:
        """Whether a file of this path was ever in the history of HEAD: an attestation of it then
        covers no line any more, since the file was deleted, rather than naming a file by mistake."""
        return bool(_git(self.root, "log", "-1", "--format=%H", self.head or "HEAD", "--", path, check=False))

    # ------------------------------------------------------------ records that cover no line any more
    def _touched(self) -> set[str]:
        """The commits that own or wrote a line of the files resolved so far."""
        out = set()
        for origins in self.origins.values():
            for o in origins:
                if o[0] in ("landed", "released"):
                    out.update(x for x in o[1:3] if x)
                elif o[0] == "pending" and o[1]:
                    out.add(o[1])
        return out

    def _covers_any(self, key: str | None, t: tuple) -> bool:
        files = self.origins.values() if key is None else [self.origins.get(key, ())]
        return any(self._covers(t, o) for origins in files for o in origins)

    def dead_records(self) -> list:
        """The [[attestations]] and [[commits]] entries (of SIGNOFF.toml and the review folder) that
        cover no line of the files resolved so far: the file was deleted, every line it checked has
        changed since, or the commit owns and wrote no line any more. They change nothing, and can
        be deleted without changing a level; git history keeps them. Call it after every file was
        resolved. An entry that is wrong (it names no commit or file of the history) is a problem
        of lint instead, and not listed."""
        touched = self._touched()
        out = list(self.gone)
        out += [a for a, key, t in self.attestation_keys
                if not self._covers_any(key, t) and not self._may_cover_excluded(key, t[5])]
        for entry in self.config.commits:
            sha = self._resolve(entry.commit)
            if sha is not None and sha in self.corrections and sha not in touched \
                    and not self._may_cover_excluded(None, sha):
                out.append(entry)
        return out

    def _may_cover_excluded(self, key: str | None, sha: str | None) -> bool:
        """Whether a record may cover lines of an excluded file, which is never resolved, so that
        it can't be told dead: an attestation of an excluded file, or a record of a commit that
        changed one that is still there, under the name it had then or the one it was renamed to
        since. It keeps its levels for when the exclusion is lifted."""
        if key is not None:
            return any(matches(p, key) for p in self.config.exclude)
        if sha is None or not self.config.exclude:
            return False
        if sha not in self._excluded_touch:
            # --root: the files of the first commit, which has no parent to compare with
            names = _git(self.root, "-c", "core.quotePath=false", "diff-tree", "--root", "--no-commit-id", "--name-only",
                         "-r", "-z", "--relative", "-m", "--first-parent", sha, check=False) or ""
            now = {self._names_since(n)[-1] for n in names.split("\0") if n}
            self._excluded_touch[sha] = any(any(matches(p, n) for p in self.config.exclude) and present(self.root, n)
                                            for n in now)
        return self._excluded_touch[sha]

    def is_dead(self, attestations: list, name: str) -> bool:
        """Whether every entry of a record file that isn't loaded (one a change deletes) covers no
        line: then deleting it changes no level."""
        for a in attestations:
            got = self._attestation(a, f"{name} [[attestations]] entry {a.index}", -1, [], [])
            if got is None or (got != "gone" and (self._covers_any(*got) or self._may_cover_excluded(got[0], got[1][5]))):
                return False
        return True

    def _review_record(self, a, where: str, pending: bool) -> None:
        """An attestation file of the review folder records an independent AI review like a pull
        request description does: with its findings, and for A2 and A3 its report. A record file
        that hasn't landed (PENDING: the change under check adds it) names a report the change adds
        or modifies, or a link, as a description does: an earlier review's report isn't this one's."""
        from .pullrequest import review_problems
        piece = pieces_from_values(a.values, where, "attestation").get(2)
        for p in review_problems(self.root, piece, a.values.get(FINDINGS), self._change_files() if pending else None):
            self.problems.append(f"{where}: {p}")

    def _signoff_review(self, a, where: str) -> None:
        """An AI review (A1-A3) that the change under check adds to SIGNOFF.toml (an entry that
        hasn't landed) gives its findings, and for A2 and A3 its report, as a record file does.
        Entries that have landed are read as they are: a review recorded before findings existed
        has none (F-)."""
        from .pullrequest import review_problems
        piece = pieces_from_values(a.values, where, "attestation").get(2)
        if piece is None or piece.level not in FINDINGS_REVIEWS:
            return
        for p in review_problems(self.root, piece, a.values.get(FINDINGS)):
            self.problems.append(f"{where}: {p}")

    def _check_signoff_commits(self) -> None:
        """A [[commits]] entry that the change under check adds to SIGNOFF.toml and that gives an AI
        review of A1-A3 gives its findings (or the commit's message does), and for A2 and A3 its
        report, as an attestation does."""
        from .pullrequest import review_problems
        entries = self.config.commits
        at = self._signoff_entry_order(len(entries), "commits")
        late = len(self.order) + 1
        for entry, ordinal in zip(entries, at):
            if ordinal != late:
                continue
            where = f"{entry.filename} [[commits]] entry {entry.index}"
            piece = pieces_from_values(entry.values, where, "commit").get(2)
            if piece is None or piece.level not in FINDINGS_REVIEWS:
                continue
            sha = self._resolve(entry.commit)
            findings = entry.values.get(FINDINGS)
            if not findings and sha is not None:
                own = self._trailers.get(sha, {}).get(2)
                findings = own.findings if own is not None and own.level == piece.level else None
            for p in review_problems(self.root, piece, findings):
                self.problems.append(f"{where}: {p}")

    def _change_files(self) -> set[str] | None:
        """The files the change under check adds or modifies (from the top of the repository)."""
        if not hasattr(self, "_changed"):
            from .pullrequest import change_files
            self._changed = change_files(self.root, self.base)
        return self._changed

    def _recorded_order(self, own: list, records: list) -> list[tuple]:
        """(attestation, the commit of the default branch that recorded it or None, whether it hasn't
        landed yet) of the entries of
        SIGNOFF.toml (OWN) and of the record files of the review folder (RECORDS), in the order they
        were recorded: by that commit, those that haven't landed last. On a tie (the same commit),
        SIGNOFF.toml first, then the record files by path, each in the order of its entries. Neither
        file counts before the other: a re-review recorded in SIGNOFF.toml (attest --signoff) replaces
        the findings of an earlier one in the review folder, and the other way round."""
        late = len(self.order) + 1
        by_ordinal = {n: sha for sha, n in self.order.items()}
        own_at = self._signoff_entry_order(len(own))
        rows = [(own_at[i], 0, "", a.index, a) for i, a in enumerate(own)]
        added = self._review_order(records)
        rows += [(added.get(a.filename, late), 1, a.filename, a.index, a) for a in records]
        rows.sort(key=lambda r: r[:4])
        return [(r[4], by_ordinal.get(r[0]), r[0] == late) for r in rows]

    _TABLE = re.compile(r"^\s*\[")
    # an array of tables header, with the key bare, "quoted" or 'quoted', and spaces as TOML allows them
    _HEADER = r"^[ \t]*\[\[[ \t]*(?:{name}|\"{name}\"|'{name}')[ \t]*\]\][ \t]*(?:#.*)?$"

    def _signoff_entry_order(self, count: int, table: str = "attestations") -> list[int]:
        """For each [[attestations]] (or TABLE) entry of SIGNOFF.toml, the ordinal of the commit of the default
        branch that last changed one of its lines (first-parent blame): the commit that recorded it.
        Entries that haven't landed (this change's, or not committed) get one past the newest commit.
        When the entries can't be told apart in the file (not all written as [[attestations]] tables),
        an entry that the default branch's SIGNOFF.toml has too gets 0: it has landed, and counts
        before the record files, in the order they are written; the others haven't landed."""
        late = len(self.order) + 1
        path = self.config.path
        if not count or path is None or not self.order:
            return [late if not self.order else 0] * count
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return self._landed_entries(table, late)
        header = re.compile(self._HEADER.format(name=re.escape(table)))
        starts = [n for n, line in enumerate(lines) if header.match(line)]
        if len(starts) != count:
            return self._landed_entries(table, late)
        blame = _git(self.root, "blame", "--porcelain", "--no-textconv", "--first-parent", "--ignore-revs-file=", "--",
                     path.name, check=False)
        if blame is None:
            return [late] * count
        owners: list[str] = []
        current = ""
        for row in blame.split("\n"):
            if row.startswith("\t"):
                owners.append(current)
                continue
            fields = row.split(" ")
            if len(fields[0]) in (40, 64) and len(fields) >= 3 and fields[1].isdigit():
                current = fields[0]
        out = []
        for k, start in enumerate(starts):
            end = start + 1
            while end < len(lines) and not self._TABLE.match(lines[end]):
                end += 1
            # the lines of the entry (its comments and blank lines aside): the newest one recorded it
            at = [self.order.get(owners[n], late) if n < len(owners) else late for n in range(start, end)
                  if lines[n].strip() and not lines[n].lstrip().startswith("#")]
            out.append(max(at, default=late))
        return out

    def _landed_entries(self, table: str, late: int) -> list[int]:
        """For the entries of SIGNOFF.toml whose recording commit can't be told: 0 for each entry that
        the default branch's SIGNOFF.toml has too (it has landed), else one past the newest commit."""
        entries = self.config.attestations if table == "attestations" else self.config.commits
        landed: list = []
        text = _git(self.root, "show", f"{self.base}:./{self.config.path.name}", check=False) if self.base else None
        if text is not None:
            from .config import ConfigError, load_text
            try:
                base = load_text(text, self.config.path)
                landed = base.attestations if table == "attestations" else base.commits
            except ConfigError:
                pass
        same = [(getattr(e, "path", None), getattr(e, "blob", None), e.commit, e.values) for e in landed]
        return [0 if (getattr(e, "path", None), getattr(e, "blob", None), e.commit, e.values) in same else late
                for e in entries]

    def _scoped_age(self, attestation: tuple, path: str) -> float:
        """How new the content of PATH was that an attestation of a commit saw: the content the file
        had at the commit that recorded the review, aged like the content of an attestation of the
        file (_content_age) as of that commit: until that version of the file was replaced, even if
        the same content returned later (an edit reverted). A review of a commit and a review of the
        whole file that saw the same
        content then count in the order they were recorded, and a whole-file review of newer content
        counts after the review of the commit."""
        key = (id(attestation), path)
        if key in self._ages:
            return self._ages[key]
        recorded = attestation[7] if len(attestation) > 7 else None
        age = float(self.newest)
        if recorded is not None:
            names = self._names_since(path)
            blob = None
            for name in reversed(names):
                blob = _git(self.root, "rev-parse", "--verify", "--quiet", f"{recorded}:./{name}", check=False)
                if blob:
                    blob = blob.strip()
                    break
            if blob:
                # the file as it was when the review was recorded, not a later return to the same content
                until, commit = self._blob_until(set(names), path, blob, at=self.order.get(recorded))
                if until is not None:
                    age = self._content_age(until, commit)
            else:
                age = float(self.order.get(recorded, self.newest))
        self._ages[key] = age
        return age

    def _review_order(self, entries: list) -> dict[str, int]:
        """The ordinal of the commit of the default branch that added each record file of the review
        folder (the files it doesn't have yet, this change's, are missing)."""
        if not entries:
            return {}
        added: dict[str, int] = {}
        if self.base:
            out = _git(self.root, "-c", "core.quotePath=false", "log", "--first-parent", "--diff-merges=first-parent",
                       "--diff-filter=A", "--name-only", "--relative", "--format=%x1e%H", self.base, "--",
                       self.config.review_dir, check=False) or ""
            for record in out.split("\x1e"):
                rows = [r for r in record.strip().splitlines() if r.strip()]
                if rows and rows[0] in self.order:
                    for name in rows[1:]:
                        added.setdefault(name, self.order[rows[0]])  # newest first: keep the last time it was added
        return added

    def _content_age(self, until: int, commit: str | None) -> float:
        """How new the checked content of an attestation is, for ordering the reviews of a line:
        the ordinal of the last commit of the default branch that had it; content of a merged branch
        just before the commit that merged it, and of the change that hasn't landed just before the
        current file. A review of older content is the older review, whenever it was recorded."""
        if commit is None:
            return float(until)
        out = _git(self.root, "rev-list", "--first-parent", "--ancestry-path", f"{commit}..{self.base}",
                   check=False) if self.base else None
        merged = [self.order[s] for s in (out or "").split() if s in self.order]
        return min(merged) - 0.5 if merged else len(self.order) + 0.5

    def renames(self) -> list[tuple[str, str]]:
        """(old, new) paths relative to root of the renames on this branch, oldest first,
        then those not committed yet."""
        if self._renames is None:
            rows: list[str] = []
            if self.head:
                log = _git(self.root, "-c", "core.quotePath=false", "log", "--first-parent", "--diff-merges=first-parent",
                           "-M", "--diff-filter=R", "--name-status", "--relative", "--format=", "--reverse", "HEAD",
                           check=False)
                rows += (log or "").splitlines()
                rows += (_git(self.root, "-c", "core.quotePath=false", "diff", "-M", "--diff-filter=R", "--name-status",
                              "--relative", "HEAD", check=False) or "").splitlines()
            from .diff import _unquote
            self._renames = [(_unquote(f[1]), _unquote(f[2])) for f in (r.split("\t") for r in rows)
                             if len(f) == 3 and f[0].startswith("R")]
        return self._renames

    def _names_since(self, path: str) -> list[str]:
        """The names of a file, oldest first: the names it had before path, path, and the names it
        was renamed to since (the last is its current name)."""
        names = [path]
        renames = self.renames()
        for old, new in reversed(renames):
            if new == names[0] and old not in names:
                names.insert(0, old)
        if not present(self.root, path):
            for old, new in renames:
                if old == names[-1] and new not in names:
                    names.append(new)
        return names

    def _blob_until(self, names: set[str], path: str, blob: str, at: int | None = None) -> tuple[int | None, str | None]:
        """Where the checked content was the attested file's content, under any of its names. The
        same content in another file doesn't count, so a copy can't extend an attestation to lines
        added since. The current file counts as newest (an attestation written before its commit):
        then every line is the checked content. On the default branch: the ordinal of the last
        commit that still had it. Only elsewhere (a merged branch, or the change that hasn't
        landed): the commit that wrote it there.
        at: the ordinal of a commit of the default branch (the one that recorded a review): the file
        as it was there, if it had that content then or before; the same content again later (an edit
        reverted) is a later version of the file. Its last commit is newest only if the content
        stayed until now."""
        current = hash_file(self.root, path)
        is_current = current == blob
        if is_current and at is None:
            return self.newest, None
        if not self.order:
            return (self.newest if is_current else None), None
        log = ["log", "--no-abbrev", "--raw", "--no-renames", "--relative", "-z", "--format=%x1e%H", f"--find-object={blob}"]
        out = self._blob_logs.get(blob)
        if out is None:
            out = _git(self.root, log[0], "--first-parent", "--diff-merges=first-parent", *log[1:], self.base, check=False)
            if out is None:  # git older than 2.31
                out = _git(self.root, log[0], "--first-parent", *log[1:], self.base, check=False) or ""
            self._blob_logs[blob] = out
        wrote, removed = self._find_blob(out, names, blob)
        if at is not None:
            # a rename writes the content under the new name where it removes it under the old one
            gone = [r for r in removed if r not in wrote]
            started = [self.order[s] for s in wrote if self.order.get(s, at + 1) <= at]
            if started:
                later = [self.order[r] for r in gone if self.order.get(r, 0) > max(started)]
                return (min(later) - 1 if later else self.newest if is_current else len(self.order)), None
        if is_current:
            return self.newest, None
        for sha in wrote:
            if sha in self.order:
                later = [self.order[r] for r in removed if self.order.get(r, 0) > self.order[sha]]
                return (min(later) - 1 if later else len(self.order)), None
        for sha in self._find_blob(_git(self.root, *log, "HEAD", check=False) or "", names, blob)[0]:
            return 0, sha
        return None, None

    @staticmethod
    def _find_blob(out: str, names: set[str], blob: str) -> tuple[list[str], list[str]]:
        """The commits of 'git log --raw -z' output that wrote the blob at one of the names, and
        those that replaced it there, each newest first."""
        wrote, removed = [], []
        for record in out.split("\x1e"):
            fields = record.strip("\n\0").split("\0")
            sha = fields[0].strip()
            # with -z: ":meta" and the path alternate
            for meta, name in zip(fields[1::2], fields[2::2]):
                meta = meta.split()
                if len(meta) >= 4 and name in names and blob in (meta[2], meta[3]):
                    (wrote if meta[3] == blob else removed).append(sha)
                    break
        return wrote, removed

    def _covers(self, attestation, origin) -> bool:
        """Whether the content an attestation checked had a line."""
        if attestation[5] is not None:  # an attestation of a commit: the lines it landed, as they are
            return origin[0] in ("landed", "released") and origin[1] == attestation[5]
        until, commit = attestation[0], attestation[1]
        if until == self.newest:
            return True
        kind = origin[0]
        if kind == "released":
            writer = origin[2] or origin[1]
            return bool(commit and self.is_ancestor(writer, commit))
        if kind == "landed":
            owner, writer = origin[1], origin[2] or origin[1]
            if owner is None:  # older than anything we can see
                return True
            return self.is_ancestor(writer, commit) if commit else until >= self.order[owner]
        writer = origin[1]
        return bool(commit and writer and self.is_ancestor(writer, commit))

    # ------------------------------------------------------------ blame
    def _blame(self, rev: str | None, path: str, first_parent: bool, stop: str | None) -> list[tuple[str, int, bool, str]]:
        """(commit, its line number there, whether blame stopped there, the file's path there) of
        each line of a file, at a commit or (rev None) in the working tree. 'stop' is the commit
        that blame doesn't look behind: lines from it or before it come back as stopped there,
        with their line number and path in it. Paths are relative to the top of the repository."""
        # an empty --ignore-revs-file first clears the list of a personal blame.ignoreRevsFile
        # --no-textconv: a diff driver's text conversion (git-crypt, a document converter) would move the lines,
        # or fail where it isn't set up
        args = ["blame", "--porcelain", "--no-textconv", "--ignore-revs-file=", *self.blame_options] + (["--first-parent"] if first_parent else [])
        out = _git(self.root, *args, *([f"^{stop}"] if stop else []), *([rev] if rev else []), "--", path)
        from .diff import _unquote
        rows: list[tuple[str, int, bool, str]] = []
        current, line, boundary, names = "", 0, set(), {}
        for row in out.split("\n"):
            if row.startswith("\t"):
                rows.append((current, line, current in boundary, names.get(current, self.prefix + path)))
                continue
            fields = row.split(" ")
            if len(fields[0]) in (40, 64) and len(fields) >= 3 and fields[1].isdigit():
                current, line = fields[0], int(fields[1])
            elif row == "boundary":
                boundary.add(current)
            elif row.startswith("filename "):
                names[current] = _unquote(row[len("filename "):])
        return rows

    def _base_origins(self, path: str, need_writer: bool) -> list[tuple]:
        """Where each line of a file of the default branch (at self.base) comes from:
        ("landed", the commit that landed it, the commit that wrote it if that is another one)."""
        landed = self._base_blame(path, True)
        merges = {sha for sha, _, stopped, _ in landed if not stopped and len(self.parents.get(sha, [])) > 1}
        written = None
        if need_writer or any(self._side(m)[0] for m in merges):
            written = self._base_blame(path, False, landed)
            if len(written) != len(landed):
                written = None
        out = []
        for n, (sha, line, stopped, name) in enumerate(landed):
            if stopped or sha not in self.order:
                out.append(("landed", None, None))  # a shallow boundary: older than anything we can see
            else:
                writer = written[n][0] if written and not written[n][2] else None
                out.append(("landed", sha, writer if writer != sha else None))
        return out

    def _base_blame(self, path: str, first_parent: bool, landed: list | None = None) -> list[tuple[str, int, bool, str]]:
        """The whole history's blame of a file of the default branch at self.base (first_parent: the
        commits that landed its lines, else those that wrote them), as _blame gives it. With a cache
        of an earlier run at a first-parent commit of the default branch (the newest one there), git
        only blames the commits since, and the lines from before come from the cache: blame passes a
        line that a commit didn't change on to that commit's parent, so the rest is what blame
        found at the cached commit. landed: the first-parent rows, for a line the cache can't place
        otherwise (blame of the writers stopped at another commit than the cached one)."""
        cache = self.cache
        full = self.prefix + path
        if cache is None:
            return self._blame(self.base, path, first_parent, None)
        rows = cache.rows(self.base, full, first_parent)
        if rows is not None:
            return rows
        start = cache.start
        if start is not None and start != self.base:
            rows = self._through_cache(self._blame(self.base, path, first_parent, start), start, first_parent, landed)
        if rows is None:
            rows = self._blame(self.base, path, first_parent, None)
        cache.record(full, first_parent, rows)
        return rows

    def _through_cache(self, recent: list, start: str, first_parent: bool, landed: list | None) -> list | None:
        """The rows of a blame that stopped at the cached commit, with the lines from before it taken
        from the cache; None where the cache doesn't have them (then git blames the whole history)."""
        cache = self.cache
        out = []
        for n, row in enumerate(recent):
            sha, line, stopped, name = row
            if not stopped:
                out.append(row)
                continue
            if sha != start:
                # a writer older than the cached commit, on a branch merged since: the line's place at the
                # cached commit is where the first-parent blame stopped
                if first_parent or landed is None or n >= len(landed) or not landed[n][2] or landed[n][0] != start:
                    return None
                line, name = landed[n][1], landed[n][3]
            before = cache.rows(start, name, first_parent)
            if before is None or not 0 < line <= len(before):
                return None
            out.append(before[line - 1])
        return out

    def _writers(self, path: str, lines: int) -> list[str | None]:
        """For a file with lines that aren't on the default branch yet: the commit of the change
        that wrote each line (None: not committed, or not a line of the change)."""
        if not self.pending or path not in self.head_files:
            return [None] * lines
        rows = self._blame(None, path, False, self.base)
        if len(rows) != lines:
            return [None] * lines
        return [sha if not stopped and sha in self.pending else None for sha, _, stopped, _ in rows]

    def _unit_origin(self, path: str) -> tuple:
        """Binary and empty files and symlinks are one unit: the commit that last changed the file."""
        old, removed, added = self.changes.get(path, (path if path in self.base_blobs else None, [], []))
        if old is None or removed or added:
            writer = None
            if self.pending and not _git(self.root, "status", "--porcelain", "--", path, check=False):
                writer = (_git(self.root, "log", "-1", "--format=%H", "HEAD", f"^{self.base}", "--", path,
                               check=False) or "").strip() or None
                if self.release:
                    owner = (_git(self.root, "log", "-1", "--first-parent", "--format=%H", "HEAD", f"^{self.base}",
                                  "--", path, check=False) or "").strip()
                    if owner in self.branch_order:
                        return ("released", owner, writer if writer != owner else None)
            return ("pending", writer)
        # the last commit that changed its content, following renames: a commit that only moved it
        # (R100) leaves it to the one before, as blame does for the lines of a text file. One
        # 'git log -1' per name, which stops at the first commit, instead of --follow over the whole history.
        cached = self.cache.unit(self.prefix + old, self._touched_since) if self.cache is not None else None
        sha = cached if cached is not None else self._last_content_change(old)
        if cached is None and self.cache is not None:
            self.cache.record_unit(self.prefix + old, sha)
        if sha not in self.order:
            return ("landed", None, None)
        return ("landed", sha, None)

    def _touched_since(self, start: str) -> set[str] | None:
        """The paths (from the top of the repository) that a first-parent commit after start changed,
        or added or deleted under a rename; None if git can't say."""
        # -z: the names as they are, which the cache's keys are (quoted, a name with a non-ASCII
        # character or a newline would miss its key, and the cache keep a stale commit)
        out = _git(self.root, "log", "--first-parent", "--diff-merges=first-parent", "--no-renames", "--name-only",
                   "-z", "--format=", f"{start}..{self.base}", check=False)
        if out is None:  # git older than 2.31: every parent of a merge, which lists more
            out = _git(self.root, "log", "--first-parent", "-m", "--no-renames", "--name-only", "-z", "--format=",
                       f"{start}..{self.base}", check=False)
        if out is None:
            return None
        # with an empty --format, the output is the names alone, each ended by a NUL: no byte of a
        # name is framing (a name may start with a newline)
        return {name for name in out.split("\0") if name}

    def _last_content_change(self, old: str) -> str:
        """The first-parent commit that last changed a file's content, under this name or one it had before."""
        sha, name, rev, seen = "", old, self.base, set()
        while name and rev and (name, rev) not in seen:
            seen.add((name, rev))
            sha = (_git(self.root, "log", "-1", "--first-parent", "--format=%H", rev, "--", name, check=False) or "").strip()
            if not sha:
                break
            raw = _git(self.root, "diff-tree", "-r", "-M", "--raw", "-z", "--no-abbrev", "--no-commit-id", f"{sha}^",
                       sha, check=False)
            moved = None
            fields = (raw or "").split("\0")  # -z: ":meta", then one name, or two for a rename or copy
            k = 0
            while k < len(fields) and fields[k].startswith(":"):
                status = fields[k].split()[-1]
                count = 2 if status[:1] in ("R", "C") else 1
                parts = fields[k + 1:k + 1 + count]
                if status == "R100" and len(parts) == 2 and parts[1] == name:
                    moved = parts[0]
                k += 1 + count
            if moved is None:
                break
            name, rev = moved, f"{sha}^"
        return sha

    def _of_file(self, path: str) -> list[tuple]:
        """The attestations of a file, in the order they were recorded: its own, and the attestations
        of commits that name no file."""
        own, every = self.attestations.get(path, []), self.attestations.get(None, [])
        if not every:
            return own
        return sorted(own + every, key=lambda a: a[6])

    def _stored(self, path: str) -> bytes:
        """A file's content as git stores it, which blame and diff read: the work tree's bytes, except for
        a file that git converts (working-tree-encoding, or a filter such as Git LFS) and that is as on the
        default branch, whose blob is read (UTF-16 text has NUL bytes in the work tree; an LFS file is its
        pointer in git). A converted file that a change edits, adds or renames is read from HEAD's blob when
        the work tree is as committed (a pull request's CI run), else from the work tree."""
        if path in self.converted:
            blob = None
            if path not in self.changes and path in self.base_blobs:
                blob = self.base_blobs[path]
            elif path in self.head_files and not _git(self.root, "status", "--porcelain", "--", path, check=False):
                blob = self.head_files[path]  # a change that is committed, as in a pull request's CI run
            content = _git_bytes(self.root, "cat-file", "blob", blob) if blob else None
            if content is not None:
                return content
        try:
            return (self.root / path).read_bytes()
        except OSError:
            return b""

    def _converted(self) -> set[str]:
        """The files of the default branch and of HEAD that git converts between the work tree and the repository."""
        paths = sorted(set(self.base_blobs) | set(self.head_files))
        if not paths:
            return set()
        out = _git_bytes(self.root, "check-attr", "-z", "--stdin", "filter", "working-tree-encoding",
                         stdin="\0".join(paths).encode("utf-8", "surrogateescape") + b"\0")
        fields = (out or b"").decode("utf-8", "surrogateescape").split("\0")
        return {fields[k] for k in range(0, len(fields) - 2, 3)  # path, attribute, value
                if fields[k + 2] not in ("unspecified", "unset")}

    def line_origins(self, path: str) -> list[tuple]:
        """Where each line of a file comes from: ("landed", ...) as in _base_origins, or ("pending", the commit of the change that wrote it, or None) for a line
        that isn't on the default branch."""
        if (self.root / path).is_symlink():  # one unit, as git sees it (never read what it points to)
            return [self._unit_origin(path)]
        data = self._stored(path)
        if not data or b"\x00" in data[:BINARY_PROBE]:
            return [self._unit_origin(path)]
        lines = data.count(b"\n") + (not data.endswith(b"\n"))
        old, removed, added = self.changes.get(path, (path if path in self.base_blobs else None, [], []))
        if old is None:  # a new file: every line is the change's
            return self._pending_origins(path, lines, [None] * lines)
        attestations = self._of_file(path)
        base = self._base_origins(old, any(a[1] for a in attestations))
        new, gone = set(added), set(removed)
        out: list[tuple | None] = []
        at = 1  # the line of the default branch's file that the next unchanged line is
        for n in range(1, lines + 1):
            if n in new:
                out.append(None)
                continue
            while at in gone:
                at += 1
            out.append(base[at - 1] if at <= len(base) else None)
            at += 1
        if None in out:
            out = self._pending_origins(path, lines, out)
        return out

    def _pending_origins(self, path: str, lines: int, out: list) -> list[tuple]:
        """The origins of the lines (None in out) that aren't on the default branch: ("pending",
        the commit of the change that wrote it), or on a release branch (landed) ("released",
        the first-parent commit of the branch that landed it there, the one that wrote it)."""
        writers = self._writers(path, lines)
        owners = [None] * lines
        if self.release and self.pending and path in self.head_files:
            rows = self._blame(None, path, True, self.base)
            if len(rows) == lines:
                owners = [sha if not stopped and sha in self.branch_order else None for sha, _, stopped, _ in rows]
        return [o if o is not None else
                ("released", owners[n], writers[n] if writers[n] != owners[n] else None) if owners[n] else
                ("pending", writers[n]) for n, o in enumerate(out)]

    # ------------------------------------------------------------ resolution
    def resolve_lines(self, path: str, fallback: Declaration) -> list[Part]:
        """The parts of a file: runs of lines that share one combined declaration."""
        fb = {i: Piece(fallback.get(level), fallback.get(names), fallback.source, "file", tuple(fallback.problems))
              for i, (level, names) in enumerate(AXES) if fallback.get(level) is not None}
        if 2 in fb and fallback.findings:
            fb[2] = replace(fb[2], findings=fallback.findings)
        attestations = self._of_file(path)
        keys: list[tuple] = []
        memo: dict[tuple, tuple] = {}
        origins = self.line_origins(path)
        self.origins[path] = set(origins)  # which records cover a line: see dead_records
        for origin in origins:
            if origin not in memo:
                memo[origin] = self._line_pieces(origin, attestations, fb, path)
            keys.append(memo[origin])

        parts: dict[tuple, Part] = {}
        previous = None
        for n, key in enumerate(keys, start=1):
            part = parts.get(key)
            if part is None:
                pieces, advisory = key
                d = combine(pieces)
                errors = validate(d, self.policy)
                missing = {f"missing {level}" for (level, _), p in zip(AXES, pieces) if p is not None and p.kind == "required"}
                errors = [e for e in errors if e not in missing]
                part = parts[key] = Part(d, errors, 0, [], tuple(p.kind if p else None for p in pieces), advisory)
            part.lines += 1
            if key == previous:
                part.runs[-1][1] = n
            else:
                part.runs.append([n, n])
            previous = key
        return sorted(parts.values(), key=lambda p: p.runs[0][0])

    def _line_pieces(self, origin: tuple, attestations: list, fb: dict[int, Piece], path: str = "") -> tuple[tuple, bool]:
        """One piece per axis for the lines of one origin, and whether they are advisory."""
        # oldest checked content first: the later of two reviews is the review of the newer content
        # (an attestation of a commit: the content of the file when the review was recorded)
        attested = [a[2] for a in sorted((a for a in attestations if self._covers(a, origin)),
                                         key=lambda a: a[4] if a[4] is not None else self._scoped_age(a, path))]
        kind = origin[0]
        if kind in ("landed", "released"):
            sha, writer = origin[1], origin[2]
            if sha is None:
                return self._combine({}, (None, False), attested, fb, None, ""), False
            owner = self.commit_pieces(sha)
            required = None
            if self.config.history.undeclared == "error":
                required = 'required by [history] undeclared = "error"'
            elif self.since is not None and self.order.get(sha, self.since + 1) > self.since:
                required = "required by [history] require-trailers-since"
            self._note_owner(sha, bool(owner), required is not None)
            hint = self._hint(sha, writer) if len(self.parents.get(sha, [])) > 1 else (None, False)
            who, advice = self.describe(sha), ""
            if owner and len(owner) < len(AXES) and sha in self.corrections and not self._trailers.get(sha):
                # the commit says nothing: the entry is all there is, and it doesn't declare the commit
                who = f"the [[commits]] entry for {who}"
                advice = ("; give all three levels there, or raise a review on its own with 'aisignoff attest', "
                          "which needs no declaration of the rest")
            return self._combine(owner, hint, attested, fb, required, who, advice=advice), False
        # a line that isn't on the default branch yet
        writer = origin[1]
        method = self.config.history.merge_method
        own = self.commit_pieces(writer) if writer and len(self.parents.get(writer, [])) <= 1 else {}
        if self.declared is not None and method != "rebase":
            # the pull request's description will be the message of the commit that lands it
            hint = self._hint(None, writer) if method == "merge" else (None, False)
            who = "the declaration of this change"
            required = "required for a pull request into the default branch"
            return self._combine(self.declared, hint, attested, fb, required, who), False
        if method == "rebase" and (self.declared is not None or self.preview):
            # each commit lands as it is, without the description
            required = None
            if writer and (self.config.history.undeclared == "error" or self.since is not None):
                required = "required by [history] " + ('undeclared = "error"' if self.since is None
                                                       else "require-trailers-since")
            who = self.describe(writer) if writer else "this change"
            return self._combine(own, (None, False), attested, fb, required, who), False
        # nothing declares the change yet: what its commits say is shown, and fails nothing. Unless
        # the commits land as they are (rebase), that is their generation only: the reviews are
        # what the pull request will declare
        own = {i: replace(p, kind="branch") for i, p in own.items() if i == 0 or method == "rebase"}
        return self._combine(own, (None, False), attested, fb, None, self.describe(writer) if writer else "this change",
                             waiting=True), bool(own)

    def _combine(self, owner: dict[int, Piece], hinted: tuple[Piece | None, bool], attested: list[dict[int, Piece]],
                 fb: dict[int, Piece], required: str | None, who: str, waiting: bool = False, advice: str = "") -> tuple:
        """One piece per axis from a line's owner, the generation its writing commit says (hinted:
        the piece, and whether a [[commits]] entry says it), and the attestations that cover it
        (reviews only). Generation: the hint (only next to an owner that
        declares something, and only a higher level than the owner's unless a [[commits]] entry
        says it: a commit message inside a pull request can't take the AI out of its lines), else
        the owner's. Reviews: the
        highest of the owner's (or, when the file level declares the line, the file level's) and the
        attestations', the later one on a tie; TODO is below every level. An axis that nothing gives is missing when the owner declares another one,
        an error when a declaration is required, and the file-level declaration's otherwise."""
        problems = tuple(dict.fromkeys(x for p in owner.values() for x in p.problems))
        hint, explicit = hinted
        if hint is not None and not explicit and 0 in owner \
                and _level_value(hint.level) <= _level_value(owner[0].level):
            hint = None
        if hint is not None and not hint.names and hint.level not in (None, "G0"):
            # a commit that says only a generation (an agent's "AI-Generation: G3"): the model is
            # the one the owner names, if it names one
            if 0 in owner and owner[0].names:
                hint = replace(hint, names=owner[0].names)
            else:
                hint = replace(hint, problems=hint.problems + (
                    f"{hint.source} says {hint.level} for the lines it wrote, but no Assisted-by; name the tool "
                    "and model there, in the declaration of the pull request, or with a [[commits]] entry",))
        out: list[Piece | None] = []
        for i, (level, _) in enumerate(AXES):
            best = None
            given = [(n, pieces[i]) for n, pieces in enumerate(attested) if i in pieces]
            if i == 0:
                if hint is not None and owner:
                    best = hint
                elif i in owner:
                    best = owner[i]
            else:
                found = ([("owner", owner[i])] if i in owner else []) + given
                if given and not owner and not required and i in fb:
                    # the file level declares the line: an attestation raises its review, never lowers it
                    found = [("file", fb[i])] + found
                if found:
                    best = max(enumerate(found), key=lambda t: (_level_value(t[1][1].level), t[0]))[1][1]
            if best is not None:
                best = replace(best, problems=tuple(dict.fromkeys(best.problems + problems)))
            elif owner:
                text = (f"{who} leaves {level} to the pull request" if waiting else
                        f"{who} declares levels, but no {level} (nor does an attestation){advice}")
                best = Piece(None, (), who, "required", problems + (text,))
            elif required:
                best = Piece(None, (), who, "required", (f"{who} declares no {level} ({required})",))
            else:
                best = fb.get(i)
            out.append(best)
        if out[2] is not None and out[2].level is not None:
            # the findings level: what the last independent AI review (A1-A3) of the line found. The
            # owner's review comes first (or the file level's, where that declares the line), then the
            # attestations that cover it, each a review of content that already had the line. A review
            # without findings leaves them as they are; an owner without one leaves the line at F-
            if owner or required:
                reviews = [owner.get(2)]
            else:
                reviews = [fb.get(2)]
            reviews += [pieces.get(2) for pieces in attested]
            findings = None
            for p in reviews:
                if p is not None and p.level in FINDINGS_REVIEWS and p.findings:
                    findings = p.findings
            if findings != out[2].findings:
                out[2] = replace(out[2], findings=findings)
        return tuple(out)


def _level_value(level: str | None) -> int:
    """For comparing review levels: TODO (or nothing) below any level."""
    return int(level[1]) if level and len(level) == 2 and level[1].isdigit() else -1
