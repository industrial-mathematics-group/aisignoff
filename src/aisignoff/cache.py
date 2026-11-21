"""The blame cache: what 'git blame' found for the files of the default branch at one of its
commits, kept in the repository's git folder (.git/aisignoff/) so that the next run only blames
the commits since.

It holds facts about git history only, never levels: for each line of a file, the commit blame
gives it and the line's number and path there, once for the commits that landed the lines
(--first-parent) and, where it was needed, once for those that wrote them. These follow from the
history and the blame options alone, so the cache can't be wrong for another SIGNOFF.toml or
review; a run with other blame options (whitespace, an ignore-revs file) doesn't use it. Deleting
it only makes the next run slower. AISIGNOFF_NO_CACHE=1 turns it off.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path

FORMAT = 1
KEEP = 3  # cache files kept, the newest first: one per commit of the default branch
PREFIX = "blame-"
SUFFIX = ".json.gz"

Row = tuple  # (commit, its line number there, whether blame stopped there, the path there)


def enabled() -> bool:
    return os.environ.get("AISIGNOFF_NO_CACHE", "").strip().lower() in ("", "0", "false", "no")


def _folder(root: Path) -> Path | None:
    """.git/aisignoff of the repository (the common one of all its worktrees)."""
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             capture_output=True, text=True)
    except FileNotFoundError:
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return Path(out.stdout.strip()) / "aisignoff"


def _encode(rows: list[Row], shas: dict[str, int], names: dict[str, int]) -> list[list[int]]:
    """Runs of rows: [lines, commit, first line there, path, stopped], a run going on while the
    commit, path and stop stay and the line there goes up by one."""
    runs: list[list[int]] = []
    for sha, line, stopped, name in rows:
        s, p, b = shas.setdefault(sha, len(shas)), names.setdefault(name, len(names)), int(stopped)
        last = runs[-1] if runs else None
        if last and last[1] == s and last[3] == p and last[4] == b and last[2] + last[0] == line:
            last[0] += 1
        else:
            runs.append([1, s, line, p, b])
    return runs


def _decode(runs: list, shas: list[str], names: list[str]) -> list[Row]:
    return [(shas[s], start + k, bool(b), names[p]) for count, s, start, p, b in runs for k in range(count)]


class BlameCache:
    """The cache of one repository. open() starts a run's use of it."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def open(self, history) -> "CacheRun | None":
        if not enabled():
            return None
        folder = _folder(self.root)
        if folder is None:
            return None
        key = hashlib.sha256(json.dumps([FORMAT, history.blame_options]).encode()).hexdigest()[:16]
        return CacheRun(folder, key, history.base, history.order)


class CacheRun:
    """One run's view of the cache: the newest cached commit of the default branch's first-parent
    history (start), and the blames this run adds, saved for the default branch's commit at the end."""

    def __init__(self, folder: Path, key: str, base: str, order: dict[str, int]):
        self.folder, self.key, self.base = folder, key, base
        self.start: str | None = None
        self._data: dict = {}  # of the start commit, as read
        self._rows: dict[tuple[str, bool], list[Row]] = {}  # (path, first_parent) -> rows, decoded when needed
        self._new: dict[tuple[str, bool], list[Row]] = {}  # this run's blames at base
        self._sides: dict[str, list[str]] = {}  # merge -> the commits it brought in, newest first
        self._sides_changed = False
        self._lock = threading.Lock()
        self.lock = threading.RLock()  # for History, while it reads the messages of the listed commits
        found = []
        for f in folder.glob(f"{PREFIX}*{SUFFIX}") if folder.is_dir() else ():
            sha = f.name[len(PREFIX):-len(SUFFIX)]
            if sha in order:
                found.append((order[sha], sha, f))
        for _, sha, f in sorted(found, reverse=True):
            data = self._read(f)
            if data is not None and data.get("key") == key and data.get("commit") == sha:
                self.start, self._data = sha, data
                try:
                    shas = data["shas"]
                    self._sides = {shas[int(m)]: [shas[i] for i in side] for m, side in (data.get("sides") or {}).items()}
                except (TypeError, ValueError, IndexError, AttributeError):
                    self._sides = {}
                break

    @staticmethod
    def _read(f: Path) -> dict | None:
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError, EOFError):
            return None
        if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("files"), dict) \
                or not isinstance(data.get("shas"), list) or not isinstance(data.get("names"), list):
            return None
        return data

    def rows(self, commit: str, path: str, first_parent: bool) -> list[Row] | None:
        """The rows of a file (path from the top of the repository) at a commit: the cached
        commit's, or the ones this run found at the default branch's commit. None: not cached."""
        if commit == self.base and (path, first_parent) in self._new:
            return self._new[(path, first_parent)]
        if commit != self.start:
            return None
        k = (path, first_parent)
        with self._lock:
            if k not in self._rows:
                entry = self._data["files"].get(path)
                runs = entry.get("fp" if first_parent else "wr") if isinstance(entry, dict) else None
                try:
                    self._rows[k] = _decode(runs, self._data["shas"], self._data["names"]) if runs is not None else None
                except (TypeError, ValueError, IndexError):
                    self._rows[k] = None
            return self._rows[k]

    def record(self, path: str, first_parent: bool, rows: list[Row]) -> None:
        with self._lock:
            self._new[(path, first_parent)] = rows

    # the commits each merge brought in: they never change, so they are kept from file to file
    def side(self, merge: str) -> list[str] | None:
        return self._sides.get(merge)

    def all_sides(self) -> list[str]:
        with self._lock:
            return [sha for side in self._sides.values() for sha in side]

    def record_side(self, merge: str, shas: list[str]) -> None:
        with self._lock:
            self._sides[merge] = list(shas)
            self._sides_changed = True

    def forget_side(self, merge: str) -> None:
        with self._lock:
            self._sides.pop(merge, None)

    def save(self) -> None:
        """Write the cache for the default branch's commit: this run's blames, and those of the
        cached commit if it is the same one. Never fails a run: a cache that can't be written is
        left out."""
        if not self._new and not self._sides_changed:
            return
        entries: dict[tuple[str, bool], list[Row]] = {}
        if self.start == self.base:
            for path, entry in self._data["files"].items():
                for fp in (True, False):
                    rows = self.rows(self.base, path, fp) if isinstance(entry, dict) else None
                    if rows is not None:
                        entries[(path, fp)] = rows
        entries.update(self._new)
        shas: dict[str, int] = {}
        names: dict[str, int] = {}
        files: dict[str, dict] = {}
        for (path, fp), rows in sorted(entries.items()):
            files.setdefault(path, {})["fp" if fp else "wr"] = _encode(rows, shas, names)
        sides = {str(shas.setdefault(m, len(shas))): [shas.setdefault(s, len(shas)) for s in side]
                 for m, side in sorted(self._sides.items())}
        data = {"format": FORMAT, "key": self.key, "commit": self.base, "shas": list(shas), "names": list(names),
                "files": files, "sides": sides}
        tmp = None
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.folder, prefix=".tmp-", suffix=SUFFIX)
            with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0) as fh:
                fh.write(json.dumps(data, separators=(",", ":")).encode("utf-8"))
            os.replace(tmp, self.folder / f"{PREFIX}{self.base}{SUFFIX}")
            old = sorted(self.folder.glob(f"{PREFIX}*{SUFFIX}"), key=lambda f: f.stat().st_mtime, reverse=True)
            for f in old[KEEP:]:
                f.unlink(missing_ok=True)
        except OSError:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
