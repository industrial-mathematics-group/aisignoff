"""Folder view of the declarations: a tree of folders with the level mix of each axis.

The same tree feeds 'aisignoff report --tree' (text), '--tree --markdown' (job summaries),
'--tree --json' (other tools) and '--html' (an interactive, self-contained page).
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
from collections import Counter
from importlib import resources
from pathlib import Path

from . import __version__
from .model import AI, AIR, GEN, GENERATION, HUM, HUMAN
from .project import line_count, weighted_parts

AXES = ((GEN, "Generation", GENERATION), (HUM, "Human review", HUMAN), (AIR, "AI review", AI))
UNDECLARED = "undeclared"
WEIGHTS = ("files", "lines")




def status_level(result, key: str) -> str:
    """Level for counting: the declared level if the declaration is valid, else 'undeclared'."""
    return UNDECLARED if result.errors else result.declaration.get(key)


def _new_dir(name: str, path: str) -> dict:
    return {"name": name, "path": path, "type": "dir", "files": 0, "lines": 0,
            "counts": {key: {w: Counter() for w in WEIGHTS} for key, _, _ in AXES},
            "errors": 0, "children": {}}


SOURCE_LIMIT = 512 * 1024  # bytes per file embedded with --with-source


def _runs(numbers) -> list[list[int]]:
    """[1, 2, 3, 7] -> [[1, 3], [7, 7]]"""
    out: list[list[int]] = []
    for n in sorted(numbers):
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return out


def _source(root: Path, path: str) -> tuple[str | None, str | None]:
    """(text, None) of a text file, or (None, why it isn't embedded)."""
    try:
        data = (root / path).read_bytes()
    except OSError:
        return None, "unreadable"
    if b"\x00" in data[:16384]:
        return None, "binary"
    if len(data) > SOURCE_LIMIT:
        return None, f"larger than {SOURCE_LIMIT // 1024} KB"
    return data.decode("utf-8", "replace"), None


def build_tree(root: Path, results, source: bool = False, changes: dict | None = None) -> dict:
    """See _build_tree. With source, text files carry their content ("source"); with changes
    ({path: (added line numbers, removed line count)}, see changed_since), files and folders
    carry what changed ("changed" runs, "added", "removed")."""
    tree = _build_tree(root, results)
    if source or changes is not None:
        _decorate(tree, Path(root), source, changes)
    return tree


def _decorate(node: dict, root: Path, source: bool, changes: dict | None) -> tuple[int, int, int]:
    if node["type"] == "file":
        if source:
            text, why = _source(root, node["path"])
            if text is not None:
                node["source"] = text
            else:
                node["source_skipped"] = why
        if changes is None:
            return 0, 0, 0
        added, removed = changes.get(node["path"], ([], 0))
        node["changed"] = _runs(added)
        node["added"], node["removed"] = len(added), removed
        return len(added), removed, int(bool(added or removed))
    totals = [0, 0, 0]
    for c in node["children"]:
        for i, v in enumerate(_decorate(c, root, source, changes)):
            totals[i] += v
    if changes is not None:
        node["added"], node["removed"], node["changed_files"] = totals
    return tuple(totals)


def changed_since(root: Path, base: str, files) -> tuple[str, dict]:
    """(sha of base, {path: (added line numbers, removed line count)}) for the given files,
    comparing base with the working tree; untracked files count as added in full."""
    from .diff import DiffError, _git, changed_lines
    sha = _git(Path(root), "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}", check=False).strip()
    if not sha:
        raise DiffError(f"{base} is not a commit")
    out = {}
    for (_, new), (removed, added) in changed_lines(Path(root), sha).items():
        if new:
            out[new] = (added, len(removed))
    tracked = set(_git(Path(root), "ls-files", "-z").split("\0"))
    for f in files:
        if f not in out and f not in tracked:
            out[f] = (list(range(1, line_count(Path(root), f) + 1)), 0)
    return sha, out


def _build_tree(root: Path, results) -> dict:
    """Nested folders with weighted level counts per axis; files are the leaves.

    Every folder carries, per axis and weight ("files" or "lines"), how much of it is at each
    level, with invalid or missing declarations counted as 'undeclared' (as the badges do).
    Folders with a single subfolder and no files are merged ("a/b"), as file browsers do.
    """
    top = _new_dir(Path(root).name or ".", "")
    for r in results:
        parts = r.path.split("/")
        weighted = {w: weighted_parts(Path(root), r, w) for w in WEIGHTS}
        lines = sum(w for _, _, w in weighted["lines"])
        file_counts = {key: {w: Counter() for w in WEIGHTS} for key, _, _ in AXES}
        for key, _, _ in AXES:
            for w in WEIGHTS:
                for d, errors, amount in weighted[w]:
                    file_counts[key][w][UNDECLARED if errors else d.get(key)] += amount
        # the level of most lines (with one part: the file's level)
        levels = {key: max(file_counts[key]["lines"].items(), key=lambda kv: kv[1])[0]
                  if lines else status_level(r, key) for key, _, _ in AXES}
        chain = [top]
        node = top
        for i, part in enumerate(parts[:-1]):
            node = node["children"].setdefault(part, _new_dir(part, "/".join(parts[: i + 1])))
            chain.append(node)
        leaf = {
            "name": parts[-1], "path": r.path, "type": "file", "files": 1, "lines": lines,
            "levels": levels, "declaration": r.declaration.as_dict(), "errors": list(r.errors),
        }
        if r.parts is not None and len(r.parts) > 1:
            leaf["counts"] = {key: {w: _ordered(key, file_counts[key][w]) for w in WEIGHTS} for key, _, _ in AXES}
        if r.parts is not None:
            leaf["parts"] = [{"lines": p.lines, "runs": p.runs, "declaration": p.declaration.as_dict(),
                              "levels": {key: UNDECLARED if p.errors else p.declaration.get(key) for key, _, _ in AXES},
                              "errors": p.errors} for p in r.parts]
        node["children"][parts[-1]] = leaf
        for d in chain:
            d["files"] += 1
            d["lines"] += lines
            d["errors"] += bool(r.errors)
            for key, _, _ in AXES:
                for w in WEIGHTS:
                    d["counts"][key][w].update(file_counts[key][w])
    return _finish(top, is_root=True)


def _finish(node: dict, is_root: bool = False) -> dict:
    if node["type"] == "file":
        return node
    children = [_finish(c) for c in node["children"].values()]
    while not is_root and len(children) == 1 and children[0]["type"] == "dir":
        only = children[0]  # merge a folder that holds nothing but one subfolder
        node = {**only, "name": f"{node['name']}/{only['name']}"}
        children = only["children"]
    # folders first, then files, each alphabetically
    children.sort(key=lambda c: (c["type"] != "dir", c["name"].lower()))
    node = dict(node, children=children)
    node["counts"] = {key: {w: _ordered(key, node["counts"][key][w]) for w in WEIGHTS}
                      for key, _, _ in AXES}
    return node


def _ordered(key: str, counts) -> dict:
    levels = dict((k, lv) for k, _, lv in AXES)[key]
    return {lv: counts.get(lv, 0) for lv in [*levels, UNDECLARED] if counts.get(lv, 0)}


# ------------------------------------------------------------------ text and Markdown
def mix(counts: dict) -> str:
    """'G0 20% · G3 80%' with integer percentages that sum to 100."""
    from .cli import percentages
    if not counts:
        return "-"
    pct = percentages(counts)
    return " · ".join(f"{lv} {pct[lv]}%" if pct[lv] else f"{lv} <1%" for lv in counts)


def number(x) -> str:
    return str(round(x)) if isinstance(x, float) else str(x)


def file_cell(n: dict, key: str, weight: str) -> str:
    """A file's level, or the mix of its lines when they differ (history mode)."""
    return mix(n["counts"][key][weight]) if "counts" in n and len(n["counts"][key][weight]) > 1 else n["levels"][key]


def _rows(node: dict, depth: int, max_depth: int | None, files: bool, prefix: str = ""):
    """Nodes in display order, each with its tree label (_label) and depth (_depth).

    Below a folder: its subfolders, and its files if 'files' is set (files with errors always)."""
    yield node
    if max_depth is not None and depth >= max_depth:
        return
    shown = [c for c in node["children"] if c["type"] == "dir" or files or c["errors"]]
    for i, child in enumerate(shown):
        is_last = i == len(shown) - 1
        child = dict(child, _label=prefix + ("└─ " if is_last else "├─ ") + child["name"]
                     + ("/" if child["type"] == "dir" else ""),
                     _depth=depth + 1)
        if child["type"] == "file":
            yield child
        else:
            yield from _rows(child, depth + 1, max_depth, files, prefix + ("   " if is_last else "│  "))


def render_text(tree: dict, weight: str = "files", max_depth: int | None = None, files: bool = False) -> str:
    rows = list(_rows(dict(tree, _label=".", _depth=0), 0, max_depth, files))
    header = ["", weight, *(title for _, title, _ in AXES)]
    table = [header]
    for n in rows:
        if n["type"] == "file" and n["errors"]:
            cells = ["✗", "✗", "✗ " + "; ".join(n["errors"])]  # the error text runs on in the last column
        elif n["type"] == "file":
            cells = [file_cell(n, key, weight) for key, _, _ in AXES]
        else:
            cells = [mix(n["counts"][key][weight]) for key, _, _ in AXES]
        table.append([n["_label"], number(n[weight]), *cells])
    widths = [max(len(r[i]) for r in table) for i in range(len(header) - 1)]
    out = []
    for r in table:
        cells = [r[0].ljust(widths[0]), r[1].rjust(widths[1])] + [c.ljust(w) for c, w in zip(r[2:-1], widths[2:])]
        out.append("  ".join([*cells, r[-1]]).rstrip())
    return "\n".join(out)


def _md(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def render_markdown(tree: dict, weight: str = "files", max_depth: int | None = None, files: bool = False) -> str:
    """The tree as a Markdown table (for $GITHUB_STEP_SUMMARY), problems listed below it."""
    head = f"| Folder | {weight.capitalize()} | " + " | ".join(t for _, t, _ in AXES) + " |"
    out = [head, "|" + " --- |" * 2 + " --- |" * len(AXES)]
    for n in _rows(dict(tree, _label=".", _depth=0), 0, max_depth, files):
        indent = "&nbsp;&nbsp;&nbsp;&nbsp;" * n["_depth"]
        if n["type"] == "file":
            name = f"{indent}{'✗ ' if n['errors'] else ''}`{_md(n['name'])}`"
            cells = [file_cell(n, key, weight).replace(UNDECLARED, "✗") for key, _, _ in AXES]
        else:
            label = "." if n["_depth"] == 0 else n["name"] + "/"
            name = f"{indent}**{_md(label)}**" + (f" ✗ {n['errors']}" if n["errors"] else "")
            cells = [mix(n["counts"][key][weight]) for key, _, _ in AXES]
        out.append(f"| {name} | {number(n[weight])} | " + " | ".join(cells) + " |")
    problems = []
    _collect_errors(tree, problems)
    if problems:
        out += ["", f"<details><summary>✗ {len(problems)} file(s) without a valid declaration</summary>", ""]
        out += [f"- `{_md(p)}`: {_md('; '.join(e))}" for p, e in problems]
        out += ["", "</details>"]
    return "\n".join(out)


def _collect_errors(node: dict, out: list) -> None:
    for c in node.get("children", []):
        if c["type"] == "file":
            if c["errors"]:
                out.append((c["path"], c["errors"]))
        elif c["errors"]:
            _collect_errors(c, out)


# ------------------------------------------------------------------ HTML
def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def report_meta(root: Path, title: str | None = None, link: str | None = None, since: dict | None = None) -> dict:
    """Header facts for the HTML report. On GitHub Actions, files link to the commit's blob view."""
    root = Path(root)
    commit = os.environ.get("GITHUB_SHA") or _git(root, "rev-parse", "HEAD")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if link is None and repo and commit:
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        link = f"{server}/{repo}/blob/{commit}/"
    return {
        "title": title or repo or root.name,
        "commit": commit,
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "version": __version__,
        "link": link,
        "axes": [{"key": key, "title": title_, "levels": levels} for key, title_, levels in AXES],
        "since": since,  # {"name": "origin/main", "commit": sha} with --since
    }


def render_html(tree: dict, meta: dict) -> str:
    template = resources.files("aisignoff").joinpath("report.html").read_text(encoding="utf-8")
    data = json.dumps({"meta": meta, "tree": tree}, ensure_ascii=False, separators=(",", ":"))
    # inside <script>: '<' escaped, so no file name can close the element or open a comment
    data = data.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    page_title = meta["title"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return template.replace("__AISIGNOFF_TITLE__", page_title).replace("__AISIGNOFF_DATA__", data)
