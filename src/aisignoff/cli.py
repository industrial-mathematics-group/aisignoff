"""Command-line interface: aisignoff init | lint | report | annotate | attest | freeze | diff | badge | migrate."""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from . import __version__, inline
from .config import FILENAME, LEGACY_FILENAME, VERSION, ConfigError, LegacyConfig, config_path, load, read_toml
from .globbing import escape
from .model import (AI, AI_REVIEWED, AIR, ASSISTED, GEN, GENERATION, HUM, HUMAN, KEYS, LIST_KEYS, REVIEWED,
                    TODO, Declaration, Policy, canonical_key, counted_level, counted_short, printable, validate)
from .project import Project, ProjectError, list_files, weighted_parts

SPEC_URL = ("https://github.com/industrial-mathematics-group/.github/blob/main/.github/"
            "CONTRIBUTING.md#ai-assisted-contributions")
AXIS_INFO = (  # key, short, title, levels, badge file, colour
    (GEN, "G", "Generation", GENERATION, "aisignoff-generation.json", "4063D8"),
    (HUM, "H", "Human review", HUMAN, "aisignoff-human-review.json", "389826"),
    (AIR, "A", "AI review", AI, "aisignoff-ai-review.json", "9558B2"),
)


class UsageError(Exception):
    pass


def _toml_str(s: str) -> str:
    # JSON string escapes are valid TOML basic-string escapes; DEL is the one control
    # character JSON leaves unescaped but TOML forbids.
    return json.dumps(s, ensure_ascii=False).replace("\x7f", "\\u007f")


def _toml_value(v) -> str:
    if isinstance(v, str):
        return _toml_str(v)
    return "[" + ", ".join(_toml_str(x) for x in v) + "]"


def _values(args) -> dict:
    values = {GEN: args.generation, HUM: args.human, AIR: args.ai}
    for key, items in ((ASSISTED, args.assisted_by), (REVIEWED, args.reviewed_by),
                       (AI_REVIEWED, args.ai_reviewed_by)):
        if items:
            for item in items:
                if not item.strip() or any(ord(c) < 32 or ord(c) == 127 for c in item):
                    raise UsageError(f"{key} values must be non-empty single-line text: {item!r}")
            values[key] = [i.strip() for i in items]
    if values[HUM] == TODO and REVIEWED not in values:
        values[REVIEWED] = [TODO]  # so the person fills in the name next to the level
    return {k: v for k, v in values.items() if v}


def _policy(root: Path) -> Policy:
    try:
        return load(root).policy
    except ConfigError as e:
        raise UsageError(str(e))


def _check_complete(values: dict, policy: Policy) -> None:
    problems = validate(Declaration.from_mapping(values, source="command line"), policy, allow_todo=True)
    if problems:
        raise UsageError("incomplete declaration: " + "; ".join(problems))


def _open(root) -> Project:
    try:
        return Project(root)
    except (ConfigError, ProjectError) as e:
        raise UsageError(str(e))


def _results(project: Project):
    try:
        return project.results()
    except ProjectError as e:
        raise UsageError(str(e))


# ---------------------------------------------------------------- init
def cmd_init(args) -> int:
    root = Path(args.root)
    if not root.is_dir():
        raise UsageError(f"project root {root} is not a directory")
    target = root / FILENAME
    if target.exists():
        raise UsageError(f"{target} already exists")
    if (root / LEGACY_FILENAME).exists():
        raise UsageError(f"{root / LEGACY_FILENAME} already exists (the old name of {FILENAME}); "
                         "run 'aisignoff migrate' to rename it")
    lines = [
        "# AI declarations for this repository: generation (G0-G3), human review (H0-H3)",
        "# and AI review (A0-A3).",
        f"# Scheme: {SPEC_URL}",
        "# The LAST annotation that matches a file wins. Inline tags in a file win over",
        '# this file unless the matching annotation sets precedence = "override".',
        f"version = {VERSION}",
        "",
        '# exclude = ["reviews/**", "docs/build/**"]   # files that need no declaration,',
        "# such as the committed AI reviews in reviews/ (CONTRIBUTING.md)",
        "",
        "# Minimum review levels (optional). G1-G3 always need at least A1.",
        "# [policy]",
        '# "*" = { human = "H1" }',
        '# G3  = { human = "H2", ai = "A2" }',
        "",
    ]
    given = [args.generation, args.human, args.ai]
    if any(given):
        if not all(given):
            raise UsageError("give --generation, --human and --ai together, or none of them")
        values = _values(args)
        _check_complete(values, Policy())
        lines += ["# Default for everything", "[[annotations]]", 'path = "**"']
        lines += [f"{k} = {_toml_value(v)}" for k, v in values.items()]
    else:
        lines += [
            "# Example:",
            "# [[annotations]]",
            '# path = "**"',
            '# AI-Generation = "G0"',
            '# Human-Review = "H2"',
            '# AI-Review = "A0"',
            '# Reviewed-by = "Jane Doe"',
        ]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Created {target}")
    return 0


# ---------------------------------------------------------------- lint
def _declared(args):
    """The declaration of the change that isn't on the default branch yet, from --declare-from
    (a pull request description, read as its merge or squash commit's message will be) or from
    the level options. None: there is none."""
    values = _values(args)
    if args.declare_from is None:
        if args.author:
            raise UsageError("--author needs --declare-from")
        return Declaration.from_mapping(values, "declared for this change") if values else None
    if values:
        raise UsageError("give --declare-from or the level options, not both")
    from .history import parse_message
    try:
        text = sys.stdin.read() if args.declare_from == "-" else Path(args.declare_from).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise UsageError(f"cannot read {args.declare_from}: {e}")
    pieces, both = parse_message(text.replace("\r\n", "\n"), args.author or "", "the pull request description")
    return {i: dataclasses.replace(p, kind="declared", problems=p.problems + ((both,) if both else ())) for i, p in pieces.items()}


def _history_results(project: Project, args):
    """The results as lint and report see them: with the change that hasn't landed declared from
    --declare-from (from --base on), or with HEAD as a commit of the default branch (--landed)."""
    declared = _declared(args)
    base = None
    if args.landed and declared is not None:
        raise UsageError("--landed says that nothing is waiting for a pull request: it can't go with --declare-from")
    if args.base:
        if declared is None:
            raise UsageError("--base needs --declare-from")
        from .diff import DiffError, merge_base
        try:
            base = merge_base(project.root, args.base)
        except DiffError as e:
            raise UsageError(str(e))
    project.landed = args.landed
    try:
        return project.results(declared=declared, base=base)
    except ProjectError as e:
        raise UsageError(str(e))


def _print_errors(results, max_files: int, file=None) -> None:
    by_error = defaultdict(list)
    for r in results:
        for e in r.errors:
            by_error[e].append(r.path)
    for error, paths in sorted(by_error.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        print(f"✗ {printable(error)}: {len(paths)} file(s)", file=file)
        for p in paths[:max_files]:
            print(f"    {printable(p)}", file=file)
        if len(paths) > max_files:
            print(f"    … and {len(paths) - max_files} more", file=file)


def _waiting(results) -> str | None:
    """A note about the lines that wait for their pull request's declaration, if there are any."""
    waiting = sum(p.lines for r in results for p in r.parts or () if p.advisory and p.errors)
    if not waiting:
        return None
    return (f"{waiting} line(s) that aren't on the default branch yet are not fully declared: the pull request "
            "that lands them declares them (--declare-from reads its description)")


def cmd_lint(args) -> int:
    project = _open(args.root)
    results = _history_results(project, args)
    if not results:
        print(f"✗ no files found below {project.root}")
        return 1
    files = [r.path for r in results]
    unused = project.unused_annotations(files)

    for problem in project.history_problems:
        print(f"✗ {printable(problem)}")
    _print_errors(results, args.max_files)
    for index in unused:
        print(f"{'✗' if args.strict else '!'} {project.config.path.name} annotation [{index}] matches no file")
    for warning in project.history_warnings:
        print(f"{'✗' if args.strict else '!'} {printable(warning)}")

    for note in project.history_notes:
        print(f"! {printable(note)}")
    waiting = _waiting(results)
    if waiting:
        print(f"! {waiting}")

    bad = sum(1 for r in results if r.errors)
    print()
    print(f"{len(results) - bad} of {len(results)} files have a valid declaration.")
    if project.history_used:
        lines = sum(p.lines for r in results for p in r.parts or ())
        bad_lines = sum(p.lines for r in results for p in r.parts or () if p.errors and not p.advisory)
        print(f"{lines - bad_lines} of {lines} lines have a valid declaration (line by line, from git history).")
    failed = bad > 0 or bool(project.history_problems) or (args.strict and (unused or project.history_warnings))
    if failed:
        print(f"See {SPEC_URL}")
    else:
        print("All files are declared. ✓")
    return 1 if failed else 0


# ---------------------------------------------------------------- report
def cmd_report(args) -> int:
    if args.markdown and not args.tree:
        raise UsageError("--markdown needs --tree")
    if args.depth is not None and not args.tree:
        raise UsageError("--depth needs --tree")
    if args.depth is not None and args.depth < 0:
        raise UsageError("--depth must be 0 or more")
    if args.tree and args.json and args.markdown:
        raise UsageError("give --json or --markdown, not both")
    project = _open(args.root)
    results = _history_results(project, args)
    if (args.with_source or args.since) and not args.html:
        raise UsageError("--with-source and --since need --html")
    if args.html or args.tree:
        from . import visualize
        tree = visualize.build_tree(project.root, results)
        if args.html:
            since = changes = None
            if args.since:
                from .diff import DiffError
                try:
                    sha, changes = visualize.changed_since(project.root, args.since, [r.path for r in results])
                except DiffError as e:
                    raise UsageError(str(e))
                since = {"name": args.since, "commit": sha}
            html_tree = visualize.build_tree(project.root, results, source=args.with_source, changes=changes) \
                if (args.with_source or changes is not None) else tree
            meta = visualize.report_meta(project.root, title=args.title, since=since)
            target = Path(args.html)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(visualize.render_html(html_tree, meta), encoding="utf-8")
            except OSError as e:
                raise UsageError(f"cannot write {target}: {e}")
            print(f"Wrote {args.html}", file=sys.stderr if args.tree else sys.stdout)
        if not args.tree:
            return 0
        if args.json:
            print(json.dumps({**_json_header(), **tree}, indent=2, ensure_ascii=False))
        elif args.markdown:
            print(visualize.render_markdown(tree, args.weight, args.depth, args.files))
            if _waiting(results):
                print(f"\n_{_waiting(results)}_")
        else:
            print(visualize.render_text(tree, args.weight, args.depth, args.files))
            if _waiting(results):
                print(f"\nnote: {_waiting(results)}")
        return 0
    if args.json:
        print(json.dumps({**_json_header(), "files": [_result_json(r) for r in results]},
                         indent=2, ensure_ascii=False))
        return 0
    if args.files:
        width = max((len(r.path) for r in results), default=4)
        for r in results:
            status = "✓" if not r.errors else "✗"
            if r.parts is not None and len(r.parts) > 1:
                total = sum(p.lines for p in r.parts)
                shares = Counter()
                for p in r.parts:
                    shares[counted_short(p.declaration, p.errors)] += p.lines
                what = " · ".join(f"{k} {100 * n / total:.0f}%" for k, n in shares.most_common())
                line = f"{status} {r.path:<{width}}  {what}"
            else:
                line = f"{status} {r.path:<{width}}  {r.declaration.short()}  ({r.declaration.source})"
            if r.errors:
                line += "  " + "; ".join(r.errors)
            print(line)
        return 0
    weight = "lines" if project.history_used else "files"
    units = defaultdict(float)
    for r in results:
        for _, _, w in weighted_parts(project.root, r, weight):
            units["all"] += w
    total = units["all"] or 1
    print(f"{len(results)} files" + (f", {int(total)} lines, declared line by line" if weight == "lines" else "") + "\n")
    for key, _, title, levels, _, _ in AXIS_INFO:
        counts = Counter()
        for r in results:
            for d, errors, w in weighted_parts(project.root, r, weight):
                counts[counted_level(d, errors, key)] += w
        print(title)
        for level, name in list(levels.items()) + [("undeclared", "missing or invalid declaration")]:
            if counts[level]:
                print(f"  {level:<10} {name:<38} {counts[level]:>5g}  {100 * counts[level] / total:5.1f}%")
        print()
    if _waiting(results):
        print(f"note: {_waiting(results)}")
    return 0


# Version of the --json output of report and diff. Raised only for changes that can break a
# reader (a key removed, renamed or with a new meaning); new keys may appear at any time.
JSON_FORMAT = 1


def _json_header() -> dict:
    return {"format": JSON_FORMAT, "aisignoff": __version__}


def _result_json(r) -> dict:
    out = {"path": r.path, **r.declaration.as_dict(), "errors": r.errors}
    if r.parts is not None:
        # kinds: where each axis comes from (commit, branch, attestation, file, declared, frozen; null: nowhere)
        out["parts"] = [{"lines": p.lines, "runs": p.runs, **p.declaration.as_dict(), "errors": p.errors,
                         "kinds": dict(zip((GEN, HUM, AIR), p.kinds)), "advisory": p.advisory}
                        for p in r.parts]
    return out


# ---------------------------------------------------------------- annotate
def _real(path: str) -> str:
    """Absolute path with symlinked directories resolved, but not the last component."""
    a = os.path.abspath(path)
    return os.path.join(os.path.realpath(os.path.dirname(a)), os.path.basename(a))


def _pattern(root: Path, arg: str) -> str:
    """Turn a command-line argument into a pattern relative to the project root.

    Existing files and directories are escaped so they match exactly (even with * or ?
    in their name); symlinks are not followed. Anything else is a glob, taken relative
    to the current directory like the shell would.
    """
    root_real = os.path.realpath(root)
    if os.path.lexists(arg):
        if os.path.realpath(arg) == root_real:
            return "**"  # the project root itself, also when named through a symlink
        full = _real(arg)
        rel = os.path.relpath(full, root_real)
        if rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel):
            raise UsageError(f"{arg} is outside the project root {root}")
        rel = Path(rel).as_posix()
        if os.path.isdir(full) and not os.path.islink(full):
            return "**" if rel == "." else escape(rel) + "/**"
        return escape(rel)
    if not any(c in arg for c in "*?"):
        raise UsageError(f"{arg} does not exist (quote glob patterns)")
    if os.path.isabs(arg) or ".." in Path(arg).parts:
        raise UsageError(f"glob {arg!r}: use a pattern relative to the current directory, without '..'")
    pattern = arg.removeprefix("./")
    cwd_rel = os.path.relpath(os.path.realpath(os.getcwd()), root_real)
    if cwd_rel == ".." or cwd_rel.startswith(".." + os.sep):
        return pattern  # working outside the project: globs are relative to the root
    if cwd_rel != ".":
        pattern = escape(Path(cwd_rel).as_posix()) + "/" + pattern
    return pattern


def _append_annotation(root: Path, patterns: list[str], values: dict, precedence: str | None,
                       comments: list[str] = ()) -> Path:
    block = ["", *[f"# {c}" for c in comments], "[[annotations]]",
             f"path = {_toml_value(patterns[0] if len(patterns) == 1 else patterns)}"]
    if precedence:
        block.append(f'precedence = "{precedence}"')
    block += [f"{k} = {_toml_value(v)}" for k, v in values.items()]
    return _append_toml(root, block)


def _append_toml(root: Path, block: list[str]) -> Path:
    """Append lines to SIGNOFF.toml; restore it if the result is no longer valid."""
    try:
        target = config_path(root)  # AIDECL.toml in a repository that isn't migrated yet
    except ConfigError as e:
        raise UsageError(str(e))
    old = target.read_text(encoding="utf-8") if target.exists() else None
    text = old if old is not None else f"version = {VERSION}\n"
    if not text.endswith("\n"):
        text += "\n"
    target.write_text(text + "\n".join(block) + "\n", encoding="utf-8")
    try:
        load(root)  # make sure the result is still a valid SIGNOFF.toml
    except ConfigError as e:
        if old is None:
            target.unlink()
        else:
            target.write_text(old, encoding="utf-8")
        raise UsageError(f"{e}; {target.name} was left unchanged")
    return target


def cmd_annotate(args) -> int:
    root = Path(args.root)
    if not root.is_dir():
        raise UsageError(f"project root {root} is not a directory")
    values = _values(args)
    _check_complete(values, _policy(root))

    if args.inline:
        if args.precedence:
            raise UsageError("--precedence only applies to SIGNOFF.toml, not to --inline")
        status = 0
        for arg in args.paths:
            path = Path(arg)
            if not path.is_file():
                print(f"aisignoff annotate: {arg} does not exist or is not a file", file=sys.stderr)
                status = 1
                continue
            rel = os.path.relpath(_real(arg), os.path.realpath(root))
            if rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel):
                print(f"aisignoff annotate: {arg} is outside the project root {root}", file=sys.stderr)
                status = 1
                continue
            try:
                inline.write(path, values)
                print(f"Tagged {path}")
            except (ValueError, OSError, UnicodeDecodeError) as e:
                print(f"aisignoff annotate: {e}", file=sys.stderr)
                status = 1
        return status

    patterns = [_pattern(root, a) for a in args.paths]
    target = _append_annotation(root, patterns, values, args.precedence)
    print(f"Added an annotation for {', '.join(patterns)} to {target}")
    return 0


# ---------------------------------------------------------------- attest
def _git_out(root: Path, *args: str) -> str | None:
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    except FileNotFoundError:
        raise UsageError("git is not installed")
    return r.stdout.strip() if r.returncode == 0 else None


def cmd_attest(args) -> int:
    project = _open(args.root)
    root = project.root
    if _git_out(root, "rev-parse", "--is-inside-work-tree") != "true":
        raise UsageError("attestations need a git repository")
    values = _values(args)
    if GEN in values or ASSISTED in values:
        raise UsageError("an attestation records a review (-H, -a): the generation of a line is declared by "
                         "the commit that landed it, and corrected with a [[commits]] entry")
    given = [k for k in (HUM, AIR) if k in values]
    if not given:
        raise UsageError("give at least one review level to attest (-H or -a)")
    if any(v == TODO or (isinstance(v, list) and TODO in v) for v in values.values()):
        raise UsageError("an attestation records a check that was done: TODO isn't allowed")
    problems = [e for e in validate(Declaration.from_mapping(values, "command line"))
                if not any(e == f"missing {k}" for k in (GEN, HUM, AIR))]
    if problems:
        raise UsageError("incomplete declaration: " + "; ".join(problems))

    files = set(project.files())
    chosen: list[str] = []
    for arg in args.paths:
        if not os.path.lexists(arg):
            raise UsageError(f"{arg} does not exist")
        rel = os.path.relpath(_real(arg), str(root))
        if rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel):
            raise UsageError(f"{arg} is outside the project root {root}")
        rel = "" if rel == "." else Path(rel).as_posix()
        if os.path.isdir(arg) and not os.path.islink(arg):
            found = sorted(f for f in files if not rel or f.startswith(rel + "/"))
            if not found:
                raise UsageError(f"{arg} contains no declared files")
            chosen += [f for f in found if f not in chosen]
        elif rel in files:
            if rel not in chosen:
                chosen.append(rel)
        else:
            raise UsageError(f"{arg} is not a file that needs a declaration (excluded or ignored?)")
    for rel in chosen:
        annotation = project.config.match(rel)
        if annotation is not None and annotation.precedence == "override":
            raise UsageError(f'{rel} is declared by an annotation with precedence = "override", which an '
                             "attestation can't raise; change the annotation instead (aisignoff annotate)")

    block = []
    for rel in chosen:
        if args.at:
            blob = _git_out(root, "rev-parse", "--verify", "--quiet", f"{args.at}:./{rel}")  # relative to root
            if not blob:
                raise UsageError(f"{rel} does not exist at {args.at} (for a file renamed since, write the entry "
                                 "by hand with the blob of its old path)")
        else:
            blob = _git_out(root, "hash-object", "--", rel)
        if not blob:
            raise UsageError(f"cannot hash {rel}")
        block += ["", "[[attestations]]", f"path = {_toml_str(rel)}", f'blob = "{blob}"']
        block += [f"{k} = {_toml_value(v)}" for k, v in values.items()]
    target = _append_toml(root, block)
    what = " ".join(values[k] for k in given)
    print(f"Attested {len(chosen)} file(s) at {what}" + (f" as of {args.at}" if args.at else "") + f" in {target.name}")
    if not project.config.history.enabled:
        print("note: attestations count only with [history] enabled in SIGNOFF.toml")
    return 0


# ---------------------------------------------------------------- freeze
def _prune_toml(root: Path, annotations: int) -> None:
    """Remove the [[commits]] and [[attestations]] tables from SIGNOFF.toml, with the comment
    lines directly above each; the file is restored if the result isn't what was meant."""
    import re
    target = config_path(root)
    old = target.read_text(encoding="utf-8")
    header = re.compile(r"^\s*\[")
    doomed = re.compile(r"^\s*\[\[\s*(commits|attestations)\s*\]\]\s*(#.*)?$")
    kept: list[str] = []
    skipped: list[str] = []
    skipping = False
    for line in old.splitlines():
        if header.match(line):
            was, skipping = skipping, bool(doomed.match(line))
            if skipping:
                while kept and kept[-1].lstrip().startswith("#"):
                    kept.pop()
            elif was:
                # the comment lines right above this table, after a blank line, are this table's
                block: list[str] = []
                while skipped and skipped[-1].lstrip().startswith("#"):
                    block.insert(0, skipped.pop())
                if block and (not skipped or not skipped[-1].strip()):
                    kept.extend(["", *block])
            skipped = []
        if skipping:
            skipped.append(line)
        else:
            kept.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).rstrip("\n") + "\n"
    target.write_text(text, encoding="utf-8")
    try:
        config = load(root)
        if config.commits or config.attestations or len(config.annotations) != annotations:
            raise ConfigError("the entries could not be taken out cleanly")
    except ConfigError as e:
        target.write_text(old, encoding="utf-8")
        raise UsageError(f"{e}; {target.name} was left unchanged, and no snapshot was written")


def cmd_freeze(args) -> int:
    from .history import SNAPSHOT, Snapshot
    project = _open(args.root)
    root = project.root
    if not project.config.history.enabled:
        raise UsageError("a snapshot records line-by-line declarations: enable [history] in SIGNOFF.toml first")
    if args.check:
        if args.reset or args.prune:
            raise UsageError("--check only checks: it can't go with --reset or --prune")
        if not (root / SNAPSHOT).is_file():
            raise UsageError(f"there is no {SNAPSHOT} to check")
        project.check_snapshot = False
        _results(project)
        problems, notes = project.verify_snapshot()
        for line in project.history_problems + problems:
            print(f"✗ {printable(line)}")
        for line in notes:
            print(f"! {printable(line)}")
        if not problems and not notes and not project.history_problems:
            print(f"{SNAPSHOT} is what 'aisignoff freeze' writes at its commit. ✓")
        return 1 if problems or project.history_problems else 0
    reset = []
    for arg in args.reset or ():
        rel = os.path.relpath(_real(arg), str(root))
        if rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel) or not os.path.isfile(arg):
            raise UsageError(f"--reset {arg}: give files of the project")
        reset.append(Path(rel).as_posix())
    project.reset = set(reset)
    results = _results(project)
    history = project.history
    if history is None:
        raise UsageError("a snapshot needs the whole git history (not a shallow clone)")
    if history.base is None:
        raise UsageError("there is no commit to freeze yet")
    dirty = [line[3:] for line in (_git_out(root, "status", "--porcelain", "--untracked-files=all") or "").splitlines()
             if line[3:].strip('"') != (history.prefix + SNAPSHOT)]
    if history.head != history.base or dirty:
        what = "the working tree has changes" if history.head == history.base else \
            f"HEAD has commits that aren't on the default branch (its newest commit here is {history.base[:7]})"
        raise UsageError(f"a snapshot is taken of a commit of the default branch, but {what}. Check that commit "
                         f"out with nothing else changed (git switch --detach {history.base[:7]}), run 'aisignoff "
                         f"freeze', and commit {SNAPSHOT} from there, on a new branch if you use pull requests")
    bad = [r.path for r in results if r.errors]
    if bad or project.history_problems:
        for problem in project.history_problems:
            print(f"✗ {printable(problem)}", file=sys.stderr)
        _print_errors(results, 10, file=sys.stderr)
        raise UsageError("'aisignoff lint' fails here"
                         + (f" ({len(bad)} file(s))" if bad else "")
                         + "; a snapshot would keep those errors for good, so fix them first")
    if project.history_warnings and not args.allow_warnings:
        for warning in project.history_warnings:
            print(f"! {printable(warning)}", file=sys.stderr)
        raise UsageError("'aisignoff lint' has warnings here; a snapshot would keep the levels they are about "
                         "for good, so settle them first (or pass --allow-warnings)")
    archive = list(history.snapshot.archive) if history.snapshot else []
    pruned = 0
    if args.prune:
        config = project.config
        entries = {"commit": history.base,
                   "commits": [{"commit": c.commit, **c.values} for c in config.commits],
                   "attestations": [{"path": a.path, "blob": a.blob, **a.values} for a in config.attestations]}
        pruned = len(entries["commits"]) + len(entries["attestations"])
        if pruned:
            archive.append(entries)
            _prune_toml(root, len(config.annotations))
    text, files, lines = Snapshot.render(history.base, __version__, results, history.base_blobs, archive, reset)
    target = root / SNAPSHOT
    again = target.exists()
    target.write_text(text, encoding="utf-8")
    print(f"{'Updated' if again else 'Wrote'} {SNAPSHOT}: the levels of {lines} lines in {files} files as of commit "
          f"{history.base[:7]}.")
    if pruned:
        print(f"Moved {pruned} [[commits]] and [[attestations]] entries from {project.config.path.name} into its "
              "archive: the snapshot has their levels. Commit both files together.")
    print("Commit it. Lines that don't change keep these levels; lines changed after that commit are declared "
          "by the commits that land them.")
    return 0


# ---------------------------------------------------------------- diff
def cmd_diff(args) -> int:
    from . import diff
    if args.json and args.markdown:
        raise UsageError("give --json or --markdown, not both")
    if args.depth < 0:
        raise UsageError("--depth must be 0 or more")
    project = _open(args.root)
    declared = _declared(args)
    try:
        data = diff.compute(project, args.base, declared, depth=args.depth, by_file=args.files)
    except (diff.DiffError, ProjectError) as e:
        raise UsageError(str(e))
    if args.json:
        print(json.dumps({**_json_header(), **data}, indent=2, ensure_ascii=False))
    elif args.markdown:
        print(diff.render_markdown(data))
    else:
        print(diff.render_text(data))
    return 0


# ---------------------------------------------------------------- badge
def percentages(counts: dict) -> dict:
    """Integer percentages that sum to 100 (largest-remainder method)."""
    total = sum(counts.values())
    exact = {k: 100 * v / total for k, v in counts.items()}
    result = {k: math.floor(x) for k, x in exact.items()}
    rest = 100 - sum(result.values())
    for k in sorted(exact, key=lambda k: exact[k] - result[k], reverse=True)[:rest]:
        result[k] += 1
    return result


def badge_json(label: str, counts: Counter, keys: list[str], color: str) -> dict:
    shown = {k: counts[k] for k in keys if counts[k]}
    if not shown:
        return {"schemaVersion": 1, "label": label, "message": "no files", "color": "lightgrey"}
    pct = percentages(shown)
    parts = [f"{k} {pct[k]}%" if pct[k] else f"{k} <1%" for k in shown]
    return {"schemaVersion": 1, "label": label, "message": " · ".join(parts),
            "color": "red" if counts["undeclared"] else color}


def cmd_badge(args) -> int:
    project = _open(args.root)
    project.landed = args.landed
    results = _results(project)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    suffix = "" if args.weight == "files" else f" ({args.weight})"
    written = []
    for key, _, title, levels, filename, color in AXIS_INFO:
        counts = Counter()
        for r in results:
            for d, errors, w in weighted_parts(project.root, r, args.weight):
                counts[counted_level(d, errors, key)] += w
        label = {GEN: "AI generation", HUM: "human review", AIR: "AI review"}[key] + suffix
        (out / filename).write_text(json.dumps(badge_json(label, counts, [*levels, "undeclared"], color),
                                               ensure_ascii=False))
        written.append(str(out / filename))
    print("Wrote " + ", ".join(written))
    return 0


# ---------------------------------------------------------------- migrate
def migrate_values(old: dict) -> tuple[dict, list[str]]:
    """Map a version-1 declaration (V0-V3) to G/H/A. Returns (values, keys a human must add).

    V0 (human ran the tests and reviewed line by line) -> H2, AI review unknown (A0 for G0)
    V1 / V2 (independent agent, same / different model)  -> A2, human review unknown
    V3 (human + independent agent)                       -> H2 + A2
    A3 needs an extensive review or benchmark, which V2 doesn't record, so V2 becomes A2 too.
    """
    get = {canonical_key(k, (GEN, ASSISTED, "AI-Verification", "Verified-by", "Tested-by")): v
           for k, v in old.items()}
    values: dict = {}
    if get.get(GEN):
        values[GEN] = get[GEN]
    if get.get(ASSISTED):
        values[ASSISTED] = get[ASSISTED]
    v = get.get("AI-Verification")
    tested, verified = get.get("Tested-by"), get.get("Verified-by")
    if v in ("V0", "V3"):
        values[HUM] = "H2"
        if tested:
            values[REVIEWED] = tested
    if v in ("V1", "V2", "V3"):
        values[AIR] = "A2"
    elif v == "V0" and values.get(GEN) == "G0":
        values[AIR] = "A0"
    if values.get(AIR) not in (None, "A0") and verified:
        values[AI_REVIEWED] = verified
    todo = [k for k in (GEN, HUM, REVIEWED, AIR) if k not in values]
    if values.get(AIR) not in (None, "A0") and AI_REVIEWED not in values:
        todo.append(AI_REVIEWED)
    return values, todo


# version 2 -> 3: the AI review scale moved up by one (see model.py)
_AI_V2 = {"A-": "A0", "A0": "A1", "A1": "A2", "A2": "A2", "A3": "A3"}
_NOTE_A2 = ("was A2 (different model). A3 now also requires an extensive review or benchmark: "
            "raise it to A3 if that applies")


def map_ai_v2(level, generation) -> tuple[str | None, str | None]:
    """New AI-Review for a version-2 value: (value, note). Value TODO if it can't be mapped."""
    if not isinstance(level, str):
        return level, None
    if level == "A0" and generation == "G0":
        return TODO, ("was A0 (self-check) on human-written content, which the new scale doesn't have: "
                      "A0 if there was no AI review, A2 or A3 if there was one")
    if level not in _AI_V2:
        return level, None  # TODO or invalid: left for lint
    return _AI_V2[level], (_NOTE_A2 if level == "A2" else None)


def _toml_key(name: str) -> str:
    return name.strip().strip('"').strip("'")


def _split_comment(line: str) -> tuple[str, str]:
    """Split a TOML line into code and trailing comment (a '#' outside strings)."""
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "#":
            return line[:i], line[i:]
        i += 1
    return line, ""


def migrate_toml_v2(text: str, data: dict, name: str = FILENAME) -> tuple[str, list[str], int]:
    """Rewrite a version-2 SIGNOFF.toml line by line, keeping comments and layout.
    Returns (new text, notes, number of TODOs). Raises UsageError if the layout is too unusual
    to convert safely (checked by comparing the parsed result with the expected one)."""
    import copy
    import re
    import tomllib

    annotations = data.get("annotations", [])
    expected = copy.deepcopy(data)
    expected["version"] = VERSION
    notes, todos = [], 0
    plan = {}  # annotation index -> (new value, note)
    for i, table in enumerate(annotations if isinstance(annotations, list) else []):
        if not isinstance(table, dict):
            continue
        get = {canonical_key(k): k for k in table}
        if AIR not in get:
            continue
        g = table.get(get[GEN]) if GEN in get else None
        new, note = map_ai_v2(table[get[AIR]], g)
        plan[i] = (new, note)
        expected["annotations"][i][get[AIR]] = new
        if new == TODO:
            todos += 1
        if note:
            notes.append(f"{FILENAME} annotation [{i + 1}]: {note}")
    policy = expected.get("policy")
    if isinstance(policy, dict):
        for gen, req in policy.items():
            if isinstance(req, dict) and isinstance(req.get("ai"), str) and req["ai"] in _AI_V2:
                if req["ai"] == "A2":
                    notes.append(f"{FILENAME} [policy] {gen}: ai = \"A2\" (different model) is now A2 "
                                 "(new session); use A3 to keep requiring a different model")
                req["ai"] = _AI_V2[req["ai"]]

    header = re.compile(r"^\s*(\[\[?)\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")
    level_line = re.compile(r"""^(\s*)(["']?[A-Za-z-]+["']?)(\s*=\s*)(["'])([^"']*)(\4)(.*)$""", re.S)
    out, section, index = [], None, -1
    for line in text.splitlines(keepends=True):
        m = header.match(line)
        if m:
            section = m.group(2).strip()
            if m.group(1) == "[[" and section == "annotations":
                index += 1
            out.append(line)
            continue
        eol = "\r\n" if line.endswith("\r\n") else "\n"
        if section is None:
            line = re.sub(r"^(\s*version\s*=\s*)2(\s*(#.*)?)$", rf"\g<1>{VERSION}\g<2>", line, flags=re.S)
        elif section == "annotations" and index in plan:
            m = level_line.match(line)
            if m and canonical_key(_toml_key(m.group(2))) == AIR:
                new, note = plan[index]
                if new == TODO:
                    out.append(f"{m.group(1)}# TODO after migration: {note}{eol}")
                elif note:
                    out.append(f"{m.group(1)}# Note from migration: {note}{eol}")
                line = f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}{new}{m.group(6)}{m.group(7)}"
        elif section == "policy" or section.startswith("policy.") or section.startswith('"policy".'):
            code, comment = _split_comment(line)
            code = re.sub(r"""((?:\bai|"ai"|'ai')\s*=\s*)(["'])(A-|A[0-3])(\2)""",
                          lambda m: f"{m.group(1)}{m.group(2)}{_AI_V2[m.group(3)]}{m.group(4)}", code)
            line = code + comment
        out.append(line)
    new_text = "".join(out)
    try:
        ok = tomllib.loads(new_text) == expected
    except tomllib.TOMLDecodeError:
        ok = False
    if not ok:
        raise UsageError(
            f"{name} is laid out in a way 'migrate' can't convert safely. Nothing was changed. "
            "Rewrite the unusual parts as plain lines (one [[annotations]] table per annotation, "
            "AI-Review = \"...\" and ai = \"...\" on their own lines), keep version = 2 and the old levels, "
            "then run 'aisignoff migrate' again. It converts SIGNOFF.toml and the inline tags together")
    return new_text, notes, todos


def _toml_generation(data: dict | None, path: str):
    """AI-Generation of the last version-2 annotation matching path (None if none)."""
    from .globbing import matches
    g = None
    for table in (data or {}).get("annotations", []) or []:
        if not isinstance(table, dict):
            continue
        pats = table.get("path")
        pats = [pats] if isinstance(pats, str) else (pats if isinstance(pats, list) else [])
        if any(isinstance(pt, str) and matches(pt, path) for pt in pats):
            keys = {canonical_key(k): k for k in table}
            g = table.get(keys[GEN]) if GEN in keys else g
    return g


def cmd_migrate(args) -> int:
    root = Path(args.root)
    if not root.is_dir():
        raise UsageError(f"project root {root} is not a directory")
    changes = []
    todos = 0

    # SIGNOFF.toml, or AIDECL.toml from before the rename (converted and renamed to SIGNOFF.toml)
    data = None
    try:
        source = config_path(root)
        data = read_toml(root)
    except ConfigError as e:
        raise UsageError(str(e))
    legacy = source.name == LEGACY_FILENAME
    new_text = None
    warnings, notes = [], []
    version = data.get("version") if data is not None else None
    if version == 1:
        lines = [
            "# AI declarations (migrated from version 1 by 'aisignoff migrate').",
            f"# Scheme: {SPEC_URL}",
            f"version = {VERSION}",
        ]
        if data.get("exclude"):
            lines += ["", f"exclude = {_toml_value(list(data['exclude']))}"]
        if "policy" in data:
            warnings.append(f"{source.name}: version 1 had no [policy]; the table was dropped, add it again by hand")
        old_keys = (GEN, ASSISTED, "AI-Verification", "Verified-by", "Tested-by")
        for i, table in enumerate(data.get("annotations", []), start=1):
            if not isinstance(table, dict) or "path" not in table:
                raise UsageError(f"{source.name} annotation [{i}] has no 'path'; fix it, then run migrate again")
            rest = {k: v for k, v in table.items() if k not in ("path", "precedence")}
            for k in rest:
                if canonical_key(k, old_keys) is None:
                    warnings.append(f"{source.name} annotation [{i}]: key '{k}' is not part of the scheme and was dropped")
            values, todo = migrate_values(rest)
            todos += bool(todo)
            lines.append("")
            if todo:
                lines.append(f"# TODO after migration: add {', '.join(todo)}")
            lines.append("[[annotations]]")
            lines.append(f"path = {_toml_value(table['path'])}")
            if table.get("precedence"):
                lines.append(f"precedence = {_toml_value(table['precedence'])}")
            lines += [f"{k} = {_toml_value(v)}" for k, v in values.items()]
        new_text = "\n".join(lines) + "\n"
        changes.append(f"{FILENAME}: version 1 -> {VERSION}")
    elif version == 2:
        new_text, toml_notes, n = migrate_toml_v2(source.read_bytes().decode("utf-8"), data, source.name)
        notes += toml_notes
        todos += n
        changes.append(f"{FILENAME}: version 2 -> {VERSION}")
    if legacy:
        if new_text is None:
            new_text = source.read_bytes().decode("utf-8")  # already version 3: only the name changes
        changes.insert(0, f"{LEGACY_FILENAME} -> {FILENAME}")

    # Inline tags. Blocks with the V0-V3 keys are always converted. Blocks with G/H/A keys use the
    # old AI review scale when SIGNOFF.toml is version 2; without SIGNOFF.toml, '--from 2' says so.
    # Afterwards SIGNOFF.toml is version 3 (created if needed), which records that inline tags
    # are on the new scale, so running migrate again never shifts them twice.
    if args.from_version == 2 and data is not None and version != 2:
        raise UsageError(f"{source.name} is version {version}, so inline tags are already read on its scale "
                         "(running --from 2 here could shift tags a second time). --from 2 is only for repositories "
                         "without SIGNOFF.toml. Convert remaining old tags by hand: A- -> A0, A0 -> A1, A1 -> A2")
    from_v2 = version == 2 or args.from_version == 2
    create_toml = args.from_version == 2 and data is None
    inline_updates = []
    seen_legacy_none = []
    several = []
    try:
        files = list_files(root.resolve())
    except ProjectError as e:
        raise UsageError(str(e))
    for f in files:
        if f in (FILENAME, LEGACY_FILENAME):
            continue
        found = inline.parse_values(root / f)
        if found is None:
            continue
        raw, problems = found
        is_v1 = any(k in raw for k in ("AI-Verification", "Verified-by", "Tested-by"))
        if not is_v1 and not (AIR in raw and from_v2):
            if raw.get(AIR) == "A-":
                seen_legacy_none.append(f)
            continue
        if any("more than one" in pr for pr in problems):
            several.append(f)
            continue
        if is_v1:
            values, todo = migrate_values(raw)
            # explicit TODO markers: an inline axis without its level line would otherwise be
            # filled in from SIGNOFF.toml, which would claim a review that never happened
            for key in todo:
                values[key] = [TODO] if key in LIST_KEYS else TODO
        else:
            values = dict(raw)
            g = raw.get(GEN) or _toml_generation(data if version == 2 else None, f)
            new, note = map_ai_v2(raw[AIR], g)
            if new == raw[AIR] and not note:
                continue
            values[AIR] = new
            todo = [AIR] if new == TODO else []
            if note:
                notes.append(f"{f}: {note}")
        todos += bool(todo)
        values = {k: values[k] for k in KEYS if k in values}
        inline_updates.append((f, values, todo))
        changes.append(f"{f}: inline tags" + (f" (TODO: {', '.join(todo)})" if todo else ""))
    if several:
        # converting the rest would leave these on the old scale, read as the new one
        raise UsageError(f"{', '.join(several)}: more than one inline declaration block (an example of the "
                         "format counts too). Leave one block per file, then run migrate again. Nothing was changed")
    if create_toml and inline_updates:
        new_text = f"# Created by 'aisignoff migrate --from 2': inline tags use the AI review scale of version {VERSION}.\nversion = {VERSION}\n"
        changes.insert(0, f"{FILENAME}: created (version {VERSION})")

    for w in warnings:
        print(f"warning: {w}")
    if not changes:
        print("Nothing to migrate.")
        if seen_legacy_none:
            print(f"{len(seen_legacy_none)} file(s) use 'AI-Review: A-' from version 2, e.g. {seen_legacy_none[0]}.")
            if data is None:
                print("If all inline tags still use the old scale, run 'aisignoff migrate --from 2'.")
            else:
                print(f"{source.name} is already version {version}: convert the old tags in these files by hand "
                      "(A- -> A0, A0 -> A1, A1 -> A2).")
        return 0
    if args.dry_run:
        for c in changes:
            print("would migrate " + c)
        for n in notes:
            print(f"note: {n}")
        return 0
    # All or nothing: inline tags first (restored if any fails), SIGNOFF.toml last, so a
    # partly migrated repository can't be migrated a second time.
    backups = {}
    try:
        for f, values, _ in inline_updates:
            path = root / f
            backups[path] = path.read_bytes()
            inline.write(path, values)
    except (ValueError, OSError, UnicodeDecodeError) as e:
        for path, content in backups.items():
            path.write_bytes(content)
        raise UsageError(f"{e}. Nothing was changed")
    if new_text is not None:
        target = root / FILENAME
        old_bytes = target.read_bytes() if target.exists() else None
        legacy_bytes = source.read_bytes() if legacy else None
        if legacy:
            source.unlink()
        target.write_bytes(new_text.encode("utf-8"))
        try:
            load(root)
        except ConfigError as e:
            if old_bytes is None:
                target.unlink()
            else:
                target.write_bytes(old_bytes)
            if legacy_bytes is not None:
                source.write_bytes(legacy_bytes)
            for path, content in backups.items():
                path.write_bytes(content)
            raise UsageError(f"the converted {FILENAME} would be invalid ({e}); fix the old file first. "
                             "Nothing was changed")
    for c in changes:
        print("migrated " + c)
    for n in notes:
        print(f"note: {n}")
    if todos:
        print("\nSome declarations need information the old levels don't contain (marked TODO).")
        print("'aisignoff lint' fails until they are filled in.")
    return 0


# ---------------------------------------------------------------- main
def _add_values(p: argparse.ArgumentParser, required: bool) -> None:
    # TODO is a placeholder for a value a person fills in later (e.g. -H TODO --reviewed-by TODO
    # when an agent declares its part); 'lint' reports it until then.
    p.add_argument("-g", "--generation", choices=[*GENERATION, TODO], required=required)
    p.add_argument("-H", "--human", choices=[*HUMAN, TODO], required=required,
                   help="human review level (TODO: left for a person)")
    p.add_argument("-a", "--ai", choices=[*AI, TODO], required=required, help="AI review level")
    p.add_argument("--assisted-by", action="append", metavar="TOOL", help="repeatable (G1-G3)")
    p.add_argument("--reviewed-by", action="append", metavar="PERSON",
                   help="repeatable; the responsible human (always required; TODO: left for a person)")
    p.add_argument("--ai-reviewed-by", action="append", metavar="MODEL", help="repeatable (A1-A3)")


def _add_history_options(p) -> None:
    _add_declare_from(p)
    p.add_argument("--base", metavar="REV", help="with --declare-from: the branch the pull request goes into "
                   "(a pull request into another branch than the default one declares nothing)")
    _add_landed(p)
    p.set_defaults(generation=None, human=None, ai=None, assisted_by=None, reviewed_by=None, ai_reviewed_by=None)


def _add_landed(p) -> None:
    p.add_argument("--landed", action="store_true", help="[history]: HEAD is a commit of the default branch, or "
                   "lands on it as it is (a merge queue's commit, a release branch): every commit must declare "
                   "its lines as on the default branch")


def _add_declare_from(p) -> None:
    p.add_argument("--declare-from", metavar="FILE", help="declare the change from the text of its pull request "
                   "description (- for standard input), read as the merge or squash commit's message will be")
    p.add_argument("--author", metavar="NAME", help="with --declare-from: who the human review of a ticked "
                   "template is by (the pull request's author)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aisignoff", description="Declare and check AI generation (G0-G3), "
                                     "human review (H0-H3) and AI review (A0-A3) of the files in a repository.")
    parser.add_argument("--version", action="version", version=f"aisignoff {__version__}")
    parser.add_argument("--root", default=".", help="project root containing SIGNOFF.toml (default: .)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help=f"create {FILENAME}")
    _add_values(p, required=False)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("lint", help="check that every file has a valid declaration")
    p.add_argument("--strict", action="store_true", help="also fail on warnings: annotations that match no file, "
                   "reverts and merges that own lines without declaring them")
    p.add_argument("--max-files", type=int, default=10, help="files listed per problem (default 10)")
    _add_history_options(p)
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("report", help="summary of the declarations")
    p.add_argument("--files", action="store_true", help="one line per file")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--tree", action="store_true", help="the level mix of each folder (with --files: and each file)")
    p.add_argument("--markdown", action="store_true", help="with --tree: a Markdown table, e.g. for a CI job summary")
    p.add_argument("--depth", type=int, metavar="N", help="with --tree: show folders down to depth N")
    p.add_argument("--weight", choices=["files", "lines"], default="files", help="with --tree: what the shares count")
    p.add_argument("--html", metavar="PATH", help="write an interactive folder report (a single HTML file)")
    p.add_argument("--title", help="title of the HTML report (default: the repository or folder name)")
    p.add_argument("--with-source", action="store_true",
                   help="with --html: embed the text of each file, for a line-by-line view in the report")
    p.add_argument("--since", metavar="BASE",
                   help="with --html: mark the lines changed since commit BASE, e.g. origin/main or the last release tag")
    _add_history_options(p)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("annotate", help=f"declare files in {FILENAME} (or inline with --inline)")
    p.add_argument("paths", nargs="+", help="files, directories or glob patterns (quote globs)")
    _add_values(p, required=True)
    p.add_argument("--inline", action="store_true", help="write tag comments into the files instead")
    p.add_argument("--precedence", choices=["closest", "override"])
    p.set_defaults(func=cmd_annotate)

    p = sub.add_parser("attest", help="re-declare whole files as checked now ([history])")
    p.add_argument("paths", nargs="+", help="files or directories")
    _add_values(p, required=False)
    p.add_argument("--at", metavar="REV", help="attest the files as they were at this commit instead")
    p.set_defaults(func=cmd_attest)

    p = sub.add_parser("diff", help="declarations of the lines changed since a commit")
    p.add_argument("base", help="the commit, branch or tag to compare with, e.g. origin/main")
    p.add_argument("--files", action="store_true", help="one row per file instead of per folder")
    p.add_argument("--depth", type=int, default=1, metavar="N", help="group by folders down to depth N (default 1)")
    p.add_argument("--markdown", action="store_true", help="a Markdown table, e.g. for a CI job summary")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    g = p.add_argument_group("declaring the change", "levels for changed lines that carry no declaration of their "
                             "own yet, e.g. from the pull request's template")
    g.add_argument("-g", "--generation", choices=[*GENERATION, TODO])
    g.add_argument("-H", "--human", choices=[*HUMAN, TODO])
    g.add_argument("-a", "--ai", choices=[*AI, TODO])
    g.add_argument("--assisted-by", action="append", metavar="TOOL")
    g.add_argument("--reviewed-by", action="append", metavar="PERSON")
    g.add_argument("--ai-reviewed-by", action="append", metavar="MODEL")
    _add_declare_from(g)
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("freeze", help="record the levels of every line as of the default branch's commit ([history])")
    p.add_argument("--prune", action="store_true", help=f"move the [[commits]] and [[attestations]] entries of "
                   f"{FILENAME} into the snapshot's archive: their levels are in the snapshot")
    p.add_argument("--reset", nargs="+", metavar="FILE", help="work these files out from history again (with "
                   "SIGNOFF.toml and the archive) instead of keeping their frozen levels")
    p.add_argument("--check", action="store_true", help="check that SIGNOFF.snapshot.json is what freeze writes at its "
                   "commit (lint does this when the file changed)")
    p.add_argument("--allow-warnings", action="store_true", help="freeze although lint has warnings (undeclared "
                   "reverts and merges: their lines keep the file-level declaration)")
    p.set_defaults(func=cmd_freeze)

    p = sub.add_parser("badge", help="write shields.io endpoint JSON files")
    p.add_argument("--out", default="badges", help="output directory (default: badges)")
    p.add_argument("--weight", choices=["files", "lines"], default="files")
    _add_landed(p)
    p.set_defaults(func=cmd_badge)

    p = sub.add_parser("migrate", help="convert declarations of versions 1 (V0-V3) and 2 (A-, A0-A3)")
    p.add_argument("--dry-run", action="store_true", help="only show what would change")
    p.add_argument("--from", dest="from_version", type=int, choices=[2],
                   help="without SIGNOFF.toml: treat inline G/H/A tags as version 2 and create a version-3 SIGNOFF.toml "
                        "that records the conversion")
    p.set_defaults(func=cmd_migrate)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except UsageError as e:
        print(f"aisignoff {args.command}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
