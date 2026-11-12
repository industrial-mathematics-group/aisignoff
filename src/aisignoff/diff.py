"""'aisignoff diff BASE': the declarations of the lines a change adds and removes.

Like a coverage diff: the levels of the added lines (at HEAD, or the working tree), of the
removed lines (at BASE), the attestations the change adds, and how the shares of the whole
repository move. The state at BASE is read from a temporary git worktree, so it uses BASE's
own SIGNOFF.toml (and its history), exactly as 'aisignoff report' did there.
"""
from __future__ import annotations

import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from .model import AI, AIR, GEN, GENERATION, HUM, HUMAN, UNDECLARED, Declaration, counted_level, printable, validate
from .history import GIT, git_env
from .project import FileResult, Project, line_count

AXES = ((GEN, "Generation", GENERATION), (HUM, "Human review", HUMAN), (AIR, "AI review", AI))


class DiffError(Exception):
    pass


def _git(root: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run([*GIT, "-C", str(root), *args], env=git_env(), capture_output=True)
    if r.returncode != 0 and check:
        raise DiffError(f"git {args[0]} failed: {r.stderr.decode('utf-8', 'replace').strip()}")
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else ""


_ESCAPES = {ord("a"): 7, ord("b"): 8, ord("t"): 9, ord("n"): 10, ord("v"): 11, ord("f"): 12, ord("r"): 13,
            ord('"'): 34, ord("\\"): 92}


def _unquote(path: str) -> str:
    """Undo git's C-style quoting of unusual paths ("a\\tb", "\\303\\274"), on the bytes."""
    if not (len(path) >= 2 and path.startswith('"') and path.endswith('"')):
        return path
    raw = path[1:-1].encode("utf-8", "surrogateescape")
    out = bytearray()
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == 92 and i + 1 < len(raw):  # backslash
            nxt = raw[i + 1]
            if 48 <= nxt <= 55 and i + 4 <= len(raw) and all(48 <= x <= 55 for x in raw[i + 1:i + 4]):
                out.append(int(raw[i + 1:i + 4], 8) & 0xFF)
                i += 4
                continue
            out.append(_ESCAPES.get(nxt, nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return out.decode("utf-8", "surrogateescape")


def _quoted_end(text: str) -> int:
    """Index just past the quoted string that text starts with."""
    i = 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return i + 1
        i += 1
    return len(text)


def _git_header_paths(rest: str) -> tuple[str | None, str | None]:
    """The two paths of a 'diff --git a/X b/Y' line (rest: after 'diff --git ').

    Unquoted paths may contain spaces; without a rename both sides are equal, which makes
    the split unambiguous. Renames are taken from the 'rename from/to' lines instead."""
    if rest.startswith('"'):
        end = _quoted_end(rest)
        a, b = _unquote(rest[:end]), rest[end + 1:]
    elif rest.endswith('"'):
        start = rest.rfind(' "')
        a, b = rest[:start], rest[start + 1:]
    else:
        half = (len(rest) - 1) // 2
        a, b = rest[:half], rest[half + 1:]
    b = _unquote(b)
    return (a[2:] if a.startswith("a/") else None), (b[2:] if b.startswith("b/") else None)


def _header_path(text: str) -> str | None:
    """The path of a '--- a/X' or '+++ b/X' header (None: /dev/null). git appends a TAB to
    names that contain a space."""
    if text.endswith("\t"):
        text = text[:-1]
    p = _unquote(text)
    return None if p == "/dev/null" else p[2:]


def changed_lines(root: Path, base: str, ignore_whitespace: bool = False) -> dict[tuple[str | None, str | None], tuple[list[int], list[int]]]:
    """(old path, new path) -> (removed line numbers at BASE, added line numbers now).

    Compares BASE with the working tree (tracked files, renames detected); untracked files
    are added by the caller. Paths are relative to root, and only files below root count.

    With ignore_whitespace, lines that differ only in whitespace are no change (git diff -w), as
    for git blame -w.

    The file names come from the header of each file's block (from 'diff --git' to its first
    hunk) only: a removed line "-- comment" reads "--- comment" in the hunk, like a header."""
    out = _git(root, "-c", "core.quotePath=false", "diff", "-M", "--relative", "--unified=0", "--no-color",
               "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/", *(["-w"] if ignore_whitespace else []), base, "--")
    result: dict = {}
    old = new = None
    removed: list[int] = []
    added: list[int] = []
    in_header = False

    def flush():
        if old is not None or new is not None:
            result[(old, new)] = (removed, added)

    for line in out.split("\n"):
        if line.startswith("diff --git "):
            flush()
            old, new = _git_header_paths(line[len("diff --git "):])
            removed, added = [], []
            in_header = True
        elif line.startswith("@@ "):
            in_header = False
            a, b = line.split(" ")[1:3]
            start, _, count = a[1:].partition(",")
            removed += range(int(start), int(start) + int(count or 1))
            start, _, count = b[1:].partition(",")
            added += range(int(start), int(start) + int(count or 1))
        elif not in_header:
            continue  # a line of a hunk
        elif line.startswith("new file mode"):
            old = None
        elif line.startswith("deleted file mode"):
            new = None
        elif line.startswith("--- "):
            old = _header_path(line[4:])
        elif line.startswith("+++ "):
            new = _header_path(line[4:])
        elif line.startswith("rename from "):
            old = _unquote(line[len("rename from "):])
        elif line.startswith("rename to "):
            new = _unquote(line[len("rename to "):])
        elif line.startswith("Binary files ") and line.endswith(" differ"):
            # a binary file counts as one line, as everywhere else
            removed, added = ([1] if old else []), ([1] if new else [])
    flush()
    return result


def merge_base(root: Path, base: str) -> str:
    """The commit a change since BASE starts from: the merge base of BASE and HEAD, so the
    commits BASE got since don't count as the change's (as a pull request's diff on GitHub)."""
    sha = _git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}", check=False).strip()
    if not sha:
        raise DiffError(f"{base} is not a commit")
    if not _git(root, "rev-parse", "--verify", "--quiet", "HEAD", check=False).strip():
        return sha
    common = _git(root, "merge-base", "HEAD", sha, check=False).strip()
    if not common:
        raise DiffError(f"{base} and HEAD have no common history")
    return common


def _line_declarations(r: FileResult, lines: list[int]):
    """(declaration, errors, kinds) of the given lines of a file."""
    if r.line_parts is None:
        return [(r.declaration, r.errors, None)] * len(lines)
    out = []
    for n in lines:
        i = r.line_parts[n - 1] if 0 < n <= len(r.line_parts) else 0
        p = r.parts[i]
        out.append((p.declaration, p.errors, p.kinds))
    return out


def _with_declared(d: Declaration, kinds, declared: Declaration | None, policy, history: bool):
    """File-level mode: a change declared with --declare takes those levels for its added lines.
    (In history mode, History applies it line by line; files with precedence = "override" stay
    at their file-level declaration.)"""
    if declared is None or kinds is not None or history:
        return None
    values = d.as_dict()
    for key, names in ((GEN, "Assisted-by"), (HUM, "Reviewed-by"), (AIR, "AI-Reviewed-by")):
        if declared.get(key) is not None:
            values[key], values[names] = declared.get(key), list(declared.get(names))
    merged = Declaration.from_mapping(values, "declared for this change")
    return merged, validate(merged, policy)


def _shares(root: Path, results) -> dict:
    """Per axis: level -> share of all lines (0-100)."""
    from .project import weighted_parts
    out = {}
    for key, _, _ in AXES:
        counts = Counter()
        for r in results:
            for d, errors, w in weighted_parts(root, r, "lines"):
                counts[counted_level(d, errors, key)] += w
        total = sum(counts.values()) or 1
        out[key] = {lv: 100 * c / total for lv, c in counts.items()}
    return out


def _bucket(path: str, depth: int) -> str:
    parts = path.split("/")[:-1]
    return "/".join(parts[:depth]) + "/" if parts and depth else "."


def compute(project: Project, base: str, declared=None, depth: int = 1, by_file: bool = False) -> dict:
    """declared: the declaration of the change (a Declaration, or one history.Piece per axis as
    read from a pull request description), None if there is none."""
    root = project.root
    tip = _git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}", check=False).strip()
    sha = merge_base(root, base)
    head = {r.path: r for r in project.results(declared=declared, base=sha)}
    if declared is not None and not isinstance(declared, Declaration):
        from .history import combine
        declared = combine([declared.get(i) for i in range(len(AXES))])
    prefix = _git(root, "rev-parse", "--show-prefix", check=False).strip()  # root below the top of the repo
    with tempfile.TemporaryDirectory(prefix="aisignoff-base-") as tmp:
        top = Path(tmp) / "base"
        where = top / prefix if prefix else top
        # no post-checkout hooks: reading BASE must not run the repository's code
        _git(root, "-c", "core.hooksPath=/dev/null", "worktree", "add", "--detach", "--quiet", str(top), sha)
        try:
            base_project = Project(where)
            base_project.check_snapshot = False
            # as the base's own report: by its SIGNOFF.toml, with its commit as the default branch's
            base_results = base_project.results(quiet=True)
            base_attestations = {(a.path, a.blob) for a in base_project.config.attestations}
            before = _shares(where, base_results)  # reads the files at BASE, so before the worktree goes
        except Exception as e:  # BASE may predate SIGNOFF.toml, or use an old format
            base_results, base_attestations, before = [], set(), {}
            note = f"the declarations at {base} could not be read ({e}); removed lines count as undeclared"
        else:
            note = None
        finally:
            _git(root, "worktree", "remove", "--force", str(top), check=False)
    base_map = {r.path: r for r in base_results}

    changes = changed_lines(root, sha)
    seen_new = {new for _, new in changes if new}
    tracked = set(_git(root, "ls-files", "-z").split("\0"))
    for path in head:
        if path not in seen_new and path not in tracked:  # untracked new file
            n = len(head[path].line_parts) if head[path].line_parts is not None else line_count(root, path)
            changes[(None, path)] = ([], list(range(1, n + 1)))

    rows: dict[str, dict] = {}
    total = _empty_row(".")
    files = 0
    for (old, new), (removed, added) in sorted(changes.items(), key=lambda kv: kv[0][1] or kv[0][0] or ""):
        r_new = head.get(new) if new else None
        r_old = base_map.get(old) if old else None
        if r_new is None and r_old is None:
            continue  # excluded or ignored on both sides
        files += 1
        name = new or old
        row = rows.setdefault(name if by_file else _bucket(name, depth), _empty_row(name if by_file else _bucket(name, depth)))
        if r_new is not None:
            for d, errors, kinds in _line_declarations(r_new, added):
                replaced = _with_declared(d, kinds, declared, project.config.policy, project.history_used)
                if replaced:
                    d, errors = replaced
                for target in (row, total):
                    target["added"] += 1
                    for key, _, _ in AXES:
                        target["levels_added"][key][counted_level(d, errors, key)] += 1
        if r_old is not None:
            for d, errors, _ in _line_declarations(r_old, removed):
                for target in (row, total):
                    target["removed"] += 1
                    for key, _, _ in AXES:
                        target["levels_removed"][key][counted_level(d, errors, key)] += 1
        elif old is not None:
            for target in (row, total):
                target["removed"] += len(removed)

    attested = [{"path": a.path, "blob": a.blob, "levels": {k: v for k, v in a.values.items() if k in (GEN, HUM, AIR)}}
                for a in project.config.attestations if (a.path, a.blob) not in base_attestations]
    return {
        "base": sha, "base_name": base, "base_tip": tip, "files": files, "history": project.history_used, "note": note,
        "rows": [_finish(r) for r in sorted(rows.values(), key=lambda r: (r["name"] != ".", r["name"]))], "total": _finish(total), "attested": attested,
        "before": before, "after": _shares(root, list(head.values())),
        "problems": list(project.history_problems), "notes": list(project.history_notes),
    }


def _empty_row(name: str) -> dict:
    return {"name": name, "added": 0, "removed": 0,
            "levels_added": {key: Counter() for key, _, _ in AXES},
            "levels_removed": {key: Counter() for key, _, _ in AXES}}


def _order(key: str, counts: Counter) -> dict:
    levels = dict((k, lv) for k, _, lv in AXES)[key]
    return {lv: counts[lv] for lv in [*levels, UNDECLARED] if counts.get(lv)}


def _finish(row: dict) -> dict:
    return dict(row, levels_added={k: _order(k, c) for k, c in row["levels_added"].items()},
                levels_removed={k: _order(k, c) for k, c in row["levels_removed"].items()})


# ------------------------------------------------------------------ rendering
def _counts(c: dict) -> str:
    return " · ".join(f"{lv} +{n}" for lv, n in c.items()) or "-"


def _moves(data: dict, threshold: float = 0.05) -> list[str]:
    out = []
    for key, title, levels in AXES:
        before, after = data["before"].get(key, {}), data["after"].get(key, {})
        parts = []
        for lv in [*levels, UNDECLARED]:
            b, a = before.get(lv, 0.0), after.get(lv, 0.0)
            if abs(a - b) >= threshold:
                parts.append(f"{lv} {b:.1f}% → {a:.1f}% ({a - b:+.1f})")
        if parts:
            out.append((title, " · ".join(parts)))
    return out


def _base_text(data: dict) -> str:
    merged = "" if data["base"] == data.get("base_tip", data["base"]) else ", merge base"
    return f"{data['base_name']} ({data['base'][:7]}{merged})"


def render_text(data: dict) -> str:
    t = data["total"]
    head = f"Changes since {_base_text(data)}: +{t['added']} −{t['removed']} lines in {data['files']} file(s)"
    table = [["", "+lines", "-lines", *(f"{title} (added)" for _, title, _ in AXES)]]
    for r in data["rows"]:
        table.append([printable(r["name"]), f"+{r['added']}", f"-{r['removed']}", *(_counts(r["levels_added"][k]) for k, _, _ in AXES)])
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
    lines = [head, ""]
    for row in table:
        cells = [row[0].ljust(widths[0]), row[1].rjust(widths[1]), row[2].rjust(widths[2])] + \
                [c.ljust(w) for c, w in zip(row[3:], widths[3:])]
        lines.append("  ".join(cells).rstrip())
    lines += _extras(data, md=False)
    return "\n".join(lines)


def _md(text: str) -> str:
    return printable(text).replace("\\", "\\\\").replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def render_markdown(data: dict) -> str:
    t = data["total"]
    out = [f"**+{t['added']} −{t['removed']} lines** in {data['files']} file(s) since `{_md(data['base_name'])}` "
           f"(`{data['base'][:7]}`" + ("" if data["base"] == data.get("base_tip", data["base"]) else ", merge base")
           + ")", "",
           "| Changed | +lines | −lines | " + " | ".join(f"{title} (added)" for _, title, _ in AXES) + " |",
           "| --- | ---: | ---: |" + " --- |" * len(AXES)]
    for r in data["rows"]:
        out.append(f"| `{_md(r['name'])}` | +{r['added']} | −{r['removed']} | "
                   + " | ".join(_counts(r["levels_added"][k]) for k, _, _ in AXES) + " |")
    out += _extras(data, md=True)
    return "\n".join(out)


def _extras(data: dict, md: bool) -> list[str]:
    out = []
    if data["attested"]:
        out.append("")
        out.append("**Attested:**" if md else "Attested:")
        for a in data["attested"]:
            levels = " ".join(a["levels"].values())
            out.append(f"- `{_md(a['path'])}` at {levels}" if md else f"  {printable(a['path'])}  {levels}")
    moves = _moves(data)
    if moves:
        out.append("")
        out.append("**Whole repository, by lines:**" if md else "Whole repository, by lines:")
        for title, text in moves:
            out.append(f"- {title}: {text}" if md else f"  {title}: {text}")
    notes = []
    if not data["history"]:
        notes.append("file-level declarations: [history] is not enabled, or not usable here")
    if data["note"]:
        notes.append(data["note"])
    notes += data.get("notes", [])
    notes += [f"✗ {p}" for p in data["problems"]]
    if notes:
        out.append("")
        out += [f"- {_md(n)}" if md else f"note: {printable(n)}" for n in notes]
    return out
