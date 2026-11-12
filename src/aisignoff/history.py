"""Line-level declarations from git history (the [history] table of SIGNOFF.toml).

The declarations around a line:

- the commit that landed it on the current branch ('git blame --first-parent'): a direct commit,
  a squash commit, or the merge commit of a pull request. Its message declares the levels with
  "Key: value" lines (AI-Generation, Human-Review, ...) or the ticked checkboxes of a pull request
  template; a [[commits]] entry corrects it;
- for a merge commit, the merges inside it that brought the line in and the commit of the merged
  branch that wrote it;
- an [[attestations]] entry of the file whose content (a git blob) already contained the line.

Generation takes the most specific of them (attestation, branch commit, inner merge, landing
commit); a review takes the highest level among them, since each saw the line as it is. Lines
that none of them declares anything for fall back to the file-level declaration (SIGNOFF.toml
annotations and inline tags), so a repository without declared commits reports what it did
before; an axis left out where others are declared is missing. With require-trailers-since,
lines of newer commits must be declared.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path

from .model import AXES, LEVEL_KEYS, LIST_KEYS, TODO, Declaration, canonical_key, validate

UNCOMMITTED = "0" * 40
# the merge preview a pull request's CI run checks out (refs/pull/N/merge): its lines are the
# pull request's, which isn't merged yet, so require-trailers-since doesn't apply to it
PREVIEW_MERGE = re.compile(r"^Merge [0-9a-f]{40} into [0-9a-f]{40}$")
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
    kind: str  # commit | branch | attestation | file | declared | required
    problems: tuple[str, ...] = ()


@dataclass
class Part:
    """The lines of a file that share one combined declaration."""

    declaration: Declaration
    errors: list[str]
    lines: int
    runs: list[list[int]]  # [first, last] line numbers, 1-based and inclusive
    kinds: tuple[str | None, ...]  # per axis: where its level comes from (None: nowhere)


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
    for line in _prose_lines(text):
        m = _KEY_LINE.match(line)
        if not m:
            continue
        key, v = canonical_key(m.group(1)), m.group(2)
        if key is None or not v:
            continue
        if key in LEVEL_KEYS:
            if key in levels and levels[key] != v:
                problems.append(f"{source} has conflicting {key} trailers ({levels[key]}, {v})")
            levels[key] = v
        elif v not in names[key]:
            names[key].append(v)
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
    blocks not at all. Nothing is returned without a ticked level."""
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
    if not any(levels.values()):
        return {}
    problems = []
    if len(levels["G"]) > 1:
        problems.append(f"{source} ticks more than one generation level ({', '.join(levels['G'])})")
    out = {}
    names = {"G": tuple(models), "H": (author,) if author else ()}
    if "A" in seen and not levels["A"]:
        levels["A"] = ["A0"]  # "leave all unticked for A0"
    for i, (letter, _) in enumerate(zip("GHA", AXES)):
        if not levels[letter]:
            continue
        top = max(levels[letter])
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


class History:
    """Resolves the declaration of each line of a project's files from git history."""

    def __init__(self, root: Path, config, declared: Declaration | None = None, declared_after: str | None = None):
        self.root = Path(root)
        self.config = config
        self.policy = config.policy
        self.problems: list[str] = []
        self.order: dict[str, int] = {}  # first-parent commits: sha -> ordinal (1 = oldest)
        self.subjects: dict[str, str] = {}
        self.parents: dict[str, list[str]] = {}
        self._trailers: dict[str, dict[int, Piece]] = {}
        self._both: dict[str, str] = {}  # commits with trailers and checkboxes: the problem
        self._sides: dict[str, set[str]] = {}  # merge -> the commits it brought in
        self._inner: dict[str, list[str]] = {}  # landing merge -> the merges inside it
        self._ancestor: dict[tuple[str, str], bool] = {}
        # (source, axis, level) -> the landing piece it outranks: reviews raised from inside a pull request
        self.raised: dict[tuple[str, str, str], Piece] = {}
        self._branch_cache: dict[str, bool] = {}
        self._renames: list[tuple[str, str]] | None = None
        self._load_chain()
        self.newest = len(self.order) + 1  # uncommitted changes
        self.head = max(self.order, key=self.order.get) if self.order else None
        # files in HEAD, relative to root: the others are new, so all their lines are uncommitted
        self.committed = set((_git(self.root, "ls-tree", "-r", "-z", "--name-only", "HEAD", check=False) or "")
                             .split("\0")) - {""} if self.order else set()
        self.corrections = self._load_corrections()
        self.since = self._ordinal_of_setting(config.history.require_trailers_since)
        self.attestations = self._load_attestations()
        self.blame_options = (["-w"] if config.history.ignore_whitespace else []) + ["--root"] + self._ignore_revs()
        # 'aisignoff diff --declare': the declaration of changes after declared_after that carry none
        self.declared = pieces_from_values(declared.as_dict(), "declared for this change", "declared") if declared else {}
        # the commits of HEAD's first-parent chain that aren't in declared_after: the change being declared
        # (a branch that merged the base meanwhile has the base as the second parent of that merge)
        self.unlanded: set[str] = set()
        self.base: str | None = None
        self._base_chain: list[str] | None = None
        if declared_after and self.declared:
            out = _git(self.root, "rev-list", "--first-parent", "HEAD", f"^{declared_after}", check=False) \
                if self.order and self.is_ancestor(declared_after, "HEAD") else None
            if out is None:
                self.problems.append(f"--declare: {short(declared_after)} is not in the first-parent history of HEAD "
                                     "or its merges, so it's unclear which lines are new; the declaration was not applied")
                self.declared = {}
            else:
                self.unlanded = set(out.split())
                self.base = self._resolve(declared_after)

    # ------------------------------------------------------------ commits
    def _load_chain(self) -> None:
        out = _git(self.root, "log", "--first-parent", f"--format={self.FORMAT}", "HEAD", check=False)
        if out is None:  # no commit yet
            return
        records = _records(out)
        for i, (sha, parents, subject, author, message) in enumerate(records):
            self.order[sha] = len(records) - i
            self.subjects[sha] = subject
            self.parents[sha] = parents.split()
            self._trailers[sha] = self._declaration(sha, author, message)

    # hash, parents, subject, author and message, each ended by NUL, which a commit message can't
    # contain (unlike any other separator, so a message can't pass for another commit's record)
    FORMAT = "%H%x00%P%x00%s%x00%an <%ae>%x00%B%x00"

    def _declaration(self, sha: str, author: str, message: str) -> dict[int, Piece]:
        """A commit's own declaration: its 'Key: value' lines, or the ticked checkboxes of a pull
        request template in its message (the subject line aside). One or the other: a commit
        with both is a problem until a [[commits]] entry settles it (both count meanwhile, the
        lines where they overlap)."""
        body = message.split("\n", 1)[1] if "\n" in message else ""
        from_trailers = parse_trailers(body, self.describe(sha))
        from_boxes = parse_checkboxes(body, author.strip(), self.describe(sha))
        if from_trailers and from_boxes:
            self._both[sha] = (f"{self.describe(sha)} declares levels both as trailers and as ticked checkboxes; "
                               "use one of them, or settle it with a [[commits]] entry")
        return {**from_boxes, **from_trailers}

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
            out.setdefault(sha, {}).update(pieces_from_values(entry.values, source, "commit"))
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
            self.problems.append(f"[history] require-trailers-since: {rev} is not a commit of this branch")
            return None
        return self.order[sha]

    def commit_pieces(self, sha: str) -> dict[int, Piece]:
        """The declaration of a commit: its trailers, corrected axis by axis by [[commits]]."""
        if sha not in self._trailers:  # a commit of a merged branch
            out = _git(self.root, "log", "-1", f"--format={self.FORMAT}", sha, check=False) or ""
            _, parents, subject, author, message = (_records(out) or [("", "", "", "", "")])[0]
            self.subjects.setdefault(sha, subject.strip())
            self.parents.setdefault(sha, parents.split())
            self._trailers[sha] = self._declaration(sha, author, message)
        pieces = dict(self._trailers[sha])
        if sha in self._both and sha not in self.corrections:
            pieces = {i: replace(p, problems=p.problems + (self._both[sha],)) for i, p in pieces.items()}
        pieces.update(self.corrections.get(sha, {}))
        return pieces

    def _branch_declares(self, merge: str) -> bool:
        """Whether a commit of the branch that a merge commit merged declares anything."""
        if merge not in self._branch_cache:
            parents = self.parents.get(merge, [])
            found = False
            if len(parents) > 1:
                out = _git(self.root, "rev-list", f"{parents[0]}..{merge}", check=False) or ""
                found = any(self.commit_pieces(s) for s in out.split() if s != merge)
            self._branch_cache[merge] = found
        return self._branch_cache[merge]

    def is_ancestor(self, a: str, b: str) -> bool:
        if (a, b) not in self._ancestor:
            try:
                r = subprocess.run(["git", "-C", str(self.root), "merge-base", "--is-ancestor", a, b],
                                   capture_output=True)
                self._ancestor[(a, b)] = r.returncode == 0
            except FileNotFoundError:
                raise HistoryError("git is not installed")
        return self._ancestor[(a, b)]

    def side(self, merge: str) -> set[str]:
        """The commits a merge commit brought in (those of its other parents)."""
        if merge not in self._sides:
            parents = self.parents.get(merge) or (_git(self.root, "rev-parse", f"{merge}^@", check=False) or "").split()
            exclude = [f"^{parents[0]}"] if parents else []
            out = _git(self.root, "rev-list", merge, *exclude, check=False) or ""
            self._sides[merge] = set(out.split()) - {merge}
        return self._sides[merge]

    def inner_merges(self, landing: str) -> list[str]:
        """The merge commits a landing merge brought in, innermost first."""
        if landing not in self._inner:
            parents = self.parents.get(landing, [])
            out = (_git(self.root, "rev-list", "--merges", landing, f"^{parents[0]}", check=False) or "") if parents else ""
            merges = [m for m in out.split() if m != landing]
            self._inner[landing] = sorted(merges, key=lambda m: len(self.side(m)))
        return self._inner[landing]

    def is_preview(self, sha: str | None) -> bool:
        """Whether a commit is the merge preview of a pull request's CI run (refs/pull/N/merge):
        HEAD, a merge of two parents, with GitHub's subject."""
        if os.environ.get("GITHUB_EVENT_NAME") == "push":  # a push to a branch is never a preview
            return False
        return bool(sha) and sha == self.head and len(self.parents.get(sha, [])) == 2 \
            and bool(PREVIEW_MERGE.match(self.subjects.get(sha, "")))

    def _rebase_preview(self) -> bool:
        """A merge preview of a pull request that will land by rebase: its commits land themselves."""
        return self.config.history.merge_method == "rebase" and self.is_preview(self.head)

    def chain(self, commit: str, orig: str | None) -> list[tuple[str, dict[int, Piece]]]:
        """The commits that declare a line, outermost (latest) first, each with its declaration:
        the commit that landed it, the merges inside it that brought the line in, and the commit
        of a merged branch that wrote it."""
        members = [commit]
        if orig and orig != commit and len(self.parents.get(commit, [])) > 1 and (
                self._branch_declares(commit) or (self._rebase_preview() and commit == self.head)):
            inner = [m for m in self.inner_merges(commit) if orig in self.side(m)]
            members += list(reversed(inner)) + [orig]  # outermost first
        return [(m, self.commit_pieces(m)) for m in members]

    # ------------------------------------------------------------ attestations
    def _load_attestations(self) -> dict[str, list[tuple[int, str | None, dict[int, Piece]]]]:
        """Per file: (ordinal, commit, pieces) of each attestation. The commit is set when the checked
        content is on a merged branch only (a pull request whose file main changed meanwhile): then
        the attestation covers the lines whose original commit the checked content contained."""
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
            ordinal, commit = self._blob_ordinal(set(names), path, a.blob)
            if ordinal is None:
                self.problems.append(f"{where}: the checked content of {a.path} ({a.blob[:7]}) is neither in the "
                                     f"history of this file on this branch nor its current content; run 'aisignoff attest' "
                                     f"again")
                continue
            pieces = pieces_from_values(a.values, f"{a.filename} attestation [{a.index}]", "attestation")
            out.setdefault(path, []).append((ordinal, commit, pieces))
        return out

    def renames(self) -> list[tuple[str, str]]:
        """(old, new) paths relative to root of the renames on this branch, oldest first,
        then those not committed yet."""
        if self._renames is None:
            rows: list[str] = []
            if self.order:
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

    def _blob_ordinal(self, names: set[str], path: str, blob: str) -> tuple[int | None, str | None]:
        """When the checked content last appeared at the attested file (ordinal of that commit on
        this branch), under any of its names. The same content in another file doesn't count, so a
        copy can't extend an attestation to lines added since. The current file counts as newest
        (an attestation written before its commit): then every line is the checked content. Content
        that only a merged branch had (main changed the file meanwhile) gives the ordinal of the
        merge and that branch's commit."""
        current = _git(self.root, "hash-object", "--", path, check=False)
        if current and current.strip() == blob:
            return self.newest, None
        if not self.order:
            return None, None
        base = ["log", "--no-abbrev", "--raw", "--no-renames", "--relative", "-z", "--format=%x1e%H",
                f"--find-object={blob}", "HEAD"]
        out = _git(self.root, base[0], "--first-parent", "--diff-merges=first-parent", *base[1:], check=False)
        if out is None:  # git older than 2.31
            out = _git(self.root, base[0], "--first-parent", *base[1:], check=False) or ""
        for sha in self._find_blob(out, names, blob):
            if sha in self.order:
                return self.order[sha], None
        for sha in self._find_blob(_git(self.root, *base, check=False) or "", names, blob):
            landing = self._landing(sha)
            if landing:
                return self.order[landing], sha
        return None, None

    @staticmethod
    def _find_blob(out: str, names: set[str], blob: str) -> list[str]:
        """The commits of 'git log --raw -z' output that wrote the blob at one of the names, newest first."""
        found = []
        for record in out.split("\x1e"):
            fields = record.strip("\n\0").split("\0")
            sha = fields[0].strip()
            # with -z: ":meta" and the path alternate
            for meta, name in zip(fields[1::2], fields[2::2]):
                meta = meta.split()
                if len(meta) >= 4 and meta[3] == blob and name in names:
                    found.append(sha)
                    break
        return found

    def _base_landing(self, sha: str) -> str:
        """The first commit of the base's first-parent chain (aisignoff diff --declare) that contains a commit."""
        if self._base_chain is None:
            self._base_chain = (_git(self.root, "rev-list", "--first-parent", "--reverse", self.base,
                                     check=False) or "").split()
        chain = self._base_chain
        lo, hi = 0, len(chain)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.is_ancestor(sha, chain[mid]):
                hi = mid
            else:
                lo = mid + 1
        return chain[lo] if lo < len(chain) else sha

    def _landing(self, sha: str) -> str | None:
        """The first commit of this branch's first-parent chain that contains a commit."""
        chain = sorted(self.order, key=self.order.get)
        lo, hi = 0, len(chain)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.is_ancestor(sha, chain[mid]):
                hi = mid
            else:
                lo = mid + 1
        return chain[lo] if lo < len(chain) else None

    # ------------------------------------------------------------ blame
    def _blame(self, path: str, first_parent: bool) -> list[str | None]:
        """The commit of each line (None: a shallow boundary) of a file that is in HEAD."""
        args = ["blame", "--porcelain", *self.blame_options] + (["--first-parent"] if first_parent else [])
        out = _git(self.root, *args, "--", path)
        commits: list[str | None] = []
        current, boundary = None, set()
        for row in out.split("\n"):
            if row.startswith("\t"):
                commits.append(None if current in boundary else current)
                continue
            head = row.split(" ", 1)[0]
            if len(head) in (40, 64) and " " in row and row.split(" ")[1].isdigit():
                current = head
            elif row == "boundary":
                boundary.add(current)
        return commits

    def _whole_file_commit(self, path: str) -> str | None:
        """For binary and empty files: the commit that last changed the file, or UNCOMMITTED."""
        if _git(self.root, "status", "--porcelain", "--", path, check=False):
            return UNCOMMITTED
        out = _git(self.root, "log", "-1", "--first-parent", "--format=%H", "HEAD", "--", path, check=False)
        return out.strip() or UNCOMMITTED if out is not None else UNCOMMITTED

    def line_commits(self, path: str) -> tuple[list[str | None], list[str | None] | None]:
        """Landing commit of each line, and (if needed) the original commit of each line."""
        if (self.root / path).is_symlink():  # one unit, as git sees it (never read what it points to)
            return [self._whole_file_commit(path)], None
        try:
            data = (self.root / path).read_bytes()
        except OSError:
            data = b""
        if not data or b"\x00" in data[:BINARY_PROBE]:
            return [self._whole_file_commit(path)], None
        if path not in self.committed:  # a new file: every line is uncommitted
            n = data.count(b"\n") + (not data.endswith(b"\n"))
            return [UNCOMMITTED] * n, None
        landing = self._blame(path, first_parent=True)
        needs_branch = self._rebase_preview() or any(
            c in self.unlanded and len(self.parents.get(c, [])) > 1 for c in set(landing)) or any(
            c and len(self.parents.get(c, [])) > 1 and self._branch_declares(c) for c in set(landing))
        off_chain = any(commit for _, commit, _ in self.attestations.get(path, []))
        original = self._blame(path, first_parent=False) if needs_branch or off_chain else None
        if original is not None and len(original) != len(landing):
            original = None
        return landing, original

    # ------------------------------------------------------------ resolution
    def resolve_lines(self, path: str, fallback: Declaration) -> list[Part]:
        """The parts of a file: runs of lines that share one combined declaration."""
        fb = {i: Piece(fallback.get(level), fallback.get(names), fallback.source, "file", tuple(fallback.problems))
              for i, (level, names) in enumerate(AXES) if fallback.get(level) is not None}
        attestations = self.attestations.get(path, [])
        landing, original = self.line_commits(path)
        keys: list[tuple] = []
        memo: dict[tuple, tuple] = {}
        for n, commit in enumerate(landing):
            orig = original[n] if original else None
            k = (commit, orig)
            if k not in memo:
                memo[k] = self._line_pieces(commit, orig, attestations, fb)
            keys.append(memo[k])

        parts: dict[tuple, Part] = {}
        previous = None
        for n, key in enumerate(keys, start=1):
            part = parts.get(key)
            if part is None:
                d = combine(key)
                errors = validate(d, self.policy)
                missing = {f"missing {level}" for (level, _), p in zip(AXES, key) if p is not None and p.kind == "required"}
                errors = [e for e in errors if e not in missing]
                part = parts[key] = Part(d, errors, 0, [], tuple(p.kind if p else None for p in key))
            part.lines += 1
            if key == previous:
                part.runs[-1][1] = n
            else:
                part.runs.append([n, n])
            previous = key
        return sorted(parts.values(), key=lambda p: p.runs[0][0])

    def _line_pieces(self, commit, orig, attestations, fb) -> tuple:
        """One piece per axis for the lines that one commit landed (and, inside a merge, another
        commit wrote). Generation: the most specific declaration (an attestation, the branch commit
        that wrote the line, the merges it came through, innermost first, the commit that landed
        it). Reviews: the highest level any of them declares: each of them saw the line as it is,
        and a later review of the whole doesn't undo a closer one (a level that is too high is
        corrected with a [[commits]] entry). Two exceptions: A1 (the generating session checked
        itself) doesn't reach lines that a human wrote, and a TODO of the landing commit (or the
        pull request) wins. Lines that none of them declares at all take the file-level
        declaration; an axis left out by a declaration that gives others is missing.

        A pull request that hasn't landed yet (its merge preview, or the commits after the base
        with 'aisignoff diff --declare') is resolved as it will land: the declaration given with
        --declare stands for its merge or squash commit, and [history] merge-method says which of
        its commits will still be there."""
        method = self.config.history.merge_method
        preview = self.is_preview(commit)
        if commit == UNCOMMITTED:
            ordinal, members = self.newest, []
        elif commit is None:  # a shallow boundary: older than anything we can see
            ordinal, members = 0, []
        else:
            if commit in self.unlanded and orig and orig != commit and self.is_ancestor(orig, self.base):
                # a line of the base that a merge of it into the branch brought in: it isn't part of the
                # change, so it resolves as on the base, by the commit that landed it there
                commit = self._base_landing(orig)
                self.commit_pieces(commit)
            ordinal = self.order.get(commit, 0)
            members = self.chain(commit, orig)
        new = commit == UNCOMMITTED or commit in self.unlanded  # part of the change given with --declare
        unlanded = preview or (bool(self.declared) and new)
        declare = bool(self.declared) and new and method != "rebase"
        if unlanded:
            if preview:
                members = members[1:]  # the preview merge itself won't land
            if method == "squash":  # the branch's commits won't be there, only the squash commit
                members = []
        landing_kind = "commit" if not unlanded or method == "rebase" else "branch"
        layers = []  # (rank, kind, pieces), latest first
        for n, (sha, pieces) in enumerate(members):
            layers.append((len(members) - n, landing_kind if n == 0 else "branch", pieces))
        if declare:
            layers.insert(0, (len(members) + 1, "declared", dict(self.declared)))
        landing = layers[0][2] if layers and (declare or not unlanded) else {}
        attested = []
        for a_ordinal, a_commit, pieces in attestations:
            covers = (orig not in (None, UNCOMMITTED) and self.is_ancestor(orig, a_commit)) if a_commit \
                else a_ordinal >= ordinal
            if covers:
                attested.append(((a_ordinal, len(attested)), pieces))
        problems = tuple(dict.fromkeys(x for _, _, pieces in layers for p in pieces.values() for x in p.problems))
        declares = any(pieces for _, _, pieces in layers)
        # a pull request's description that is still to come (its merge preview, without --declare)
        awaiting = unlanded and not declare and method != "rebase"
        lands = orig if unlanded and method == "rebase" and orig else commit  # the commit that will carry the line
        out = []
        gen_layer = None  # where generation came from: ("a", rank) for an attestation, ("l", rank) for a commit layer
        for i, (level, _) in enumerate(AXES):
            from_attestation = [(rank, pieces[i]) for rank, pieces in attested if i in pieces]
            from_layers = [(rank, kind, pieces[i]) for rank, kind, pieces in layers if i in pieces]
            best = None
            if i == 0:  # generation: the most specific
                if from_attestation:
                    rank, best = max(from_attestation, key=lambda t: t[0])
                    gen_layer = ("a", rank)
                elif from_layers:  # a level beats TODO
                    filled = [t for t in from_layers if _level_value(t[2].level) >= 0] or from_layers
                    rank, kind, p = min(filled, key=lambda t: t[0])
                    best = replace(p, kind=kind)
                    gen_layer = ("l", rank)
            elif i in landing and landing[i].level == TODO and not any(
                    _level_value(p.level) >= 0 for _, p in from_attestation):
                # the pull request isn't reviewed yet (a later review of the file, an attestation, counts)
                best = replace(landing[i], kind=layers[0][1])
            else:  # reviews: the highest; the later one on a tie
                found = [((_level_value(p.level), 1, rank), p) for rank, p in from_attestation]
                found += [((_level_value(p.level), 0, (rank, 0)), replace(p, kind=kind)) for rank, kind, p in from_layers]
                if i == 2 and out[0] is not None and out[0].level == "G0":
                    # A1 is the generating session checking itself: there is none for hand-written lines.
                    # From the declaration that says G0 itself, G0 with A1 is invalid, and validate says so.
                    def same(key):
                        return gen_layer == ("a", key[2]) if key[1] else gen_layer == ("l", key[2][0])
                    self_checks = [t for t in found if t[1].level == "A1" and not same(t[0])]
                    found = [t for t in found if t[1].level != "A1" or same(t[0])]
                    if not found and self_checks:
                        p = max(self_checks, key=lambda t: t[0])[1]
                        found = [((0, 0, 0), replace(p, level="A0", names=()))]
                if found:
                    best = max(found, key=lambda t: t[0])[1]
                    self._note_raised(i, best, landing)
            if best is not None:
                best = replace(best, problems=tuple(dict.fromkeys(best.problems + problems)))
            elif declares and not awaiting:
                who = self.describe(lands) if lands not in (None, UNCOMMITTED) and members \
                    else "the declaration of this change"
                best = Piece(None, (), who, "required",
                             problems + (f"{who} declares levels, but no {level} (nor does a pull request "
                                         f"or commit around it)",))
            elif self.since is not None and commit not in (None, UNCOMMITTED) and ordinal > self.since \
                    and not awaiting:
                best = Piece(None, (), self.describe(lands), "required",
                             (f"{self.describe(lands)} has no {level} trailer "
                              f"(required by [history] require-trailers-since)",))
            else:
                best = fb.get(i)
                if best is not None and problems:
                    best = replace(best, problems=tuple(dict.fromkeys(best.problems + problems)))
            out.append(best)
        return tuple(out)

    def warnings(self) -> list[str]:
        """Reviews raised from inside a pull request: they count, but often a commit (or its agent)
        claimed a review before anyone did it, so lint names them."""
        out = []
        for (source, axis, level), mine in sorted(self.raised.items()):
            sha = source.split()[1] if source.startswith("commit ") else None
            if mine.level is None:
                out.append(f"{source} declares {axis} {level}, which {mine.source} doesn't declare; it counts for "
                           f"the lines it wrote" + (f'; if nobody did that review, correct it: [[commits]] commit = '
                                                    f'"{sha}" with the right {axis}' if sha else ""))
                continue
            fix = (f'; if that is too high, correct it: [[commits]] commit = "{sha}" {axis} = "{mine.level}"'
                   if sha else "")
            out.append(f"{source} declares {axis} {level}, higher than {mine.source} ({mine.level}); "
                       f"the higher level counts for the lines it wrote{fix}")
        return out

    def _note_raised(self, i: int, best: Piece, landing: dict[int, Piece]) -> None:
        """A review that a commit inside a pull request declares higher than the pull request itself."""
        if not landing or best.kind == "attestation" or "[[commits]]" in best.source:  # a correction is deliberate
            return
        mine = landing.get(i)
        if mine is None:  # the pull request declares levels, but not this one: only the commit inside does
            some = next(iter(landing.values()))
            mine = Piece(None, (), some.source, some.kind)
        if best is mine or mine.level == best.level:
            return
        if _level_value(best.level) > _level_value(mine.level):
            self.raised.setdefault((best.source, AXES[i][0], best.level), mine)


def _level_value(level: str | None) -> int:
    """For comparing review levels: TODO (or nothing) below any level."""
    return int(level[1]) if level and len(level) == 2 and level[1].isdigit() else -1
