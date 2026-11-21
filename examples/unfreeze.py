#!/usr/bin/env python3
"""Move a repository off SIGNOFF.snapshot.json, which aisignoff 0.17 no longer reads.

Up to 0.16, 'aisignoff freeze' kept the levels of every line in SIGNOFF.snapshot.json, and
'freeze --prune' moved [[commits]] and [[attestations]] entries of SIGNOFF.toml into its archive.
From 0.17 on, every line is worked out from the whole history again (docs/history.md). This
script keeps what the snapshot said where history alone says otherwise:

1. it puts the archived entries back into SIGNOFF.toml;
2. it works out the lines of the snapshot's commit without the snapshot and, for each commit that
   landed lines whose levels would change, adds a [[commits]] entry with the levels the snapshot
   had for them (the axes on which all of that commit's lines agree);
3. it lists the lines that still differ, and deletes SIGNOFF.snapshot.json.

Run it with aisignoff 0.17 at the repository root, on a branch of the default branch with
nothing else changed, then look over the diff and commit SIGNOFF.toml and the deletion together:

    python unfreeze.py            # or: --dry-run to see the entries and the lines that differ only
"""
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from aisignoff.model import AI_REVIEWED, AIR, AXES, FINDINGS, from_version_3
from aisignoff.project import Project

SNAPSHOT, NAME = "SIGNOFF.snapshot.json", "SIGNOFF.toml"


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def toml_value(v):
    return json.dumps(v, ensure_ascii=False)  # a TOML basic string or array of them is JSON


def table(kind, values, comment=""):
    rows = [f"[[{kind}]]" + (f"   # {comment}" if comment else "")]
    rows += [f"{k} = {toml_value(v)}" for k, v in values.items() if v not in (None, [], "")]
    return "\n".join(rows) + "\n"


def old_scale(d, rules):
    """A declaration as today's scale reads it (snapshots of rules 0 and 1 have the scale before version 4)."""
    if rules is not None and rules >= 2 or not isinstance(d.get(AIR), str):
        return d
    level, names = from_version_3(d[AIR], d.get(AI_REVIEWED) or ())
    return {**d, AIR: level, AI_REVIEWED: list(names)}


def levels(project):
    """(path, line) -> (the declaration as a dict without its source, the origin of the line)."""
    out = {}
    for r in project.results(quiet=True):
        if r.parts is None:
            continue
        origins = project.history.line_origins(r.path)
        for p in r.parts:
            d = {k: v for k, v in p.declaration.as_dict().items() if k != "source"}
            for a, b in p.runs:
                for n in range(a, b + 1):
                    out[(r.path, n)] = (d, origins[n - 1] if n <= len(origins) else None)
    return out


def axis_values(d, i):
    level, names = AXES[i]
    out = {level: d.get(level), names: list(d.get(names) or [])}
    if i == 2 and d.get(FINDINGS):
        out[FINDINGS] = d[FINDINGS]
    return out


def main(argv):
    dry = "--dry-run" in argv
    root = Path(".").resolve()
    path = root / SNAPSHOT
    if not path.is_file():
        sys.exit(f"no {SNAPSHOT} here: nothing to do")
    snap = json.loads(path.read_text(encoding="utf-8"))
    rules = snap.get("rules") if isinstance(snap.get("rules"), int) else None
    declarations = [old_scale(d, rules) for d in snap["declarations"]]
    toml = (root / NAME).read_text(encoding="utf-8")

    # 1. the archive back into SIGNOFF.toml
    restored = ""
    for item in snap.get("archive", []):
        for kind in ("commits", "attestations"):
            for e in item.get(kind, []):
                restored += "\n" + table(kind, old_scale(e, rules), f"from the archive of {SNAPSHOT}")
    toml_restored = toml.rstrip("\n") + "\n" + restored if restored else toml

    # 2. the snapshot's commit, worked out without the snapshot
    with tempfile.TemporaryDirectory(prefix="aisignoff-unfreeze-") as tmp:
        where = Path(tmp) / "at"
        git(root, "-c", "core.hooksPath=/dev/null", "worktree", "add", "--detach", "--quiet", str(where), snap["commit"])
        try:
            (where / SNAPSHOT).unlink(missing_ok=True)
            (where / NAME).write_text(toml_restored, encoding="utf-8")
            want = {}
            for p, entry in snap["files"].items():
                for a, b, i in entry["runs"]:
                    for n in range(a, b + 1):
                        want[(p, n)] = {k: v for k, v in declarations[i].items() if k != "source"}
            now = levels(Project(where))

            def key(d, i):
                return json.dumps(axis_values(d, i), sort_keys=True)

            owners = defaultdict(list)  # commit -> the snapshot's lines it owns, with what they should be
            for k, target in want.items():
                d, origin = now.get(k, (None, None))
                if d is None or origin is None or origin[0] != "landed" or origin[1] is None:
                    continue
                owners[origin[1]].append((target, d))
            entries = ""
            for sha, rows in owners.items():
                axes = {}
                for i in range(3):
                    targets = {key(t, i) for t, _ in rows}
                    if len(targets) == 1 and any(key(t, i) != key(d, i) for t, d in rows):
                        axes.update(axis_values(rows[0][0], i))
                if not axes:
                    continue
                subject = git(where, "log", "-1", "--format=%s", sha).strip()
                subject = subject if len(subject) <= 50 else subject[:49] + "…"
                entries += "\n" + table("commits", {"commit": sha, **axes}, f"{subject}: as {SNAPSHOT} had it")
            (where / NAME).write_text(toml_restored.rstrip("\n") + "\n" + entries, encoding="utf-8")
            after = levels(Project(where))
            differ = sorted(k for k, t in want.items() if k in after and
                            {a: v for a, v in after[k][0].items()} != t)
        finally:
            git(root, "worktree", "remove", "--force", str(where))

    new = toml_restored.rstrip("\n") + "\n" + entries
    print(f"{len(entries.split('[[commits]]')) - 1} [[commits]] entries keep the snapshot's levels; "
          f"{restored.count('[[')} archived entries go back into {NAME}.")
    if differ:
        files = defaultdict(list)
        for p, n in differ:
            files[p].append(n)
        print(f"{len(differ)} of {len(want)} lines of the snapshot's commit still differ from it:")
        for p, ns in sorted(files.items(), key=lambda t: -len(t[1])):
            print(f"  {p}: {len(ns)} line(s), from line {ns[0]}")
    if dry:
        print("\n" + restored + entries)
        return
    (root / NAME).write_text(new, encoding="utf-8")
    path.unlink()
    print(f"Wrote {NAME} and deleted {SNAPSHOT}. Check 'aisignoff lint', then commit both.")


if __name__ == "__main__":
    main(sys.argv[1:])
