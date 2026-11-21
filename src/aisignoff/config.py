"""Reading SIGNOFF.toml.

Format::

    version = 4
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

    [[attestations]]                     # or the lines one commit landed (and still has)
    commit = "1a2b3c4"
    path = "src/solver.py"               # optional with commit: all its files
    AI-Review = "A2"
    AI-Reviewed-by = "GPT Sol (OpenAI), reviews/pull12.md"
    AI-Review-Findings = "minor"

    [review]
    dir = "reviews"                      # optional: the review folder (default reviews)

The review folder holds the reviews: their reports, the evidence of A3, and attestation files
(*.toml with [[attestations]] tables only, which may give only the AI review). It needs no
declaration, and a change may only add files to it.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .globbing import compile_glob, matches
from .model import (AI_REVIEWED, AIR, AXES, FINDINGS, KEYS, LEVELS, LIST_KEYS, NO_FINDINGS, SEVERITIES, TODO, Declaration,
                    Policy, canonical_key, findings_value, valid_findings, from_version_3, parse_policy, policy_from_version_3)

FILENAME = "SIGNOFF.toml"
# Converted by 'aisignoff migrate' up to 1.0.0rc1, and no longer read: say so instead of treating
# the repository as one without a SIGNOFF.toml.
OLD_FILENAME = "AIDECL.toml"
OLD_RELEASE = "1.0.0rc1"  # the last release that converts old formats
CONVERT = f"convert it once with 'uvx aisignoff=={OLD_RELEASE} migrate' (or pipx run)"
VERSION = 4
# Version 3 had another AI review scale (A1 was the self-check of the generating session). It is
# still read: its AI review levels, and those of the repository's commit messages, are taken over to today's scale (model.from_version_3) until the file says version = 4.
VERSION_3 = 3
REVIEW_DIR = "reviews"  # the default review folder ([review] dir)
REVIEW_KEYS = ("dir", "recheck")
PRECEDENCES = ("closest", "override")
HISTORY_KEYS = ("enabled", "require-trailers-since", "ignore-revs-file", "merge-method", "ignore-whitespace",
                "default-branch", "undeclared")
MERGE_METHODS = ("merge", "squash", "rebase")
UNDECLARED = ("baseline", "error")
_HEX = set("0123456789abcdef")


class ConfigError(Exception):
    pass


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
    """An [[attestations]] entry: one file re-declared as of the content (git blob) that was checked,
    or (commit) the lines one commit of the default branch landed and that are still there, in one
    file (path) or in all of them (path None)."""

    index: int
    path: str | None
    blob: str | None
    values: dict
    filename: str = FILENAME
    commit: str | None = None


@dataclass
class Config:
    path: Path | None
    annotations: list[Annotation] = field(default_factory=list)
    exclude: tuple[str, ...] = ()
    policy: Policy = field(default_factory=Policy)
    history: HistorySettings = field(default_factory=HistorySettings)
    commits: list[CommitEntry] = field(default_factory=list)
    attestations: list[Attestation] = field(default_factory=list)
    review_dir: str = REVIEW_DIR  # the review folder, relative to the project root
    # the [[attestations]] of the attestation files in the review folder, by path
    review_attestations: list[Attestation] = field(default_factory=list)
    # keys this version doesn't know (a later 1.x may add optional ones): lint warns, --strict fails
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # for the reader, never a failure
    # version = 3: AI review levels here, and in commit messages are of the scale before version 4
    version_3: bool = False

    def is_excluded(self, path: str) -> bool:
        return self.in_review_dir(path) or any(matches(p, path) for p in self.exclude)

    def in_review_dir(self, path: str) -> bool:
        """Whether a path (relative to the project root) is in the review folder: reviews are
        records about the content, not content, so they need no declaration."""
        return bool(self.review_dir) and path.startswith(self.review_dir + "/")

    def all_attestations(self) -> list[Attestation]:
        """The attestations of SIGNOFF.toml, then those of the review folder."""
        return self.attestations + self.review_attestations

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


def config_path(root: Path) -> Path:
    if (root / OLD_FILENAME).exists():
        raise ConfigError(f"{OLD_FILENAME} is the old name of {FILENAME} and is no longer read; {CONVERT}")
    return root / FILENAME


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
    config = parse(data, config_path(root))
    config.review_attestations = load_review_attestations(root, config)
    return config


def load_review_attestations(root: Path, config: Config) -> list[Attestation]:
    """The [[attestations]] of the attestation files (*.toml) in the review folder, by path. An
    attestation file records an independent AI review: it holds [[attestations]] tables and nothing
    else, and each gives the AI review (A1-A3) with its names and findings, never another axis."""
    folder = root / config.review_dir if config.review_dir else None
    if folder is None or not folder.is_dir():
        return []
    out = []
    for file in sorted(folder.rglob("*.toml")):
        if not file.is_file():
            continue
        name = file.relative_to(root).as_posix()
        try:
            data = tomllib.loads(file.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
            raise ConfigError(f"{name}: invalid TOML: {e}") from e
        if set(data) - {"attestations"}:
            raise ConfigError(f"{name}: an attestation file in the review folder holds [[attestations]] tables "
                              f"only, not {', '.join(sorted(set(data) - {'attestations'}))}")
        entries = _attestations(data, name, False)  # always on today's scale
        if not entries:
            raise ConfigError(f"{name}: an attestation file in the review folder needs [[attestations]] tables")
        for a in entries:
            where = f"{name} [[attestations]] entry {a.index}"
            other = set(a.values) - {AIR, AI_REVIEWED, FINDINGS}
            if other:
                raise ConfigError(f"{where}: an attestation file in the review folder records an AI review, so it "
                                  f"gives {AIR}, {AI_REVIEWED} and {FINDINGS} only, not {', '.join(sorted(other))} "
                                  f"(a person's review goes into {FILENAME})")
            if a.values.get(AIR) not in ("A1", "A2", "A3"):
                raise ConfigError(f"{where}: {AIR} must be A1, A2 or A3 (an independent AI review)")
        out += entries
    return out


def load_text(text: str, path: Path) -> Config:
    """A SIGNOFF.toml given as text, such as the one of another commit (path names it in errors)."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name}: invalid TOML: {e}") from e
    return parse(data, path)


def parse(data: dict, path: Path) -> Config:
    name = path.name

    version = data.get("version")
    if type(version) is int and version in (1, 2):
        old = "V0-V3 levels" if version == 1 else "the AI review scale A-, A0-A3"
        raise ConfigError(f"{name} uses version {version} ({old}), which is no longer read; {CONVERT}")
    if type(version) is not int or version not in (VERSION, VERSION_3):
        raise ConfigError(f"{name}: 'version = {VERSION}' is required")
    old = version == VERSION_3
    warnings = []
    unknown = set(data) - {"version", "exclude", "policy", "annotations", "history", "commits", "attestations", "review"}
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
    if old:
        policy = Policy(policy_from_version_3(policy.rules))

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
        values = _parse_values(table, ("path", "precedence"), where, old)
        annotations.append(Annotation(index=i, paths=paths, precedence=precedence, values=values, filename=name))
    history = _parse_history(data.get("history"), name, warnings)
    review = data.get("review", {})
    if not isinstance(review, dict):
        raise ConfigError(f"{name}: use a [review] table")
    review_dir = review.get("dir", REVIEW_DIR)
    if not isinstance(review_dir, str) or review_dir.startswith(("/", "../")) or any(c in review_dir for c in "*?") \
            or ".." in review_dir.split("/"):
        raise ConfigError(f"{name} [review]: 'dir' must be a folder inside the project (no glob), or \"\" for none")
    review_dir = review_dir.removeprefix("./").strip("/")
    if "recheck" in review:
        # 1.0.0rc8 had a threshold from which a finding failed lint; findings are now recorded as the
        # findings level of the lines the review covered, and block nothing
        warnings.append(f"{name} [review]: 'recheck' is no longer used (a finding blocks nothing: it is shown as the "
                        "findings level of the lines the review covered); remove it")
    if set(review) - set(REVIEW_KEYS):
        warnings.append(f"{name} [review]: unknown key(s) {', '.join(sorted(set(review) - set(REVIEW_KEYS)))}, ignored "
                        "(a typo, or a setting of a later aisignoff?)")
    commits = []
    for i, table in enumerate(_tables(data, "commits", name), start=1):
        where = f"{name} [[commits]] entry {i}"
        commit = table.get("commit")
        if not isinstance(commit, str) or not _is_hex(commit, 4):
            raise ConfigError(f"{where}: 'commit' must be a commit hash (at least 4 hex digits)")
        values = _parse_values(table, ("commit",), where, old)
        _check_axes(values, where)
        commits.append(CommitEntry(index=i, commit=commit.lower(), values=values, filename=name))
    attestations = _attestations(data, name, old)
    notes = []
    if old:
        notes.append(f"{name} says version = {VERSION_3}: its AI review levels, and those of this repository's commit "
                     "messages and pull request descriptions, are read on the scale before version 4 "
                     "and shown on today's (A1 self-check: A0, A2 new session: A1, A3 stays). To change over, run "
                     "examples/convert-to-version-4.py (see 'Upgrading' in the documentation)")
    return Config(path=path, annotations=annotations, exclude=exclude, policy=policy, history=history,
                  commits=commits, attestations=attestations, warnings=warnings, notes=notes, version_3=old,
                  review_dir=review_dir)


def _attestations(data: dict, name: str, old: bool) -> list[Attestation]:
    """The [[attestations]] tables of a file: each a file as of its checked content (path and
    blob), or the lines one commit landed (commit, and optionally the path of one file)."""
    out = []
    for i, table in enumerate(_tables(data, "attestations", name), start=1):
        where = f"{name} [[attestations]] entry {i}"
        apath, blob, commit = table.get("path"), table.get("blob"), table.get("commit")
        if (blob is None) == (commit is None):
            raise ConfigError(f"{where}: give 'blob' (the whole file, as of the checked content) or 'commit' "
                              "(the lines that commit landed), not both")
        if apath is not None or blob is not None:
            if not isinstance(apath, str) or not apath or any(c in apath for c in "*?"):
                raise ConfigError(f"{where}: 'path' must be the path of one file (no glob)")
            apath = apath.removeprefix("./")
        if blob is not None and (not isinstance(blob, str) or not _is_hex(blob, 40) or len(blob) not in (40, 64)):
            raise ConfigError(f"{where}: 'blob' must be the full git blob hash of the checked content")
        if commit is not None and (not isinstance(commit, str) or not _is_hex(commit, 7)):
            raise ConfigError(f"{where}: 'commit' must be a commit hash (at least 7 hex digits)")
        values = _parse_values(table, ("path", "blob", "commit"), where, old)
        _check_axes(values, where)
        out.append(Attestation(index=i, path=apath, blob=blob.lower() if blob else None, values=values,
                               filename=name, commit=commit.lower() if commit else None))
    return out


def _is_hex(s: str, minimum: int) -> bool:
    return len(s) >= minimum and set(s.lower()) <= _HEX


def _tables(data: dict, key: str, name: str) -> list:
    raw = data.get(key, [])
    if not isinstance(raw, list) or not all(isinstance(t, dict) for t in raw):
        raise ConfigError(f"{name}: use [[{key}]] tables")
    return raw


def _parse_values(table: dict, skip: tuple, where: str, old: bool = False) -> dict:
    """The declaration keys of a table, validated (level values, string lists). old: the table is
    of version 3, so its AI review is taken over to today's scale."""
    values = {}
    for k, v in table.items():
        if k in skip:
            continue
        key = canonical_key(k, (*KEYS, FINDINGS))
        if key is None:
            raise ConfigError(f"{where}: unknown key '{k}' (allowed: {', '.join((*skip, *KEYS, FINDINGS))})")
        if key in values:
            raise ConfigError(f"{where}: '{key}' is given more than once")
        if key == FINDINGS:
            if not isinstance(v, str) or not valid_findings(v):
                raise ConfigError(f"{where}: invalid {FINDINGS} {v!r} (use {NO_FINDINGS}, {', '.join(SEVERITIES)})")
            values[key] = findings_value(v)
        elif key in LIST_KEYS:
            values[key] = _str_list(v, f"{where}: '{k}'")
        else:
            if not isinstance(v, str):
                raise ConfigError(f"{where}: '{k}' must be a string")
            if v not in LEVELS[key] and v != TODO:  # TODO: placeholder, reported by lint
                raise ConfigError(f"{where}: invalid {key} '{v}' (use {', '.join(LEVELS[key])})")
            values[key] = v
    if old and AIR in values:
        level, names = from_version_3(values[AIR], values.get(AI_REVIEWED, ()))
        values[AIR] = level
        if names:
            values[AI_REVIEWED] = names
        else:
            values.pop(AI_REVIEWED, None)
    return values


def _check_axes(values: dict, where: str) -> None:
    """[[commits]] and [[attestations]] declare whole axes: a level, and names only next to their level."""
    if not any(level in values for level, _ in AXES):
        raise ConfigError(f"{where}: declare at least one level ({', '.join(level for level, _ in AXES)})")
    for level, names in AXES:
        if names in values and level not in values:
            raise ConfigError(f"{where}: {names} without {level}")
    if FINDINGS in values and AIR not in values:
        raise ConfigError(f"{where}: {FINDINGS} without {AIR}")


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
