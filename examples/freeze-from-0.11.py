#!/usr/bin/env python3
"""Keep the levels that aisignoff 0.11 reported when upgrading to 0.12.

aisignoff 0.12 decides a line's levels by simpler rules than 0.11 did (one owner per line: see
docs/history.md), so some lines of existing code would report other levels after the upgrade.
This script writes SIGNOFF.snapshot.json with the levels of every line as aisignoff 0.11 works
them out, in the format of 'aisignoff freeze'. aisignoff 0.12 then keeps them for every line that
doesn't change, and applies its own rules to what lands afterwards.

Run it once, with aisignoff 0.11 and before upgrading, at a clean checkout of a commit of the
default branch (on a new branch at that commit if you use pull requests), and commit the file:

    uv run --no-project --with aisignoff==0.11.0 python freeze-from-0.11.py
    # or: python -m venv old && old/bin/pip install aisignoff==0.11.0 && old/bin/python freeze-from-0.11.py

Only needed for repositories that use [history]. Later snapshots are 'aisignoff freeze'.
"""
import json
import subprocess
import sys
from pathlib import Path

import aisignoff
from aisignoff.project import Project

SNAPSHOT = "SIGNOFF.snapshot.json"


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True).stdout.decode("utf-8", "surrogateescape")


def main(root="."):
    if not aisignoff.__version__.startswith("0.11."):
        sys.exit(f"this script is for aisignoff 0.11, not {aisignoff.__version__}: with 0.12, run 'aisignoff freeze'")
    project = Project(Path(root))
    root = project.root
    if any(line[3:] != SNAPSHOT for line in git(root, "status", "--porcelain", "--untracked-files=all").splitlines()):
        sys.exit("the working tree has changes: check out a commit of the default branch with nothing else changed")
    results = project.results()
    if not project.history_used:
        sys.exit("[history] is not enabled or not usable here (a shallow clone?): there is nothing to keep")
    if project.history_problems or any(r.errors for r in results):
        sys.exit("'aisignoff lint' fails here; a snapshot would keep those errors for good, so fix them first")
    commit = git(root, "rev-parse", "HEAD").strip()
    blobs = {}
    for row in git(root, "ls-tree", "-r", "-z", "HEAD").split("\0"):
        meta, _, name = row.partition("\t")
        if name:
            blobs[name] = meta.split()[2]
    declarations, index, files, lines = [], {}, [], 0
    for r in results:
        if r.parts is None or r.path not in blobs:
            continue  # file-level (precedence = "override"): the annotation keeps declaring it
        runs = []
        for part in r.parts:
            text = json.dumps({**part.declaration.as_dict(), "source": part.declaration.source}, ensure_ascii=False)
            n = index.setdefault(text, len(declarations))
            if n == len(declarations):
                declarations.append(text)
            runs += [[a, b, n] for a, b in part.runs]
        runs.sort()
        lines += sum(b - a + 1 for a, b, _ in runs)
        files.append(f" {json.dumps(r.path, ensure_ascii=False)}: "
                     + json.dumps({"blob": blobs[r.path], "runs": runs}, separators=(", ", ": ")))
    out = ["{", ' "format": 1,', f' "aisignoff": {json.dumps(aisignoff.__version__)},', f' "commit": "{commit}",',
           ' "declarations": [', ",\n".join("  " + d for d in declarations), " ],",
           ' "files": {', ",\n".join(" " + f for f in files), " }", "}"]
    (root / SNAPSHOT).write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Wrote {SNAPSHOT}: the levels of {lines} lines in {len(files)} files as of commit {commit[:7]}, "
          f"as aisignoff {aisignoff.__version__} reports them. Commit it, then upgrade.")


if __name__ == "__main__":
    main(*sys.argv[1:2])
