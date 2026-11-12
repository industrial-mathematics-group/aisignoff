"""Line-level declarations from git history (the [history] table of SIGNOFF.toml).

Each line has one owner, and the owner declares it:

1. A line that is unchanged since the commit of the snapshot (SIGNOFF.snapshot.json, written by
   'aisignoff freeze') has the levels the snapshot recorded.
2. Otherwise the owner is the commit that landed the line on the default branch
   ('git blame --first-parent'): a commit made there directly, a squash commit, or the merge
   commit of a pull request. Its message declares the levels with "Key: value" lines
   (AI-Generation, Human-Review, ...) or the ticked checkboxes of a pull request template; a
   [[commits]] entry corrects it. Commits and pull requests inside it declare nothing.
3. One exception, for generation only: inside a merge commit that declares its lines, the
   commit that wrote a line can say AI-Generation for it (a hand-written commit in an AI-written
   pull request).
4. A review is the higher of the owner's level and an [[attestations]] entry of the file whose
   content (a git blob) already contained the line.
5. An owner that declares nothing leaves its lines to the file-level declaration (SIGNOFF.toml
   annotations and inline tags), or fails lint with undeclared = "error". One that declares some
   axes but not all, or leaves the template unfilled, is an error.

Lines that aren't on the default branch yet (a feature branch, a pull request's merge preview,
uncommitted changes) are the diff against it. They take the declaration given for the change
(the pull request description); without one they are shown with what their commits say, and
nothing about them fails.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path

from .model import AXES, LEVEL_KEYS, LIST_KEYS, TODO, Declaration, canonical_key, validate

UNCOMMITTED = "0" * 40
SNAPSHOT = "SIGNOFF.snapshot.json"  # written by 'aisignoff freeze'
SNAPSHOT_FORMAT = 1
REVERT = re.compile(r"^This reverts commit ([0-9a-f]{7,64})", re.M)
BINARY_PROBE = 16384


class HistoryError(Exception):
    pass


def _git(root: Path, *args: str, check: bool = True, stdin: bytes | None = None) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, input=stdin)
    except FileNotFoundError:
        raise HistoryError("git is not installed")
    if r.returncode != 0:
        if check:
            raise HistoryError(f"git {args[0]} failed: {r.stderr.decode('utf-8', 'replace').strip()}")
        return None
    return r.stdout.decode("utf-8", "surrogateescape")


def _git_error(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    except FileNotFoundError:
        return ""
    return r.stderr.decode("utf-8", "replace") if r.returncode else ""


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
    kind: str  # commit | branch | attestation | file | declared | frozen | required
    problems: tuple[str, ...] = ()


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


def parse_checkboxes(text: str, author: str, source: str) -> dict[int, Piece]:
    """Axis pieces from the ticked checkboxes of a pull request template in a commit message
    (a squash commit with the default message "Pull request title and description"):

        - [x] **G3** AI-autonomous: ...           the generation level (one)
        - [x] **Claude Opus** (Anthropic)         a model that wrote parts of it
        - [ ] **Other:** Some model               another one, if filled in
        - [x] **H1** I ran the tests ...          the highest ticked human review level
        - [x] **A2** A new AI session ... Model: X  the highest ticked AI review level

    The human review is the commit author's; the AI review names the model after "Model:", or
    the models that wrote the change. As in the template, no ticked AI review box means A0.
    Models count only between the generation and the human review boxes, and boxes in code
    blocks not at all. Generation or human review boxes that are there with none ticked are a
    template that wasn't filled in: TODO. Nothing is returned without any level box."""
    levels: dict[str, list[str]] = {"G": [], "H": [], "A": []}
    seen: set[str] = set()
    models: list[str] = []
    reviewer: dict[str, str] = {}
    for ticked, item in _boxes(text):
        level = _BOX_LEVEL.match(item)
        if level:
            code = level.group(1)
            seen.add(code[0])
            if ticked:
                levels[code[0]].append(code)
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
            elif top == "A1":
                found = tuple(f"{m}, self-check by the generating session" for m in models)
            elif top == "A2":
                found = tuple(f"{m}, new session without the generating conversation" for m in models)
            else:  # A0, or A3 without a model
                found = ()
        else:
            found = names[letter]
        out[i] = Piece(top, found, f"{source}, pull request checkboxes", "commit", tuple(problems))
    return out


def parse_message(body: str, author: str, source: str) -> tuple[dict[int, Piece], str | None]:
    """The declaration in a commit message body or a pull request description: its "Key: value"
    lines, or the ticked checkboxes of a pull request template. One or the other: with both, both
    count (the lines where they overlap) and the second value is the problem to report."""
    from_trailers = parse_trailers(body, source)
    from_boxes = parse_checkboxes(body, author.strip(), source)
    both = None
    if from_trailers and from_boxes:
        both = (f"{source} declares levels both as trailers and as ticked checkboxes; "
                "use one of them, or settle it with a [[commits]] entry")
    return {**from_boxes, **from_trailers}, both


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
    if not values and not problems:
        return Declaration()
    d = Declaration.from_mapping(values, " + ".join(sources) or "history")
    d.problems = problems
    return d


def format_runs(runs: list[list[int]], limit: int = 3) -> str:
    text = ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs[:limit])
    more = "" if len(runs) <= limit else f" and {len(runs) - limit} more range(s)"
    return ("line " if len(runs) == 1 and runs[0][0] == runs[0][1] else "lines ") + text + more


class Snapshot:
    """SIGNOFF.snapshot.json: the levels of every line as of one commit of the default branch.

        {"format": 1, "aisignoff": "0.12.0", "commit": "<hash>",
         "declarations": [{"AI-Generation": "G3", ..., "source": "commit 1a2b3c4 (...)"}, ...],
         "files": {"src/solver.py": {"blob": "<hash>", "runs": [[1, 120, 0], [121, 130, 2]]}}}

    A run is [first line, last line, index into declarations]. Lines that are unchanged since
    that commit keep these levels whatever a later version of aisignoff would work out for them."""

    def __init__(self, commit: str, declarations: list[dict], files: dict[str, dict]):
        self.commit = commit
        self.declarations = declarations
        self.files = files
        self.pieces = [pieces_from_values(d, d.get("source") or "snapshot", "frozen") for d in declarations]

    @classmethod
    def read(cls, path: Path) -> "Snapshot":
        """Raises ValueError for a file that isn't a snapshot."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError(f"cannot be read ({e})")
        if not isinstance(data, dict) or data.get("format") != SNAPSHOT_FORMAT:
            raise ValueError(f'needs "format": {SNAPSHOT_FORMAT} (written by a newer aisignoff?)')
        commit, declarations, files = data.get("commit"), data.get("declarations"), data.get("files")
        if not isinstance(commit, str) or not _SHA.match(commit):
            raise ValueError('"commit" must be a full commit hash')
        if not isinstance(declarations, list) or not all(isinstance(d, dict) for d in declarations):
            raise ValueError('"declarations" must be a list of tables')
        for d in declarations:
            for (level, names) in AXES:
                if not isinstance(d.get(level), str) or not isinstance(d.get(names, []), list) \
                        or not all(isinstance(n, str) for n in d.get(names, [])):
                    raise ValueError(f"a declaration without a valid {level}")
        if not isinstance(files, dict):
            raise ValueError('"files" must be a table')
        for name, entry in files.items():
            runs = entry.get("runs") if isinstance(entry, dict) else None
            if not isinstance(runs, list) or not isinstance(entry.get("blob"), str):
                raise ValueError(f"{name}: needs blob and runs")
            expected = 1
            for run in runs:
                if not (isinstance(run, list) and len(run) == 3 and all(type(x) is int for x in run)
                        and run[0] == expected and run[1] >= run[0] and 0 <= run[2] < len(declarations)):
                    raise ValueError(f"{name}: runs must cover the lines in order, each with a declaration")
                expected = run[1] + 1
        return cls(commit, declarations, files)

    def blob(self, path: str) -> str | None:
        entry = self.files.get(path)
        return entry["blob"] if entry else None

    def lines(self, path: str) -> int:
        runs = self.files[path]["runs"]
        return runs[-1][1] if runs else 0

    def lookup(self, path: str, line: int) -> int | None:
        """The index of the declaration of a line as of the snapshot's commit (None: not recorded)."""
        entry = self.files.get(path)
        if entry is None:
            return None
        runs = entry["runs"]
        lo, hi = 0, len(runs)
        while lo < hi:
            mid = (lo + hi) // 2
            if runs[mid][1] < line:
                lo = mid + 1
            else:
                hi = mid
        return runs[lo][2] if lo < len(runs) and runs[lo][0] <= line else None

    @staticmethod
    def render(commit: str, version: str, results, blobs: dict[str, str]) -> tuple[str, int, int]:
        """The text of a snapshot of the given results (those resolved line by line) at commit,
        with the number of files and lines in it. One line per declaration and per file, so
        that a later snapshot shows up as a readable diff."""
        declarations: list[str] = []
        index: dict[str, int] = {}
        files = []
        lines = 0
        for r in results:
            if r.parts is None or r.path not in blobs:
                continue  # file-level (precedence = "override"): the annotation keeps declaring it
            runs = []
            for i, part in enumerate(r.parts):
                text = json.dumps({**part.declaration.as_dict(), "source": part.declaration.source}, ensure_ascii=False)
                n = index.setdefault(text, len(declarations))
                if n == len(declarations):
                    declarations.append(text)
                runs += [[a, b, n] for a, b in part.runs]
            runs.sort()
            lines += sum(b - a + 1 for a, b, _ in runs)
            files.append(f" {json.dumps(r.path, ensure_ascii=False)}: "
                         + json.dumps({"blob": blobs[r.path], "runs": runs}, separators=(", ", ": ")))
        out = ["{", f' "format": {SNAPSHOT_FORMAT},', f' "aisignoff": {json.dumps(version)},',
               f' "commit": "{commit}",', ' "declarations": [', ",\n".join("  " + d for d in declarations), " ],",
               ' "files": {', ",\n".join(" " + f for f in files), " }", "}"]
        return "\n".join(out) + "\n", len(files), lines


class History:
    """Resolves the declaration of each line of a project's files from git history."""

    def __init__(self, root: Path, config, declared: dict[int, Piece] | None = None, base: str | None = None,
                 use_snapshot: bool = True):
        """declared: the declaration of the change that isn't on the default branch yet (the pull
        request description), None when there is none. base: the commit that change starts from,
        when the caller knows it (aisignoff diff BASE, lint --base)."""
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
        self._side_cache: dict[str, tuple[bool, int]] = {}
        self._noted: set[str] = set()
        self._renames: list[tuple[str, str]] | None = None
        self.head = self._resolve("HEAD")
        self.prefix = (_git(self.root, "rev-parse", "--show-prefix", check=False) or "").strip()
        self.declared = declared
        # the newest commit of the default branch that HEAD contains: what is landed
        self.base = self._find_base(base)
        self._load_chain()
        self.newest = len(self.order) + 1  # content that no commit of the default branch has yet
        # the commits of HEAD that aren't on the default branch yet
        self.pending: set[str] = set()
        if self.head and self.head != self.base:
            self.pending = set((_git(self.root, "rev-list", self.head, f"^{self.base}", check=False) or "").split())
        head_parents = (_git(self.root, "rev-parse", f"{self.head}^@", check=False) or "").split() if self.head else []
        # HEAD merges the change into the default branch: the merge preview of a pull request's CI run
        self.preview = self.head in self.pending and len(head_parents) == 2 and head_parents[0] == self.base
        self.head_files = self._tree("HEAD") if self.head else {}
        self.base_blobs = self._tree(self.base) if self.base else {}
        self.changes = self._load_changes()
        self.snapshot = self._load_snapshot() if use_snapshot else None
        self.frozen = self.order[self.snapshot.commit] if self.snapshot else 0
        self.corrections = self._load_corrections()
        self.since = self._ordinal_of_setting(config.history.require_trailers_since)
        self.blame_options = (["-w"] if config.history.ignore_whitespace else []) + ["--root"] + self._ignore_revs()
        self.attestations = self._load_attestations()

    # ------------------------------------------------------------ the default branch
    def _default_tip(self) -> str | None:
        """The tip of the default branch: HEAD when it is checked out, else origin's (or the local
        one, when that is ahead of it or the only one)."""
        name = self.config.history.default_branch
        if name:
            names = [name]
        else:
            remote = (_git(self.root, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD", check=False) or "").strip()
            names = ([remote.split("/", 1)[1]] if "/" in remote else []) + ["main", "master"]
        current = (_git(self.root, "symbolic-ref", "--short", "-q", "HEAD", check=False) or "").strip()
        if current and current in names:
            return self.head
        for n in names:
            remote, local = self._resolve(f"refs/remotes/origin/{n}"), self._resolve(f"refs/heads/{n}")
            if remote and local and self.is_ancestor(remote, local):
                return local  # commits that aren't pushed yet
            if remote or local:
                return remote or local
        if name:
            self.problems.append(f"[history] default-branch: there is no branch {name} here (neither origin/{name} "
                                 f"nor {name}), so every commit of HEAD counts as landed")
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

    def _load_snapshot(self) -> Snapshot | None:
        path = self.root / SNAPSHOT
        if not path.is_file():
            return None
        try:
            snapshot = Snapshot.read(path)
        except ValueError as e:
            self.problems.append(f"{SNAPSHOT} {e}; run 'aisignoff freeze' again")
            return None
        if snapshot.commit not in self.order:
            self.problems.append(f"{SNAPSHOT}: its commit {short(snapshot.commit)} is not on the default branch below "
                                 "HEAD, so the snapshot can't be used; run 'aisignoff freeze' on the default branch")
            return None
        tree = self._tree(snapshot.commit)
        wrong = sorted(p for p in snapshot.files if tree.get(p) != snapshot.blob(p))
        if wrong:
            self.problems.append(f"{SNAPSHOT} doesn't match commit {short(snapshot.commit)} ({wrong[0]}"
                                 + (f" and {len(wrong) - 1} more" if len(wrong) > 1 else "")
                                 + "): it was edited or belongs to another commit; restore it or run 'aisignoff freeze'")
            for p in wrong:
                del snapshot.files[p]
        return snapshot

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
        self._trailers[sha], both = parse_message(body, author, self.describe(sha))
        if both:
            self._both[sha] = both
        revert = REVERT.search(body)
        if revert:
            self._reverts[sha] = revert.group(1)

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
            if sha not in self.order and sha not in self.pending and set(pieces) - {0} and not (
                    self.snapshot and self.is_ancestor(sha, self.snapshot.commit)):
                self._warnings.append(f"{where}: {entry.commit} is a commit inside a pull request, so only its "
                                      "AI-Generation counts; reviews are declared by the commit that landed it "
                                      "on the default branch, or by an attestation")
            out.setdefault(sha, {}).update(pieces)
        return out

    def _ignore_revs(self) -> list[str]:
        """--ignore-rev options from .git-blame-ignore-revs (or [history] ignore-revs-file).

        Each entry is resolved first: git blame stops at an entry it can't resolve (an
        abbreviated hash, a commit of other history), which must not pass for "not committed"."""
        name = self.config.history.ignore_revs_file
        if name is None:
            if not (self.root / ".git-blame-ignore-revs").is_file():
                return []
            name = ".git-blame-ignore-revs"
        try:
            text = (self.root / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            self.problems.append(f"[history] ignore-revs-file: {name} does not exist")
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
        return options

    def _ordinal_of_setting(self, rev: str | None) -> int | None:
        if rev is None:
            return None
        sha = self._resolve(rev)
        if sha is None or sha not in self.order:
            self.problems.append(f"[history] require-trailers-since: {rev} is not a commit of the default branch")
            return None
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

    def _side(self, merge: str) -> tuple[bool, int]:
        """Of the commits a merge commit brought in: whether one that isn't a merge says
        AI-Generation, and how many merges among them declare something (pull requests that
        landed elsewhere first, as after a git pull)."""
        if merge not in self._side_cache:
            parents = self.parents.get(merge, [])
            says, merges = False, 0
            if len(parents) > 1:
                out = _git(self.root, "log", f"--format={self.FORMAT}", merge, f"^{parents[0]}", check=False) or ""
                for record in _records(out):
                    if record[0] == merge:
                        continue
                    if record[0] not in self._trailers:
                        self._remember(*record)
                    pieces = self.commit_pieces(record[0])
                    if len(self.parents[record[0]]) > 1:
                        merges += bool(pieces)
                    elif 0 in pieces:
                        says = True
            self._side_cache[merge] = (says, merges)
        return self._side_cache[merge]

    def is_ancestor(self, a: str, b: str) -> bool:
        if (a, b) not in self._ancestor:
            try:
                r = subprocess.run(["git", "-C", str(self.root), "merge-base", "--is-ancestor", a, b],
                                   capture_output=True)
                self._ancestor[(a, b)] = r.returncode == 0
            except FileNotFoundError:
                raise HistoryError("git is not installed")
        return self._ancestor[(a, b)]

    def _hint(self, owner: str | None, writer: str | None) -> Piece | None:
        """The generation that the commit which wrote a line says for it (rule 3): only a commit
        that isn't a merge, and only a level."""
        if not writer or writer == owner:
            return None
        pieces = self.commit_pieces(writer)
        if len(self.parents.get(writer, [])) > 1 or 0 not in pieces or _level_value(pieces[0].level) < 0:
            return None
        return replace(pieces[0], kind="branch")

    def _note_owner(self, sha: str, declares: bool, required: bool) -> None:
        """Warnings about a commit that owns lines without declaring them, where that is easy to miss."""
        if sha in self._noted:
            return
        self._noted.add(sha)
        if declares or required:
            return
        if sha in self._reverts:
            self._warnings.append(f"{self.describe(sha)} reverts {short(self._reverts[sha])} and declares nothing: the "
                                  "lines it restored take the file-level declaration. Declare it with the levels of "
                                  f'what it restored: [[commits]] commit = "{sha[:12]}"')
        elif len(self.parents.get(sha, [])) > 1 and self._side(sha)[1]:
            self._warnings.append(f"{self.describe(sha)} is a merge that declares nothing, with {self._side(sha)[1]} "
                                  "declared merge(s) inside it (pull requests that a git pull brought in?): what is "
                                  "inside doesn't count, so its lines take the file-level declaration. Declare it "
                                  f'with [[commits]] commit = "{sha[:12]}"')

    def warnings(self) -> list[str]:
        """What lint shows without failing (lint --strict fails on them)."""
        return list(dict.fromkeys(self._warnings))

    # ------------------------------------------------------------ attestations
    def _load_attestations(self) -> dict[str, list[tuple[int, str | None, dict[int, Piece]]]]:
        """Per file: (until, commit, pieces) of each attestation. 'until' is the ordinal of the last
        commit of the default branch at which the file still was the checked content (newest: it
        is the file as it is now). The commit is set instead when no commit of the default branch
        had that content, only a merged branch or the change that hasn't landed (a pull request
        whose file the default branch changed meanwhile): then the attestation covers the lines
        whose commit the checked content contained."""
        out: dict[str, list] = {}
        for a in self.config.attestations:
            where = f"{a.filename} [[attestations]] entry {a.index}"
            names = self._names_since(a.path)  # the attested file's names, the current one last
            path = names[-1]
            moves = [(old, new) for old, new in self.renames() if a.path in (old, new)]
            if (self.root / a.path).is_file() and moves and moves[-1][0] == a.path:
                self.problems.append(f"{where}: {a.path} was renamed to {moves[-1][1]}, and a new {a.path} created "
                                     f"since; set the path of the file that was checked")
                continue
            if not (self.root / path).is_file():
                self.problems.append(f"{where}: {a.path} does not exist" + (f" (renamed to {path})" if path != a.path else ""))
                continue
            until, commit = self._blob_until(set(names), path, a.blob)
            if until is None:
                self.problems.append(f"{where}: the checked content of {a.path} ({a.blob[:7]}) is neither in the "
                                     f"history of this file on this branch nor its current content; run 'aisignoff attest' "
                                     f"again")
                continue
            pieces = pieces_from_values(a.values, f"{a.filename} attestation [{a.index}]", "attestation")
            out.setdefault(path, []).append((until, commit, pieces))
        return out

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
        if not (self.root / path).is_file():
            for old, new in renames:
                if old == names[-1] and new not in names:
                    names.append(new)
        return names

    def _blob_until(self, names: set[str], path: str, blob: str) -> tuple[int | None, str | None]:
        """Where the checked content was the attested file's content, under any of its names. The
        same content in another file doesn't count, so a copy can't extend an attestation to lines
        added since. The current file counts as newest (an attestation written before its commit):
        then every line is the checked content. On the default branch: the ordinal of the last
        commit that still had it. Only elsewhere (a merged branch, or the change that hasn't
        landed): the commit that wrote it there."""
        current = _git(self.root, "hash-object", "--", path, check=False)
        if current and current.strip() == blob:
            return self.newest, None
        if not self.order:
            return None, None
        log = ["log", "--no-abbrev", "--raw", "--no-renames", "--relative", "-z", "--format=%x1e%H", f"--find-object={blob}"]
        out = _git(self.root, log[0], "--first-parent", "--diff-merges=first-parent", *log[1:], self.base, check=False)
        if out is None:  # git older than 2.31
            out = _git(self.root, log[0], "--first-parent", *log[1:], self.base, check=False) or ""
        wrote, removed = self._find_blob(out, names, blob)
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
        until, commit, _ = attestation
        if until == self.newest:
            return True
        kind = origin[0]
        if kind == "frozen":
            return self.is_ancestor(self.snapshot.commit, commit) if commit else until >= self.frozen
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
        args = ["blame", "--porcelain", *self.blame_options] + (["--first-parent"] if first_parent else [])
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
        ("frozen", index of its declaration in the snapshot, or None) or
        ("landed", the commit that landed it, the commit that wrote it if that is another one)."""
        snapshot = self.snapshot
        if snapshot and snapshot.blob(path) == self.base_blobs.get(path):  # unchanged since the snapshot
            return [("frozen", snapshot.lookup(path, n)) for n in range(1, snapshot.lines(path) + 1)]
        if snapshot and snapshot.commit == self.base:  # a file the snapshot doesn't have
            data = _git(self.root, "cat-file", "blob", self.base_blobs[path], check=False) or ""
            return [("frozen", None)] * (data.count("\n") + (not data.endswith("\n")))
        stop = snapshot.commit if snapshot else None
        landed = self._blame(self.base, path, True, stop)
        merges = {sha for sha, _, stopped, _ in landed if not stopped and len(self.parents.get(sha, [])) > 1}
        written = None
        if need_writer or any(self._side(m)[0] for m in merges):
            written = self._blame(self.base, path, False, stop)
            if len(written) != len(landed):
                written = None
        out = []
        for n, (sha, line, stopped, name) in enumerate(landed):
            if stopped and stop and sha == stop:
                out.append(("frozen", snapshot.lookup(name.removeprefix(self.prefix), line)))
            elif stopped or sha not in self.order:
                out.append(("landed", None, None))  # a shallow boundary: older than anything we can see
            else:
                writer = written[n][0] if written and not written[n][2] else None
                out.append(("landed", sha, writer if writer != sha else None))
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
            return ("pending", writer)
        out = _git(self.root, "log", "-1", "--first-parent", "--format=%H", self.base, "--", old, check=False)
        sha = (out or "").strip()
        if sha not in self.order:
            return ("landed", None, None)
        if self.order[sha] <= self.frozen:
            return ("frozen", self.snapshot.lookup(old, 1))
        return ("landed", sha, None)

    def line_origins(self, path: str) -> list[tuple]:
        """Where each line of a file comes from: ("frozen", ...) and ("landed", ...) as in
        _base_origins, or ("pending", the commit of the change that wrote it, or None) for a line
        that isn't on the default branch."""
        if (self.root / path).is_symlink():  # one unit, as git sees it (never read what it points to)
            return [self._unit_origin(path)]
        try:
            data = (self.root / path).read_bytes()
        except OSError:
            data = b""
        if not data or b"\x00" in data[:BINARY_PROBE]:
            return [self._unit_origin(path)]
        lines = data.count(b"\n") + (not data.endswith(b"\n"))
        old, removed, added = self.changes.get(path, (path if path in self.base_blobs else None, [], []))
        if old is None:  # a new file: every line is the change's
            return [("pending", w) for w in self._writers(path, lines)]
        base = self._base_origins(old, any(commit for _, commit, _ in self.attestations.get(path, [])))
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
            writers = self._writers(path, lines)
            out = [o if o is not None else ("pending", writers[n]) for n, o in enumerate(out)]
        return out

    # ------------------------------------------------------------ resolution
    def resolve_lines(self, path: str, fallback: Declaration) -> list[Part]:
        """The parts of a file: runs of lines that share one combined declaration."""
        fb = {i: Piece(fallback.get(level), fallback.get(names), fallback.source, "file", tuple(fallback.problems))
              for i, (level, names) in enumerate(AXES) if fallback.get(level) is not None}
        attestations = self.attestations.get(path, [])
        keys: list[tuple] = []
        memo: dict[tuple, tuple] = {}
        for origin in self.line_origins(path):
            if origin not in memo:
                memo[origin] = self._line_pieces(origin, attestations, fb)
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

    def _line_pieces(self, origin: tuple, attestations: list, fb: dict[int, Piece]) -> tuple[tuple, bool]:
        """One piece per axis for the lines of one origin, and whether they are advisory."""
        attested = [pieces for a in attestations if self._covers(a, origin) for pieces in [a[2]]]
        kind = origin[0]
        if kind == "frozen":
            owner = self.snapshot.pieces[origin[1]] if origin[1] is not None else {}
            return self._combine(owner, None, attested, fb, None, "the snapshot"), False
        if kind == "landed":
            sha, writer = origin[1], origin[2]
            if sha is None:
                return self._combine({}, None, attested, fb, None, ""), False
            owner = self.commit_pieces(sha)
            required = None
            if self.config.history.undeclared == "error":
                required = 'required by [history] undeclared = "error"'
            elif self.since is not None and self.order[sha] > self.since:
                required = "required by [history] require-trailers-since"
            self._note_owner(sha, bool(owner), required is not None)
            hint = self._hint(sha, writer) if len(self.parents.get(sha, [])) > 1 else None
            return self._combine(owner, hint, attested, fb, required, self.describe(sha)), False
        # a line that isn't on the default branch yet
        writer = origin[1]
        method = self.config.history.merge_method
        own = self.commit_pieces(writer) if writer and len(self.parents.get(writer, [])) <= 1 else {}
        if self.declared is not None and method != "rebase":
            # the pull request's description will be the message of the commit that lands it
            hint = self._hint(None, writer) if method == "merge" else None
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
            return self._combine(own, None, attested, fb, required, who), False
        own = {i: replace(p, kind="branch") for i, p in own.items()}
        # nothing declares the change yet: what its commits say is shown, and fails nothing
        return self._combine(own, None, attested, fb, None, self.describe(writer) if writer else "this change",
                             waiting=True), bool(own)

    def _combine(self, owner: dict[int, Piece], hint: Piece | None, attested: list[dict[int, Piece]],
                 fb: dict[int, Piece], required: str | None, who: str, waiting: bool = False) -> tuple:
        """One piece per axis from a line's owner, the generation its writing commit says (hint),
        and the attestations that cover it. Generation: an attestation that gives it, else the
        hint (only next to an owner that declares something), else the owner's. Reviews: the
        highest of the owner's and the attestations', the later one on a tie; TODO is below every
        level. A1 (the generating session checked itself) doesn't reach a line whose G0 comes from
        somewhere else. An axis that nothing gives is missing when the owner declares another one,
        an error when a declaration is required, and the file-level declaration's otherwise."""
        problems = tuple(dict.fromkeys(x for p in owner.values() for x in p.problems))
        out: list[Piece | None] = []
        gen_from = None
        for i, (level, _) in enumerate(AXES):
            best = None
            given = [(n, pieces[i]) for n, pieces in enumerate(attested) if i in pieces]
            if i == 0:
                if given:
                    gen_from, best = given[-1]
                elif hint is not None and owner:
                    gen_from, best = "hint", hint
                elif i in owner:
                    gen_from, best = "owner", owner[i]
            else:
                found = ([("owner", owner[i])] if i in owner else []) + given
                if i == 2 and out[0] is not None and out[0].level == "G0":
                    # from the declaration that says G0 itself, G0 with A1 is invalid, and validate says so
                    self_checks = [t for t in found if t[1].level == "A1" and t[0] != gen_from]
                    found = [t for t in found if t[1].level != "A1" or t[0] == gen_from]
                    if not found and self_checks:
                        found = [(None, replace(self_checks[-1][1], level="A0", names=()))]
                if found:
                    best = max(enumerate(found), key=lambda t: (_level_value(t[1][1].level), t[0]))[1][1]
            if best is not None:
                best = replace(best, problems=tuple(dict.fromkeys(best.problems + problems)))
            elif owner:
                text = (f"{who} leaves {level} to the pull request" if waiting else
                        f"{who} declares levels, but no {level} (nor does an attestation)")
                best = Piece(None, (), who, "required", problems + (text,))
            elif required:
                best = Piece(None, (), who, "required", (f"{who} declares no {level} ({required})",))
            else:
                best = fb.get(i)
            out.append(best)
        return tuple(out)


def _level_value(level: str | None) -> int:
    """For comparing review levels: TODO (or nothing) below any level."""
    return int(level[1]) if level and len(level) == 2 and level[1].isdigit() else -1
