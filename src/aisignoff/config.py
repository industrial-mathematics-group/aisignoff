"""Reading SIGNOFF.toml (or, from before the rename to aisignoff, AIDECL.toml).

Format::

    version = 3
    exclude = ["docs/build/**"]          # optional: files that need no declaration

    [policy]                             # optional: minimum review levels per generation level
    "*" = { human = "H1" }
    G3  = { human = "H2", ai = "A2" }

    [[annotations]]
    path = "**"                          # one pattern or a list of patterns
    precedence = "closest"               # optional: "closest" (default) or "override"
    AI-Generation = "G0"
    Human-Review = "H2"
    AI-Review = "A0"
    Reviewed-by = "Jane Doe"             # string or list of strings

    [history]                            # optional: line-level declarations from git history
    enabled = true
    default-branch = "main"              # optional: the branch whose commits own the lines
    undeclared = "baseline"              # optional: "error" if every commit there must declare its lines
    require-trailers-since = "1a2b3c4"   # optional: commits after this one must declare their lines
    merge-method = "merge"               # optional: how pull requests land (merge, squash, rebase)

    [[commits]]                          # corrects or adds the declaration of a commit
    commit = "1a2b3c4"
    Human-Review = "H2"
    Reviewed-by = "Jane Doe"

    [[attestations]]                     # re-declares a file as of the content that was checked
    path = "src/solver.py"
    blob = "<git blob hash of the checked content>"
    Human-Review = "H2"
    Reviewed-by = "Jane Doe"
"""
from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .globbing import compile_glob, matches
from .model import AIR, AXES, KEYS, LEGACY_AI_NONE, LEVELS, LIST_KEYS, TODO, Declaration, Policy, canonical_key, parse_policy

FILENAME = "SIGNOFF.toml"
LEGACY_FILENAME = "AIDECL.toml"  # the name before aidecl became aisignoff; read until migrated
VERSION = 3
PRECEDENCES = ("closest", "override")
HISTORY_KEYS = ("enabled", "require-trailers-since", "ignore-revs-file", "merge-method", "ignore-whitespace",
                "default-branch", "undeclared")
MERGE_METHODS = ("merge", "squash", "rebase")
UNDECLARED = ("baseline", "error")
_HEX = set("0123456789abcdef")


class ConfigError(Exception):
    pass


class LegacyConfig(ConfigError):
    """The config file still uses version 1 (V0-V3 levels) or 2 (A-, A0-A3)."""


@dataclass
class Annotation:
    index: int  # 1-based position in the file
    paths: tuple[str, ...]
    precedence: str
    values: dict
    filename: str = FILENAME

    def matches(self, path: str) -> bool:
        return any(matches(p, path) for p in self.paths)

    def declaration(self) -> Declaration:
        return Declaration.from_mapping(self.values, source=f"{self.filename} [{self.index}]")


@dataclass
class HistorySettings:
    """The [history] table: line-level declarations from git history."""

    enabled: bool = False
    require_trailers_since: str | None = None
    ignore_revs_file: str | None = None  # default: .git-blame-ignore-revs if it exists
    merge_method: str = "merge"  # how pull requests land: what a pull request's CI run previews
    ignore_whitespace: bool = True  # git blame -w
    default_branch: str | None = None  # default: origin's default branch, else main or master
    undeclared: str = "baseline"  # lines of a commit that declares nothing: the file-level declaration, or an error


@dataclass
class CommitEntry:
    """A [[commits]] entry: declares (or corrects) the levels of one commit."""

    index: int
    commit: str
    values: dict
    filename: str = FILENAME


@dataclass
class Attestation:
    """An [[attestations]] entry: one file re-declared as of the content (git blob) that was checked."""

    index: int
    path: str
    blob: str
    values: dict
    filename: str = FILENAME


@dataclass
class Config:
    path: Path | None
    annotations: list[Annotation] = field(default_factory=list)
    exclude: tuple[str, ...] = ()
    policy: Policy = field(default_factory=Policy)
    history: HistorySettings = field(default_factory=HistorySettings)
    commits: list[CommitEntry] = field(default_factory=list)
    attestations: list[Attestation] = field(default_factory=list)
    # keys this version doesn't know (a later 1.x may add optional ones): lint warns, --strict fails
    warnings: list[str] = field(default_factory=list)

    def is_excluded(self, path: str) -> bool:
        return any(matches(p, path) for p in self.exclude)

    def match(self, path: str) -> Annotation | None:
        """The last annotation that matches wins (same rule as REUSE.toml)."""
        found = None
        for a in self.annotations:
            if a.matches(path):
                found = a
        return found


def _str_list(value, what: str) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{what} must be a string or a list of strings")
    return tuple(value)


_warned: set[Path] = set()


def config_path(root: Path) -> Path:
    """SIGNOFF.toml, or AIDECL.toml if only that one exists (a repository not migrated yet)."""
    new, old = root / FILENAME, root / LEGACY_FILENAME
    if old.exists():
        if new.exists():
            raise ConfigError(f"both {FILENAME} and {LEGACY_FILENAME} exist; keep only {FILENAME}")
        return old
    return new


def _warn_legacy(path: Path) -> None:
    if path.name == LEGACY_FILENAME and path not in _warned:
        _warned.add(path)
        print(f"warning: {LEGACY_FILENAME} is the old name of {FILENAME}; run 'aisignoff migrate' to rename it",
              file=sys.stderr)


def read_toml(root: Path) -> dict | None:
    path = config_path(root)
    if not path.exists():
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name}: invalid TOML: {e}") from e


def load(root: Path) -> Config:
    data = read_toml(root)
    if data is None:
        return Config(path=None)
    path = config_path(root)
    name = path.name
    _warn_legacy(path)

    version = data.get("version")
    if type(version) is int and version in (1, 2):
        old = "V0-V3 levels" if version == 1 else "the AI review scale A-, A0-A3"
        raise LegacyConfig(f"{name} uses version {version} ({old}). Run 'aisignoff migrate' to convert "
                           f"it to version {VERSION}.")
    if type(version) is not int or version != VERSION:
        raise ConfigError(f"{name}: 'version = {VERSION}' is required")
    warnings = []
    unknown = set(data) - {"version", "exclude", "policy", "annotations", "history", "commits", "attestations"}
    if unknown:
        warnings.append(f"{name}: unknown top-level key(s) {', '.join(sorted(unknown))}, ignored (a typo, or a "
                        "setting of a later aisignoff?)")
    exclude = _str_list(data.get("exclude", []), f"{name}: 'exclude'")
    for p in exclude:
        compile_glob(p)
    try:
        policy = parse_policy(data.get("policy"), where=f"{name} [policy]")
    except ValueError as e:
        raise ConfigError(str(e)) from e

    annotations = []
    raw = data.get("annotations", [])
    if not isinstance(raw, list) or not all(isinstance(t, dict) for t in raw):
        raise ConfigError(f"{name}: use [[annotations]] tables")
    for i, table in enumerate(raw, start=1):
        where = f"{name} annotation [{i}]"
        if "path" not in table:
            raise ConfigError(f"{where}: 'path' is required")
        paths = _str_list(table["path"], f"{where}: 'path'")
        if not paths or any(p == "" for p in paths):
            raise ConfigError(f"{where}: 'path' must not be empty")
        precedence = table.get("precedence", "closest")
        if precedence not in PRECEDENCES:
            raise ConfigError(f"{where}: precedence must be 'closest' or 'override'")
        values = _parse_values(table, ("path", "precedence"), where)
        annotations.append(Annotation(index=i, paths=paths, precedence=precedence, values=values, filename=name))
    history = _parse_history(data.get("history"), name, warnings)
    commits = []
    for i, table in enumerate(_tables(data, "commits", name), start=1):
        where = f"{name} [[commits]] entry {i}"
        commit = table.get("commit")
        if not isinstance(commit, str) or not _is_hex(commit, 4):
            raise ConfigError(f"{where}: 'commit' must be a commit hash (at least 4 hex digits)")
        values = _parse_values(table, ("commit",), where)
        _check_axes(values, where)
        commits.append(CommitEntry(index=i, commit=commit.lower(), values=values, filename=name))
    attestations = []
    for i, table in enumerate(_tables(data, "attestations", name), start=1):
        where = f"{name} [[attestations]] entry {i}"
        apath = table.get("path")
        if not isinstance(apath, str) or not apath or any(c in apath for c in "*?"):
            raise ConfigError(f"{where}: 'path' must be the path of one file (no glob)")
        blob = table.get("blob")
        if not isinstance(blob, str) or not _is_hex(blob, 40) or len(blob) not in (40, 64):
            raise ConfigError(f"{where}: 'blob' must be the full git blob hash of the checked content")
        values = _parse_values(table, ("path", "blob"), where)
        _check_axes(values, where)
        attestations.append(Attestation(index=i, path=apath.removeprefix("./"), blob=blob.lower(), values=values,
                                        filename=name))
    return Config(path=path, annotations=annotations, exclude=exclude, policy=policy, history=history,
                  commits=commits, attestations=attestations, warnings=warnings)


def _is_hex(s: str, minimum: int) -> bool:
    return len(s) >= minimum and set(s.lower()) <= _HEX


def _tables(data: dict, key: str, name: str) -> list:
    raw = data.get(key, [])
    if not isinstance(raw, list) or not all(isinstance(t, dict) for t in raw):
        raise ConfigError(f"{name}: use [[{key}]] tables")
    return raw


def _parse_values(table: dict, skip: tuple, where: str) -> dict:
    """The declaration keys of a table, validated (level values, string lists)."""
    values = {}
    for k, v in table.items():
        if k in skip:
            continue
        key = canonical_key(k)
        if key is None:
            raise ConfigError(f"{where}: unknown key '{k}' (allowed: {', '.join((*skip, *KEYS))})")
        if key in values:
            raise ConfigError(f"{where}: '{key}' is given more than once")
        if key in LIST_KEYS:
            values[key] = _str_list(v, f"{where}: '{k}'")
        else:
            if not isinstance(v, str):
                raise ConfigError(f"{where}: '{k}' must be a string")
            if v not in LEVELS[key] and v != TODO:  # TODO: placeholder, reported by lint
                hint = " (A- is now A0)" if key == AIR and v == LEGACY_AI_NONE else ""
                raise ConfigError(f"{where}: invalid {key} '{v}' (use {', '.join(LEVELS[key])}){hint}")
            values[key] = v
    return values


def _check_axes(values: dict, where: str) -> None:
    """[[commits]] and [[attestations]] declare whole axes: a level, and names only next to their level."""
    if not any(level in values for level, _ in AXES):
        raise ConfigError(f"{where}: declare at least one level ({', '.join(level for level, _ in AXES)})")
    for level, names in AXES:
        if names in values and level not in values:
            raise ConfigError(f"{where}: {names} without {level}")


def _parse_history(table, name: str, warnings: list[str]) -> HistorySettings:
    if table is None:
        return HistorySettings()
    where = f"{name} [history]"
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table")
    unknown = set(table) - set(HISTORY_KEYS)
    if unknown:
        warnings.append(f"{where}: unknown key(s) {', '.join(sorted(unknown))}, ignored (this version knows "
                        f"{', '.join(HISTORY_KEYS)})")
    enabled = table.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError(f"{where}: 'enabled' must be true or false")
    since = table.get("require-trailers-since")
    if since is not None and (not isinstance(since, str) or not since.strip()):
        raise ConfigError(f"{where}: 'require-trailers-since' must be a commit (hash, tag or branch)")
    revs = table.get("ignore-revs-file")
    if revs is not None and (not isinstance(revs, str) or not revs):
        raise ConfigError(f"{where}: 'ignore-revs-file' must be a path")
    method = table.get("merge-method", "merge")
    if method not in MERGE_METHODS:
        raise ConfigError(f"{where}: 'merge-method' must be one of {', '.join(MERGE_METHODS)}")
    whitespace = table.get("ignore-whitespace", True)
    if not isinstance(whitespace, bool):
        raise ConfigError(f"{where}: 'ignore-whitespace' must be true or false")
    branch = table.get("default-branch")
    if branch is not None and (not isinstance(branch, str) or not branch.strip() or branch.startswith("-")):
        raise ConfigError(f"{where}: 'default-branch' must be the name of a branch")
    undeclared = table.get("undeclared", "baseline")
    if undeclared not in UNDECLARED:
        raise ConfigError(f"{where}: 'undeclared' must be one of {', '.join(UNDECLARED)}")
    return HistorySettings(enabled=enabled, require_trailers_since=since, ignore_revs_file=revs,
                           merge_method=method, ignore_whitespace=whitespace, default_branch=branch,
                           undeclared=undeclared)
