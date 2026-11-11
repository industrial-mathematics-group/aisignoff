"""Finding the files of a project and resolving each file's declaration."""
from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import inline
from .config import FILENAME, LEGACY_FILENAME, Config, load
from .model import AXES, Declaration, validate

ALWAYS_SKIPPED = {FILENAME, LEGACY_FILENAME}


class ProjectError(Exception):
    pass


def _inside_git(root: Path) -> bool:
    return any((p / ".git").exists() for p in (root, *root.parents))


def list_files(root: Path) -> list[str]:
    """Files of the project, relative to root with '/' separators.

    In a git work tree: tracked files plus untracked files that are not ignored
    (so .gitignore is respected). Outside git: every file below root except .git/.
    """
    if _inside_git(root):
        try:
            out = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                capture_output=True, check=True,
            ).stdout
        except FileNotFoundError:
            raise ProjectError("this is a git repository, but git is not installed, so .gitignore "
                               "cannot be respected")
        except subprocess.CalledProcessError as e:
            message = e.stderr.decode("utf-8", "replace").strip()
            raise ProjectError(f"git ls-files failed: {message}")
        names = sorted({n for n in out.decode("utf-8", "surrogateescape").split("\0") if n})
        return [n for n in names if (root / n).is_file() or (root / n).is_symlink()]
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for f in filenames:
            found.append(Path(dirpath, f).relative_to(root).as_posix())
    return sorted(found)


@dataclass
class FileResult:
    """The declaration of one file. With [history], also its parts: runs of lines that share one
    declaration (then 'declaration' is the part with the most lines, 'errors' those of all parts)."""

    path: str
    declaration: Declaration
    errors: list[str]
    parts: list | None = None  # list[history.Part] in history mode
    line_parts: list[int] | None = field(default=None, repr=False)  # part index of each line


def line_count(root: Path, path: str) -> int:
    """Lines of a file (binary files count as one line, unreadable ones as zero)."""
    try:
        data = (root / path).read_bytes()
    except OSError:
        return 0
    if b"\x00" in data[:16384]:
        return 1
    return max(1, data.count(b"\n"))


def weighted_parts(root: Path, result: FileResult, weight: str):
    """(declaration, errors, weight) per part of a file. Weight "lines" counts lines; "files"
    counts the file as 1, split by the line shares of its parts."""
    if result.parts is None:
        w = 1 if weight == "files" else line_count(root, result.path)
        return [(result.declaration, result.errors, w)]
    total = sum(p.lines for p in result.parts) or 1
    return [(p.declaration, p.errors, p.lines if weight == "lines" else p.lines / total) for p in result.parts]


def _history_result(path: str, parts: list) -> FileResult:
    from .history import format_runs
    main = max(parts, key=lambda p: p.lines)
    errors = []
    for p in parts:
        prefix = "" if len(parts) == 1 else format_runs(p.runs) + ": "
        errors += [prefix + e for e in p.errors]
    index = [0] * sum(p.lines for p in parts)
    for i, p in enumerate(parts):
        for a, b in p.runs:
            index[a - 1:b] = [i] * (b - a + 1)
    return FileResult(path, main.declaration, errors, parts, index)


def _merge_closest(own: Declaration, fallback: Declaration | None) -> Declaration:
    """Inline tags win per axis; a missing axis is taken from SIGNOFF.toml.

    The axes are generation (AI-Generation + Assisted-by), human review
    (Human-Review + Reviewed-by) and AI review (AI-Review + AI-Reviewed-by). An axis counts
    as given inline when its level line is present.
    """
    stray = [f"inline {names} without an inline {level} line"
             for level, names in AXES if own.get(level) is None and own.get(names)]
    if stray:
        own = replace(own, problems=own.problems + stray)
    if fallback is None:
        return own
    updates = {}
    for level, names in AXES:
        if own.get(level) is None and fallback.get(level) is not None:
            updates[Declaration._FIELDS[level]] = fallback.get(level)
            updates[Declaration._FIELDS[names]] = fallback.get(names)
    if not updates:
        return own
    return replace(own, **updates, source=f"inline + {fallback.source}", problems=list(own.problems))


def resolve(root: Path, config: Config, path: str) -> Declaration:
    """Declaration of one file. With precedence "closest" (default), inline tags win and
    SIGNOFF.toml fills a missing axis; with "override", the annotation alone counts."""
    annotation = config.match(path)
    if annotation is not None and annotation.precedence == "override":
        return annotation.declaration()
    found = inline.parse(root / path)
    if found is not None:
        return _merge_closest(found, annotation.declaration() if annotation else None)
    if annotation is not None:
        return annotation.declaration()
    return Declaration()


class Project:
    def __init__(self, root: Path):
        root = Path(root)
        if not root.is_dir():
            raise ProjectError(f"project root {root} is not a directory")
        self.root = root.resolve()
        self.config = load(self.root)
        self.history_problems: list[str] = []
        self.history_used = False

    def history_wanted(self) -> bool:
        return self.config.history.enabled

    def files(self) -> list[str]:
        return [f for f in list_files(self.root)
                if f not in ALWAYS_SKIPPED and not self.config.is_excluded(f)]

    def results(self, declared: Declaration | None = None, declared_after: str | None = None,
                quiet: bool = False) -> list[FileResult]:
        """Every file's declaration. With [history] enabled (and full git history at hand), line
        by line; 'declared' then declares the changes after 'declared_after' that carry no
        declaration of their own (aisignoff diff --declare)."""
        files = self.files()
        fallback = {f: resolve(self.root, self.config, f) for f in files}
        history = self._history(declared, declared_after, quiet)
        if history is None:
            return [FileResult(f, d, validate(d, self.config.policy)) for f, d in fallback.items()]

        def one(f: str) -> FileResult:
            annotation = self.config.match(f)
            if annotation is not None and annotation.precedence == "override":
                d = fallback[f]
                return FileResult(f, d, validate(d, self.config.policy))
            return _history_result(f, history.resolve_lines(f, fallback[f]))

        with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 2))) as pool:
            return list(pool.map(one, files))

    def _history(self, declared, declared_after, quiet):
        self.history_used = False
        self.history_problems = []
        if not self.history_wanted():
            return None
        from .history import History, HistoryError, unavailable_reason
        reason = unavailable_reason(self.root)
        if reason:
            if not quiet:
                print(f"warning: [history] is enabled, but this is a {reason}; using the file-level declarations",
                      file=sys.stderr)
            return None
        try:
            history = History(self.root, self.config, declared, declared_after)
        except HistoryError as e:
            raise ProjectError(str(e))
        self.history_used = True
        self.history_problems = history.problems
        return history

    def unused_annotations(self, files: list[str]) -> list[int]:
        return [a.index for a in self.config.annotations if not any(a.matches(f) for f in files)]
