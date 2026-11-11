"""Line-level declarations from git history (the [history] table of SIGNOFF.toml).

Each line of a file takes, per axis, the newest of:

- the declaration of the commit that landed the line on the current branch: its trailers
  (AI-Generation, Human-Review, ... in the commit message), corrected by a [[commits]] entry.
  'git blame --first-parent' finds that commit, so a squash commit or the merge commit of a
  pull request carries the declaration of all its lines. For a merge commit, the commits of the
  merged branch fill the axes it leaves out;
- an [[attestations]] entry of the file whose content (a git blob) already contained the line:
  "this whole file was checked, as it was then".

Lines with neither, on an axis, fall back to the file-level declaration (SIGNOFF.toml
annotations and inline tags), so a repository without trailers reports what it did before.
With require-trailers-since, lines of newer commits must be declared by the commit instead.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .model import AXES, LEVEL_KEYS, LIST_KEYS, Declaration, canonical_key, validate

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


def parse_trailers(text: str, source: str) -> dict[int, Piece]:
    """Axis pieces from 'Key: value' trailer lines. Names without their level are ignored
    (Reviewed-by is a common trailer on its own); conflicting levels are a problem."""
    levels: dict[str, str] = {}
    names: dict[str, list[str]] = {k: [] for k in LIST_KEYS}
    problems = []
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        key = canonical_key(k)
        v = v.strip()
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
        self._branch_cache: dict[str, bool] = {}
        self._renames: list[tuple[str, str]] | None = None
        self._load_chain()
        self.newest = len(self.order) + 1  # uncommitted changes
        # files in HEAD, relative to root: the others are new, so all their lines are uncommitted
        self.committed = set((_git(self.root, "ls-tree", "-r", "-z", "--name-only", "HEAD", check=False) or "")
                             .split("\0")) - {""} if self.order else set()
        self.corrections = self._load_corrections()
        self.since = self._ordinal_of_setting(config.history.require_trailers_since)
        self.attestations = self._load_attestations()
        self.blame_options = ["-w", "--root"] + self._ignore_revs()
        # 'aisignoff diff --declare': the declaration of changes after declared_after that carry none
        self.declared = pieces_from_values(declared.as_dict(), "declared for this change", "declared") if declared else {}
        self.declared_after = self.newest
        if declared_after:
            if declared_after in self.order:
                self.declared_after = self.order[declared_after]
            elif self.declared:
                self.problems.append(f"--declare: {short(declared_after)} is not on the first-parent history of HEAD, "
                                     "so it's unclear which lines are new; the declaration was not applied")
                self.declared = {}

    # ------------------------------------------------------------ commits
    def _load_chain(self) -> None:
        out = _git(self.root, "log", "--first-parent", "--format=%H%x1f%P%x1f%s%x1f%(trailers:unfold,only)%x1e",
                   "HEAD", check=False)
        if out is None:  # no commit yet
            return
        records = [r.strip("\n") for r in out.split("\x1e") if r.strip("\n")]
        for i, record in enumerate(records):
            sha, parents, subject, trailers = (record.split("\x1f") + ["", "", ""])[:4]
            self.order[sha] = len(records) - i
            self.subjects[sha] = subject
            self.parents[sha] = parents.split()
            self._trailers[sha] = parse_trailers(trailers, self.describe(sha))

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
                self.problems.append(f"{where}: unknown commit {entry.commit}")
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
            out = _git(self.root, "log", "-1", "--format=%s%x1f%(trailers:unfold,only)", sha, check=False) or ""
            subject, _, trailers = out.partition("\x1f")
            self.subjects.setdefault(sha, subject.strip())
            self._trailers[sha] = parse_trailers(trailers, self.describe(sha))
        pieces = dict(self._trailers[sha])
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

    # ------------------------------------------------------------ attestations
    def _load_attestations(self) -> dict[str, list[tuple[int, dict[int, Piece]]]]:
        out: dict[str, list] = {}
        for a in self.config.attestations:
            where = f"{a.filename} [[attestations]] entry {a.index}"
            names = self._names_since(a.path)  # the attested file's names, the current one last
            path = names[-1]
            if not (self.root / path).is_file():
                self.problems.append(f"{where}: {a.path} does not exist" + (f" (renamed to {path})" if path != a.path else ""))
                continue
            ordinal = self._blob_ordinal(set(names), path, a.blob)
            if ordinal is None:
                self.problems.append(f"{where}: the checked content of {a.path} ({a.blob[:7]}) is neither in the "
                                     f"history of this file on this branch nor its current content; run 'aisignoff attest' "
                                     f"again")
                continue
            pieces = pieces_from_values(a.values, f"{a.filename} attestation [{a.index}]", "attestation")
            out.setdefault(path, []).append((ordinal, pieces))
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

    def _blob_ordinal(self, names: set[str], path: str, blob: str) -> int | None:
        """When the checked content last appeared at the attested file on this branch (ordinal of
        that commit), under any of its names. The same content in another file doesn't count, so
        a copy can't extend an attestation to lines added since. The current file counts as newest
        (an attestation written before its commit): then every line is the checked content."""
        current = _git(self.root, "hash-object", "--", path, check=False)
        if current and current.strip() == blob:
            return self.newest
        if self.order:
            args = ["log", "--first-parent", "--no-abbrev", "--raw", "--no-renames", "--relative", "-z",
                    "--format=%x1e%H", f"--find-object={blob}", "HEAD"]
            out = _git(self.root, args[0], "--diff-merges=first-parent", *args[1:], check=False)
            if out is None:  # git older than 2.31
                out = _git(self.root, *args, check=False) or ""
            for record in out.split("\x1e"):
                fields = record.strip("\n\0").split("\0")
                sha = fields[0].strip()
                # with -z: ":meta" and the path alternate
                for meta, name in zip(fields[1::2], fields[2::2]):
                    meta = meta.split()
                    if len(meta) >= 4 and meta[3] == blob and name in names and sha in self.order:
                        return self.order[sha]
        return None

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
        needs_branch = {c for c in set(landing) if c and len(self.parents.get(c, [])) > 1
                        and len(self.commit_pieces(c)) < len(AXES) and self._branch_declares(c)}
        original = self._blame(path, first_parent=False) if needs_branch else None
        if original is not None and len(original) != len(landing):
            original = None
        if original is not None:
            original = [o if l in needs_branch else None for l, o in zip(landing, original)]
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
        if commit == UNCOMMITTED:
            ordinal, own = self.newest, {}
        elif commit is None:  # a shallow boundary: older than anything we can see
            ordinal, own = 0, {}
        else:
            ordinal = self.order.get(commit, 0)
            own = self.commit_pieces(commit)
            if orig and orig != commit:  # the merge commit is newer: the branch commit only fills its gaps
                own = dict(own)
                for i, p in self.commit_pieces(orig).items():
                    own.setdefault(i, Piece(p.level, p.names, p.source, "branch", p.problems))
        out = []
        for i, (level, _) in enumerate(AXES):
            best, best_rank = None, None
            p = own.get(i)
            if p is None and self.declared.get(i) and ordinal > self.declared_after:
                p = self.declared[i]
            if p is not None:
                best, best_rank = p, (ordinal, 0)
            for a_ordinal, pieces in attestations:
                if i in pieces and a_ordinal >= ordinal and (best_rank is None or (a_ordinal, 1) > best_rank):
                    best, best_rank = pieces[i], (a_ordinal, 1)
            if best is None:
                if self.since is not None and commit not in (None, UNCOMMITTED) and ordinal > self.since \
                        and not PREVIEW_MERGE.match(self.subjects.get(commit, "")):
                    best = Piece(None, (), self.describe(commit), "required",
                                 (f"{self.describe(commit)} has no {level} trailer "
                                  f"(required by [history] require-trailers-since)",))
                else:
                    best = fb.get(i)
            out.append(best)
        return tuple(out)
