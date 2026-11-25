"""Command-line interface: aisignoff init | lint | report | annotate | attest | correct | gc | diff | badge | guide."""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import sys
import traceback
from collections import Counter, defaultdict
from pathlib import Path

from . import __version__, guide
from .config import FILENAME, VERSION, ConfigError, config_path, load, load_text
from .globbing import escape
from .model import (AI, AI_REVIEWED, AIR, ASSISTED, FINDINGS, FINDINGS_AXIS, FINDINGS_LEVELS, FINDINGS_REVIEWS, GEN,
                    GENERATION, HUM, HUMAN, NO_FINDINGS, REVIEWED, SEVERITIES, TODO, UNREVIEWED, Declaration, Policy, counted_findings, counted_level,
                    counted_short, findings_value, printable, valid_findings, validate)
from .project import Project, ProjectError, weighted_parts

SPEC_URL = ("https://github.com/industrial-mathematics-group/.github/blob/main/.github/"
            "CONTRIBUTING.md#ai-assisted-contributions")
AXIS_INFO = (  # key, short, title, levels, badge file, colour
    (GEN, "G", "Generation", GENERATION, "aisignoff-generation.json", "4063D8"),
    (HUM, "H", "Human review", HUMAN, "aisignoff-human-review.json", "389826"),
    (AIR, "A", "AI review", AI, "aisignoff-ai-review.json", "9558B2"),
)
FINDINGS_BADGE = "aisignoff-findings.json"


# exit codes: 0 fine, 1 lint found a problem, 2 the command couldn't run (usage, configuration, a file
# that can't be read or written), 3 an internal error (a bug in aisignoff)
EXIT_PROBLEMS, EXIT_USAGE, EXIT_INTERNAL = 1, 2, 3
DEFAULT_SKILLS = ".claude/skills"  # guide --skills without a folder: in the repository
ISSUES_URL = "https://github.com/industrial-mathematics-group/aisignoff/issues"


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
    findings = getattr(args, "findings", None)
    if findings:
        if values[AIR] not in FINDINGS_REVIEWS:
            raise UsageError(f"--findings belongs to an independent AI review: give it with -a A1, A2 or A3")
        values[FINDINGS] = findings_value(findings)
    return {k: v for k, v in values.items() if v}


def _policy(root: Path) -> Policy:
    try:
        config = load(root)
    except ConfigError as e:
        raise UsageError(str(e))
    _refuse_version_3(config)
    return config.policy


def _refuse_version_3(config) -> None:
    """Commands that write levels into SIGNOFF.toml take them on today's scale."""
    if config.version_3:
        raise UsageError(f"{config.path.name} says version = 3, the AI review scale before version 4, and this "
                         "command writes levels of today's scale: change the file over first (see 'Upgrading' in "
                         "the documentation)")


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
    try:
        config_path(root)  # refuses next to an AIDECL.toml that was never converted
    except ConfigError as e:
        raise UsageError(str(e))
    lines = [
        "# AI declarations for this repository: generation (G0-G3), human review (H0-H3)",
        "# and AI review (A0-A3).",
        f"# Scheme: {SPEC_URL}",
        "# The LAST annotation that matches a file wins. With [history], the commits that wrote",
        '# a line win over it unless the matching annotation sets precedence = "override".',
        f"version = {VERSION}",
        "",
        '# exclude = ["docs/build/**"]   # files that need no declaration (the review folder,',
        "# reviews/, needs none by itself)",
        "",
        "# Minimum review levels (optional).",
        "# [policy]",
        '# "*" = { human = "H1" }',
        '# G3  = { human = "H2", ai = "A1" }',
        "",
        "# A commit or pull request that declares A1-A3 says the highest severity its review found in",
        '# the change, in a line "AI-Review-Findings: minor" (none, trivial, minor, major, critical).',
        "# The reviewer only reviews; the finding is recorded, blocks nothing, and reports show it as",
        "# the findings level of the lines the review covered (F0-F3, F- for no independent review).",
        "",
    ]
    if args.history:
        lines += [
            "# Line-level declarations from git history: each line takes the levels of the commit that",
            '# wrote it (its "AI-Generation:" ... lines, or its pull request\'s template), and the',
            "# annotations below are the baseline for lines whose commit declares nothing.",
            "[history]",
            "enabled = true",
            '# undeclared = "error"                 # every commit on the default branch must declare its lines',
            '# require-trailers-since = "<commit>"  # ... from this commit on',
            '# merge-method = "merge"               # how pull requests land: merge, squash or rebase',
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
        alone = [flag for flag, v in (("--assisted-by", getattr(args, "assisted_by", None)),
                                      ("--reviewed-by", getattr(args, "reviewed_by", None)),
                                      ("--ai-reviewed-by", getattr(args, "ai_reviewed_by", None)),
                                      ("--findings", getattr(args, "findings", None))) if v]
        if alone:
            raise UsageError(f"{', '.join(alone)} goes with the levels: give --generation, --human and --ai as well")
        lines += [
            "# Example:",
            "# [[annotations]]",
            '# path = "**"',
            '# AI-Generation = "G0"',
            '# Human-Review = "H2"',
            '# AI-Review = "A0"',
            '# Reviewed-by = "Jane Doe"',
        ]
    if not args.no_agents_md:
        guide.check_pointer_files(root)  # before SIGNOFF.toml is written: init does all or nothing
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Created {target}")
    if not args.no_agents_md:
        for message in guide.point_agents(root):
            print(message)
    return 0


# ---------------------------------------------------------------- guide
def cmd_guide(args) -> int:
    root = Path(args.root)
    if not (args.role or args.skills or args.agents_md):
        raise UsageError("give --role dev or --role review (or --skills, --agents-md)")
    if args.skills or args.agents_md:
        if not root.is_dir():
            raise UsageError(f"project root {root} is not a directory")
        if args.agents_md:
            for message in guide.point_agents(root) or ["AGENTS.md is up to date"]:
                print(message)
        if args.skills:
            # the default is the repository's .claude/skills; a folder given is where it says, from here
            directory = root / DEFAULT_SKILLS if args.skills is True else Path(args.skills)
            for path in guide.write_skills(directory):
                print(f"Wrote {path}")
    if args.role:
        print(guide.full(args.role, root), end="")
    return 0


# ---------------------------------------------------------------- lint
def _declared(args, version_3: bool = False):
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
    from .history import findings_line, old_template, parse_message, parse_trailers
    try:
        text = sys.stdin.read() if args.declare_from == "-" else Path(args.declare_from).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise UsageError(f"cannot read {args.declare_from}: {e}")
    from .pullrequest import reviewer
    text = text.replace("\r\n", "\n")
    name, problems, notes = reviewer(text, args.author or "")
    # the check before the merge: on the scale the repository's SIGNOFF.toml says. Its "AI-Review-Findings:" line is checked with
    # the review report (_pull_request), and becomes the findings level of the lines the change lands
    pieces, both = parse_message(text, name, "the pull request description", version_3)
    args.pr_findings = findings_line(text)
    # whether its AI review is on today's scale, where A1-A3 give their findings (A2, A3 a report): in
    # version 4, and in version 3 for the ticked boxes of today's template (parse_message)
    args.pr_today = not version_3 or (old_template(text) is False and 2 not in parse_trailers(text, ""))
    pieces = {i: dataclasses.replace(p, kind="declared", problems=p.problems + ((both,) if both else ()))
              for i, p in pieces.items()}
    if 2 in pieces and pieces[2].level in FINDINGS_REVIEWS and args.pr_today and valid_findings(args.pr_findings):
        pieces[2] = dataclasses.replace(pieces[2], findings=findings_value(args.pr_findings))
    args.pr_pieces, args.pr_problems, args.pr_notes = pieces, problems, notes
    return pieces


def _load_base_rules(project: Project, args) -> None:
    """The rules of the branch the change goes into (--base): its [policy] applies to the
    change, which can't lower them itself, not even with --allow-policy-change, which lets it change
    them for the pull requests after it."""
    from .pullrequest import base_rules
    try:
        args.pr_rules = base_rules(project.root, args.base, project.config)
    except ConfigError as e:
        raise UsageError(str(e))
    if args.pr_rules.config is not None:
        project.config.policy = args.pr_rules.config.policy


def _description_scale(project: Project, args) -> bool:
    """Whether the pull request description is read on the AI review scale of version 3: the base
    branch's version, as for its other rules, so a change of version doesn't change how the pull
    request that makes it is read (ticked boxes of today's template are today's scale either way)."""
    rules = getattr(args, "pr_rules", None)
    if rules is not None and rules.config is not None:
        return rules.config.version_3
    return project.config.version_3


def _history_results(project: Project, args):
    """The results as lint and report see them: with the change that hasn't landed declared from
    --declare-from (from --base on), or with HEAD as a commit of the default branch (--landed)."""
    if args.base and args.declare_from is not None:
        _load_base_rules(project, args)
    declared = _declared(args, _description_scale(project, args))
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
        args.pr_merge_base = base
        # the rules of the branch the change goes into apply to it: it can't lower them itself, not even
        # with --allow-policy-change, which lets it change them for the pull requests after it
        if not hasattr(args, "pr_rules"):
            _load_base_rules(project, args)
    elif getattr(args, "allow_policy_change", False):
        raise UsageError("--allow-policy-change needs --base")
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


def _pull_request(project: Project, args) -> dict | None:
    """With --declare-from: the pull request's declaration as its description gives it, and what is
    wrong with it. The description must be complete on its own, also when the change has no lines to
    declare (such as one that changes only SIGNOFF.toml) and in a repository without SIGNOFF.toml,
    and the change can't alter the rules of the branch it goes into."""
    if args.declare_from is None:
        return None
    from .history import combine
    from .pullrequest import change_files, description_problems, review_folder_changes, review_problems
    if not hasattr(args, "pr_pieces"):
        _declared(args, _description_scale(project, args))
    rules = getattr(args, "pr_rules", None)
    declaration = combine([args.pr_pieces.get(i) for i in range(3)])
    out = {"applies": True, "declaration": declaration, "problems": [], "notes": list(args.pr_notes)}
    if project.history is not None and project.history.declared is None:
        out["applies"] = False  # it doesn't go into the default branch: the pull request that lands it there declares it
        return out
    base = getattr(args, "pr_merge_base", None) or (project.history.base if project.history else None)
    base_dir = rules.config.review_dir if rules is not None and rules.config is not None else None
    folder = review_folder_changes(project.root, base, project.config.review_dir,
                                   _dead_record_file(project, base), base_dir)
    review_only, problems = folder.review_only, list(folder.problems)
    records = [p for p in folder.added if project.config.is_record_file(p)]
    if records and folder.outside:
        # a change's own AI review is declared in its description, with its findings: a record file
        # next to the content would raise the change's lines without a review the check can see
        more = f" and {len(folder.outside) - 1} more" if len(folder.outside) > 1 else ""
        problems.append(f"the change adds the review record {records[0]} and also changes {folder.outside[0]}{more}: "
                        "a review record goes into a pull request of its own, which only adds files to the review "
                        f"folder ({project.config.review_dir}/). The AI review of this change is declared in its "
                        "description")
    if review_only:
        # a review: it only adds records to the review folder, so it has no lines to declare. What it
        # attests is in its attestation files, which lint checks with the others
        out["review"] = True
        if folder.added:
            out["notes"].append(f"this change only adds files to the review folder ({project.config.review_dir}/)"
                                + (" and deletes record files there that cover no line" if folder.deleted else "")
                                + ": it is a review, so its description needs no declaration; its record files "
                                "record what it reviewed")
        else:
            out["notes"].append(f"this change only deletes record files of the review folder "
                                f"({project.config.review_dir}/) that cover no line (aisignoff gc): it changes no "
                                "level, so its description needs no declaration")
    else:
        problems += [f"the pull request description: {p}" for p in args.pr_problems]
    if not review_only and not (project.history_used and project.config.history.merge_method == "rebase"):
        problems += [f"the pull request description: {p}"
                     for p in description_problems(args.pr_pieces, project.config.policy) if p not in problems]
        if getattr(args, "pr_today", True):
            problems += [f"the pull request description: {p}" for p in
                         review_problems(project.root, args.pr_pieces.get(2), args.pr_findings,
                                         change_files(project.root, base))]
    if rules is not None and rules.config is not None:
        what = (f"removes {FILENAME}" if project.config.path is None
                else f"alters {', '.join(rules.changed)} in {FILENAME}" if rules.changed else None)
        if rules.ignore_revs and project.config.path is not None:
            # its entries give lines back to the commits before them, as [history] steers resolution
            ignore = f"edits the entries of {rules.ignore_revs}"
            what = f"{what} and {ignore}" if what else ignore
        problems += rules.unconverted
        if what and getattr(args, "allow_policy_change", False):
            # allowed, but said out loud, and it doesn't lower the bar for this pull request itself
            out["notes"].append(f"the change {what} (allowed by --allow-policy-change); this pull request is "
                                f"still checked under the base branch's [policy] ({args.base}); the new rules apply once it has landed")
        elif what:
            problems.append(f"the change {what}, which only the branch it goes into "
                            f"{'can do' if project.config.path is None else 'sets'}: commit it there directly, "
                            "or let the check pass it with --allow-policy-change")
    out["problems"] = problems
    return out


def _dead_record_file(project: Project, base: str | None):
    """For the check before the merge: whether a record file of the review folder that the change
    deletes covers no line any more (as of the change), so that it may be deleted."""
    history = project.history
    if history is None or not base:
        return None
    from .config import parse_record_file

    def dead(path: str) -> bool:
        if not project.config.is_record_file(path):
            return False  # evidence in a subfolder, never read: add-only like every other file there
        text = _git_out(project.root, "show", f"{base}:./{path}", strip=False)
        if text is None:
            return False
        try:
            attestations = parse_record_file(text, path)
        except ConfigError:
            return False
        return history.is_dead(attestations, path)
    return dead


def dead_records(project: Project) -> tuple[list, list[str]]:
    """The entries of SIGNOFF.toml that cover no line any more, and the record files of the review
    folder all of whose entries cover none. Only after every file was resolved."""
    if project.history is None:
        return [], []
    dead = project.history.dead_records()
    ids = {id(e) for e in dead}
    own = [e for e in dead if e.filename == FILENAME]
    files: dict[str, bool] = {}
    for e in project.config.review_attestations:
        files[e.filename] = files.get(e.filename, True) and id(e) in ids
    return own, sorted(f for f, all_dead in files.items() if all_dead)


def _describe_entry(e) -> str:
    if not hasattr(e, "blob"):
        return f"[[commits]] entry {e.index} ({e.commit[:7]})"
    what = " ".join(x for x in (e.path, e.commit[:7] if e.commit else None) if x)
    return f"[[attestations]] entry {e.index} ({what})"


def _description_only(project: Project, args) -> int:
    """lint --declare-from in a repository without SIGNOFF.toml: only the description is checked."""
    if args.base:
        _load_base_rules(project, args)
    pr = _pull_request(project, args)
    for problem in pr["problems"]:
        print(f"✗ {printable(problem)}")
    for note in pr["notes"]:
        print(f"! {printable(note)}")
    print()
    if pr["problems"]:
        print(f"See {SPEC_URL}")
        return 1
    print(f"The pull request's declaration is complete (no {FILENAME}: files aren't checked). ✓")
    return 0


def cmd_lint(args) -> int:
    project = _open(args.root)
    if args.declare_from is not None and project.config.path is None:
        return _description_only(project, args)
    results = _history_results(project, args)
    if not results:
        print(f"✗ no files found below {project.root}")
        return 1
    pr = _pull_request(project, args)
    pr_problems, pr_notes = (pr["problems"], pr["notes"]) if pr else ([], [])
    files = [r.path for r in results]
    unused = project.unused_annotations(files)

    for problem in pr_problems:
        print(f"✗ {printable(problem)}")
    for problem in project.history_problems:
        print(f"✗ {printable(problem)}")
    _print_errors(results, args.max_files)
    for index in unused:
        print(f"{'✗' if args.strict else '!'} {project.config.path.name} annotation [{index}] matches no file")
    for warning in project.config.warnings + project.history_warnings:
        print(f"{'✗' if args.strict else '!'} {printable(warning)}")

    for note in project.config.notes + project.history_notes + pr_notes:
        print(f"! {printable(note)}")
    waiting = _waiting(results)
    if waiting:
        print(f"! {waiting}")
    own, files = dead_records(project)
    if own or files:
        listed = [f"{FILENAME} {_describe_entry(e)}" for e in own] + files
        more = f" and {len(listed) - 3} more" if len(listed) > 3 else ""
        print(f"! {len(listed)} record(s) cover no line any more: {', '.join(listed[:3])}{more}. They change no "
              "level; 'aisignoff gc' deletes them (git history keeps them)")

    bad = sum(1 for r in results if r.errors)
    print()
    print(f"{len(results) - bad} of {len(results)} files have a valid declaration.")
    if project.history_used:
        lines = sum(p.lines for r in results for p in r.parts or ())
        bad_lines = sum(p.lines for r in results for p in r.parts or () if p.errors and not p.advisory)
        print(f"{lines - bad_lines} of {lines} lines have a valid declaration (line by line, from git history).")
    failed = bad > 0 or bool(project.history_problems) or bool(pr_problems) or (args.strict and (unused or project.history_warnings
                                                                                    or project.config.warnings))
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
                    sha, changes = visualize.changed_since(
                        project.root, args.since, [r.path for r in results],
                        project.history_used and project.config.history.ignore_whitespace)
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
        out = {**_json_header(), "files": [_result_json(r) for r in results]}
        pr = _pull_request(project, args)
        if pr is not None:
            # the levels for labels and the like: what the description declares, and whether it applies
            out["pull_request"] = {"applies": pr["applies"], **pr["declaration"].as_dict(),
                                   "AI-Review-Findings": getattr(args, "pr_findings", None), "errors": pr["problems"]}
        print(json.dumps(out, indent=2, ensure_ascii=False))
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
    counts = Counter()
    for r in results:
        for d, errors, w in weighted_parts(project.root, r, weight):
            counts[counted_findings(d, errors)] += w
    print("Findings (of the last independent AI review)")
    for level, name in list(FINDINGS_LEVELS.items()) + [(UNREVIEWED, "No independent AI review since last change")]:
        if counts[level]:
            print(f"  {level:<10} {name:<46} {counts[level]:>5g}  {100 * counts[level] / total:5.1f}%")
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
    # Findings: the findings level (F0-F3, F- for no independent AI review), from AI-Review-Findings
    out = {"path": r.path, **r.declaration.as_dict(), FINDINGS_AXIS: counted_findings(r.declaration, r.errors),
           "errors": r.errors}
    if r.parts is not None:
        # kinds: where each axis comes from (commit, branch, attestation, file, declared; null: nowhere)
        out["parts"] = [{"lines": p.lines, "runs": p.runs, **p.declaration.as_dict(),
                         FINDINGS_AXIS: counted_findings(p.declaration, p.errors), "errors": p.errors,
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
        target = config_path(root)
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


def _shown(root: Path, target: Path) -> str:
    try:
        return target.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(target)


def _review_target(project: Project, name: str) -> Path:
    """The attestation file --to names: a new .toml file in the review folder."""
    folder = project.config.review_dir
    if not folder:
        raise UsageError('--to needs a review folder ([review] dir is "")')
    target = Path(name)
    if not target.is_absolute():
        target = Path.cwd() / target
    target = target.resolve()
    try:
        rel = target.relative_to(project.root).as_posix()
    except ValueError:
        raise UsageError(f"{name} is outside the project root {project.root}")
    if not project.config.is_record_file(rel):
        raise UsageError(f"--to names a .toml file directly in the review folder ({folder}/), such as "
                         f"{folder}/pull12.toml (files in its subfolders aren't read as records)")
    if target.exists():
        raise UsageError(f"{rel} exists: the review folder keeps every review as it was recorded, so write a new file")
    return target


def _new_record_name(project: Project, what: str) -> Path:
    """A new record file in the review folder: <date>-<what>.toml, numbered if that exists."""
    import datetime
    import re
    stem = f"{datetime.date.today().isoformat()}-{re.sub(r'[^A-Za-z0-9._-]+', '-', what)[:40].strip('-') or 'record'}"
    folder = project.root / project.config.review_dir
    target, n = folder / f"{stem}.toml", 1
    while target.exists():
        n += 1
        target = folder / f"{stem}-{n}.toml"
    return target


def _write_review(root: Path, target: Path, block: list[str]) -> Path:
    """Write a new record file; remove it again if the result isn't a valid one."""
    target.parent.mkdir(parents=True, exist_ok=True)
    head = ["# An independent AI review, recorded by 'aisignoff attest'. The review folder keeps it as it is:",
                    "# a later review goes into a new file."]
    target.write_text("\n".join(head + block) + "\n", encoding="utf-8")
    try:
        load(root)
    except ConfigError as e:
        target.unlink()
        raise UsageError(f"{e}; nothing was written")
    return target


def cmd_annotate(args) -> int:
    root = Path(args.root)
    if not root.is_dir():
        raise UsageError(f"project root {root} is not a directory")
    values = _values(args)
    _check_complete(values, _policy(root))

    patterns = [_pattern(root, a) for a in args.paths]
    target = _append_annotation(root, patterns, values, args.precedence)
    print(f"Added an annotation for {', '.join(patterns)} to {target}")
    return 0


# ---------------------------------------------------------------- attest
def _git_out(root: Path, *args: str, strip: bool = True) -> str | None:
    import subprocess
    from .history import GIT, git_env
    try:
        r = subprocess.run([*GIT, "-C", str(root), *args], env=git_env(), capture_output=True, text=True)
    except FileNotFoundError:
        raise UsageError("git is not installed")
    if r.returncode != 0:
        return None
    return r.stdout.strip() if strip else r.stdout


def cmd_attest(args) -> int:
    project = _open(args.root)
    _refuse_version_3(project.config)
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
    if values.get(AIR) in FINDINGS_REVIEWS and FINDINGS not in values:
        raise UsageError(f"an AI review of {values[AIR]} records what it found: give --findings ({NO_FINDINGS}, "
                         f"{', '.join(SEVERITIES)}); it sets the findings level of the attested lines")
    problems = [e for e in validate(Declaration.from_mapping(values, "command line"))
                if not any(e == f"missing {k}" for k in (GEN, HUM, AIR))]
    if problems:
        raise UsageError("incomplete declaration: " + "; ".join(problems))

    if args.at and args.commit:
        raise UsageError("give --at (whole files, as of a commit) or --commit (the lines a commit landed), not both")
    if not args.paths and not args.commit:
        raise UsageError("give the files to attest, or --commit")
    target_file = None
    if args.signoff and args.to:
        raise UsageError(f"give --to (a record file of the review folder) or --signoff ({FILENAME}), not both")
    if HUM not in values and not args.to and not args.signoff:
        # an AI review goes into a new file in the review folder, never SIGNOFF.toml
        if not project.config.review_dir:
            raise UsageError('an AI review is recorded in the review folder, and [review] dir is "": record it in '
                             'a pull request description instead, or set a review folder')
        what = (_git_out(root, "rev-parse", "--short=7", "--verify", "--quiet", f"{args.commit}^{{commit}}") or args.commit
                if args.commit else Path(args.paths[0]).stem if args.paths else "review")
        args.to = str(_new_record_name(project, what))
    if args.to:
        target_file = _review_target(project, args.to)
        if HUM in values:
            raise UsageError(f"an attestation file in the review folder records an AI review: a person's review "
                             f"(-H) goes into {FILENAME}, without --to")
        if values.get(AIR) not in FINDINGS_REVIEWS:
            raise UsageError("an attestation file in the review folder records an independent AI review: give -a "
                             "A1, A2 or A3")
    sha = None
    if args.commit:
        sha = _git_out(root, "rev-parse", "--verify", "--quiet", f"{args.commit}^{{commit}}")
        if not sha:
            raise UsageError(f"{args.commit} is not a commit")
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
    if sha:
        for rel in chosen or [None]:
            block += ["", "[[attestations]]", f'commit = "{sha}"']
            block += [f"path = {_toml_str(rel)}"] if rel else []
            block += [f"{k} = {_toml_value(v)}" for k, v in values.items()]
        target = _write_review(root, target_file, block) if target_file else _append_toml(root, block)
        what = " ".join(values[k] for k in given)
        scope = f"{len(chosen)} file(s)" if chosen else "all its files"
        print(f"Attested the lines of {sha[:7]} in {scope} at {what} in {_shown(root, target)}")
        if not project.config.history.enabled:
            print("note: attestations count only with [history] enabled in SIGNOFF.toml")
        return 0
    for rel in chosen:
        if args.at:
            blob = _git_out(root, "rev-parse", "--verify", "--quiet", f"{args.at}:./{rel}")  # relative to root
            if not blob:
                raise UsageError(f"{rel} does not exist at {args.at} (for a file renamed since, write the entry "
                                 "by hand with the blob of its old path)")
        else:
            from .history import hash_file
            blob = hash_file(root, rel)  # a symlink: its target text, as git stores it
        if not blob:
            raise UsageError(f"cannot hash {rel}")
        block += ["", "[[attestations]]", f"path = {_toml_str(rel)}", f'blob = "{blob}"']
        block += [f"{k} = {_toml_value(v)}" for k, v in values.items()]
    target = _write_review(root, target_file, block) if target_file else _append_toml(root, block)
    what = " ".join(values[k] for k in given)
    print(f"Attested {len(chosen)} file(s) at {what}" + (f" as of {args.at}" if args.at else "")
          + f" in {_shown(root, target)}")
    if not project.config.history.enabled:
        print("note: attestations count only with [history] enabled in SIGNOFF.toml")
    return 0


# ---------------------------------------------------------------- correct
def cmd_correct(args) -> int:
    """A [[commits]] entry in SIGNOFF.toml: a person's correction of a commit's declaration."""
    project = _open(args.root)
    _refuse_version_3(project.config)
    root = project.root
    sha = _git_out(root, "rev-parse", "--verify", "--quiet", f"{args.commit}^{{commit}}")
    if not sha:
        raise UsageError(f"{args.commit} is not a commit")
    values = _values(args)
    if not any(k in values for k in (GEN, HUM, AIR)):
        raise UsageError("give at least one level to correct (-g, -H or -a)")
    if any(v == TODO or (isinstance(v, list) and TODO in v) for v in values.values()):
        raise UsageError("a correction records what is known: TODO isn't allowed")
    for level, names in ((GEN, ASSISTED), (HUM, REVIEWED), (AIR, AI_REVIEWED)):
        if names in values and level not in values:
            raise UsageError(f"{names} without {level}")
    block = ["", "[[commits]]", f'commit = "{sha}"'] + [f"{k} = {_toml_value(v)}" for k, v in values.items()]
    target = _append_toml(root, block)
    print(f"Corrected {sha[:7]} ({' '.join(values[k] for k in (GEN, HUM, AIR) if k in values)}) in "
          f"{_shown(root, target)}")
    return 0


# ---------------------------------------------------------------- gc
def remove_tables(text: str, kind: str, indices: set[int], count: int | None = None) -> str:
    """SIGNOFF.toml without the [[kind]] tables of these 1-based positions. A table runs from its
    header to the next header; comment lines right above the next header stay with that one. The
    header's key may be bare, "quoted" or 'quoted', as TOML allows. With COUNT (the number of
    [[kind]] entries TOML reads), a file whose headers don't match it (entries written another way,
    such as an inline array) raises ConfigError: its entries can't be told apart by line."""
    import re
    from .history import History
    lines = text.splitlines(keepends=True)
    header = re.compile(r"^\s*\[")
    own = re.compile(History._HEADER.format(name=re.escape(kind)))
    starts = [i for i, line in enumerate(lines) if header.match(line)]
    if count is not None and sum(1 for i in starts if own.match(lines[i].rstrip("\r\n"))) != count:
        raise ConfigError(f"the [[{kind}]] entries of {FILENAME} aren't all written as [[{kind}]] tables, "
                          "so gc can't tell which lines to delete; delete them by hand")
    drop: set[int] = set()
    n = 0
    for k, start in enumerate(starts):
        if not own.match(lines[start].rstrip("\r\n")):
            continue
        n += 1
        if n not in indices:
            continue
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        while end - 1 > start and lines[end - 1].lstrip().startswith("#"):
            end -= 1
        drop.update(range(start, end))
    kept = [line for i, line in enumerate(lines) if i not in drop]
    out: list[str] = []
    for line in kept:  # no runs of blank lines where tables were
        if line.strip() or not out or out[-1].strip():
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "".join(out).rstrip("\n") + "\n"


def _entry_identity(e) -> tuple:
    """What an attestation or [[commits]] entry is: what it covers and what it says."""
    return (getattr(e, "path", None), getattr(e, "blob", None), e.commit, e.values)


def cmd_gc(args) -> int:
    project = _open(args.root)
    if not project.config.history.enabled:
        raise UsageError("gc needs [history]: without it, every entry counts as written")
    try:
        project.results()
    except ProjectError as e:
        raise UsageError(str(e))
    if not project.history_used:
        raise UsageError("gc needs the whole git history (a shallow clone?)")
    if project.history_problems:
        for p in project.history_problems:
            print(f"✗ {printable(p)}")
        raise UsageError("fix the problems lint reports first")
    own, files = dead_records(project)
    if not own and not files:
        print("Every record covers a line. Nothing to delete.")
        return 0
    text = None
    if own:  # the file without them, checked before anything is shown or written
        path = project.config.path
        before = project.config
        try:
            text = path.read_text(encoding="utf-8")
            for kind, cls, entries in (("attestations", True, before.attestations), ("commits", False, before.commits)):
                gone = {e.index for e in own if hasattr(e, "blob") == cls}
                if gone:
                    text = remove_tables(text, kind, gone, count=len(entries))
            # exactly those entries are gone, the rest as they were: what each covers (path, blob,
            # commit) and what it says, so that deleting the wrong one of two equal reviews fails
            new = load_text(text, path)
            want_a = [_entry_identity(a) for a in before.attestations if not any(a is e for e in own)]
            want_c = [_entry_identity(c) for c in before.commits if not any(c is e for e in own)]
            if [_entry_identity(a) for a in new.attestations] != want_a \
                    or [_entry_identity(c) for c in new.commits] != want_c \
                    or [(a.paths, a.precedence, a.values) for a in new.annotations] \
                    != [(a.paths, a.precedence, a.values) for a in before.annotations]:
                raise ConfigError("the entries left over aren't the ones expected")
        except ConfigError as e:
            raise UsageError(f"{e}; {FILENAME} was left unchanged")
    for e in own:
        print(f"{'would delete' if args.dry_run else 'deleted'} {FILENAME} {_describe_entry(e)}")
    for f in files:
        print(f"{'would delete' if args.dry_run else 'deleted'} {f}")
    if args.dry_run:
        return 0
    if text is not None:
        project.config.path.write_text(text, encoding="utf-8")
    for f in files:
        (project.root / f).unlink()
    print(f"Deleted {len(own)} entr{'y' if len(own) == 1 else 'ies'} of {FILENAME} and {len(files)} record file(s). "
          "Their levels are unchanged; git history keeps them.")
    return 0


# ---------------------------------------------------------------- diff
def cmd_diff(args) -> int:
    from . import diff
    if args.json and args.markdown:
        raise UsageError("give --json or --markdown, not both")
    if args.depth < 0:
        raise UsageError("--depth must be 0 or more")
    project = _open(args.root)
    declared = _declared(args, project.config.version_3)
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
                                               ensure_ascii=False), encoding="utf-8")
        written.append(str(out / filename))
    counts = Counter()
    for r in results:
        for d, errors, w in weighted_parts(project.root, r, args.weight):
            counts[counted_findings(d, errors)] += w
    badge = badge_json("AI review findings" + suffix, counts, [*FINDINGS_LEVELS, UNREVIEWED], "2DA44E")
    if badge["message"] != "no files":
        # the flags: an open critical or major finding
        badge["color"] = "red" if counts["F3"] else "orange" if counts["F2"] else "2DA44E"
    (out / FINDINGS_BADGE).write_text(json.dumps(badge, ensure_ascii=False), encoding="utf-8")
    written.append(str(out / FINDINGS_BADGE))
    print("Wrote " + ", ".join(written))
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
    p.add_argument("--findings", choices=[NO_FINDINGS, *SEVERITIES], help=f"with -a A1, A2 or A3: the highest severity "
                   f"the review found ({FINDINGS}), which reports show as the findings level")


def _add_history_options(p) -> None:
    _add_declare_from(p)
    p.add_argument("--base", metavar="REV", help="with --declare-from: the branch the pull request goes into "
                   "(a pull request into another branch than the default one declares nothing)")
    _add_landed(p)
    p.set_defaults(generation=None, human=None, ai=None, assisted_by=None, reviewed_by=None, ai_reviewed_by=None,
                   findings=None)


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
    p.add_argument("--history", action="store_true", help="turn on [history]: line-level declarations from git history")
    p.add_argument("--no-agents-md", action="store_true", help="don't add the section that points AI agents to "
                   "'aisignoff guide' to AGENTS.md (and to CLAUDE.md, if it exists)")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("lint", help="check that every file has a valid declaration")
    p.add_argument("--strict", action="store_true", help="also fail on warnings: annotations that match no file, "
                   "reverts and merges that own lines without declaring them")
    p.add_argument("--max-files", type=int, default=10, help="files listed per problem (default 10)")
    _add_history_options(p)
    p.add_argument("--allow-policy-change", action="store_true", help="with --base: let the change alter [policy], "
                   "exclude or [history] of SIGNOFF.toml (for example for maintainers); the change itself is "
                   "still checked under the base branch's [policy]")
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

    p = sub.add_parser("annotate", help=f"declare files in {FILENAME}")
    p.add_argument("paths", nargs="+", help="files, directories or glob patterns (quote globs)")
    _add_values(p, required=True)
    p.add_argument("--precedence", choices=["closest", "override"])
    p.set_defaults(func=cmd_annotate)

    p = sub.add_parser("attest", help="re-declare whole files as checked now, or the lines of a commit ([history])")
    p.add_argument("paths", nargs="*", help="files or directories (with --commit: optional, default all its files)")
    _add_values(p, required=False)
    p.add_argument("--at", metavar="REV", help="attest the files as they were at this commit instead")
    p.add_argument("--commit", metavar="REV", help="attest only the lines this commit of the default branch landed "
                   "(a pull request's merge or squash commit), not the whole files")
    p.add_argument("--to", metavar="FILE", help="for an AI review (-a only): the new record file in the review folder, "
                   "such as reviews/pull12.toml (default: <date>-<commit or file>.toml); a person's review (-H) goes "
                   "into SIGNOFF.toml")
    p.add_argument("--signoff", action="store_true", help="write an AI review into SIGNOFF.toml, the file a person "
                   "signs off, instead of the review folder (for a person who records it)")
    p.set_defaults(func=cmd_attest)

    p = sub.add_parser("correct", help=f"correct the declaration of a commit: a [[commits]] entry in {FILENAME} ([history])")
    p.add_argument("commit", metavar="REV", help="the commit that landed the lines (a pull request's merge or squash "
                   "commit), or for -g only a commit inside it")
    _add_values(p, required=False)
    p.set_defaults(func=cmd_correct)

    p = sub.add_parser("gc", help="delete the records that cover no line any more ([history])")
    p.add_argument("--dry-run", action="store_true", help="only list them")
    p.set_defaults(func=cmd_gc)

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


    p = sub.add_parser("badge", help="write shields.io endpoint JSON files")
    p.add_argument("--out", default="badges", help="output directory (default: badges)")
    p.add_argument("--weight", choices=["files", "lines"], default="files")
    _add_landed(p)
    p.set_defaults(func=cmd_badge)

    p = sub.add_parser("guide", help="what an AI agent needs to know: the developer's or the reviewer's brief")
    p.add_argument("--role", choices=guide.ROLES, help="dev: the agent that writes the change and declares it; "
                   "review: the independent AI reviewer")
    p.add_argument("--agents-md", action="store_true", help="add the section that points AI agents to this "
                   "command to AGENTS.md (created if missing) and to CLAUDE.md (if it exists), or update it")
    p.add_argument("--skills", nargs="?", const=True, metavar="DIR", help="write both guides as "
                   "Claude skills, aisignoff-dev and aisignoff-review (default DIR: .claude/skills)")
    p.set_defaults(func=cmd_guide)

    args = parser.parse_args(argv)
    from .diff import DiffError
    from .history import HistoryError
    try:
        return args.func(args)
    except (UsageError, ConfigError, ProjectError, HistoryError, DiffError, guide.GuideError) as e:
        print(f"aisignoff {args.command}: {e}", file=sys.stderr)
        return EXIT_USAGE
    except BrokenPipeError:
        # the reader stopped (report --json | head): not an error, and nothing more to say
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except (OSError, ValueError):
            pass
        return 0
    except OSError as e:
        # a file that can't be read or written: the environment, not the declarations
        where = f"{e.filename}: " if e.filename else ""
        print(f"aisignoff {args.command}: {where}{e.strerror or e}", file=sys.stderr)
        return EXIT_USAGE
    except Exception:
        # a bug in aisignoff: never exit 1, which says that the declarations failed the check
        traceback.print_exc()
        print(f"aisignoff {args.command}: internal error in aisignoff {__version__}, a bug: please report it with "
              f"the traceback above at {ISSUES_URL}", file=sys.stderr)
        return EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
