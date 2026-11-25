"""New evidence for D6 / contract 5.6 and 5.7: "the check before the merge shows what lands".

A differential test. For random old content (text, binary to git, or binary only to aisignoff's 16 KiB
probe), random new text content, optional .gitattributes, an optional rename and both settings of
ignore-whitespace, it compares, line by line:

  1. report --json --base main --declare-from D on the feature branch (the check before the merge),
  2. report --json on main after 'git merge --no-ff' with the same declaration (what git blame gives),
  3. the same after the merge with the blame cache on (a cache written before the merge), and
  4. the counts of 'diff main~1 --json' (added = the lines the merge owns, checked with ignore-whitespace = false;
     removed = 1 for a binary old side).

usage: python fuzz_binary_text.py /path/to/aisignoff /scratch/dir [iterations] [seed]"""
import json
import random
import sys
from pathlib import Path

from lib import DECL, ENV, H3, HIST, Repo

exe, work = sys.argv[1], Path(sys.argv[2])
iterations = int(sys.argv[3]) if len(sys.argv) > 3 else 150
seed = int(sys.argv[4]) if len(sys.argv) > 4 else 20261125

WORDS = [b"alpha", b"beta", b"gamma", b"delta", b"  indented", b"}", b"", b"x = 1", b"return x", b"end"]


def old_content(rng, kind):
    lines = [rng.choice(WORDS) for _ in range(rng.randint(2, 12))]
    if kind == "binary":  # a NUL that git sees too
        lines.insert(rng.randrange(len(lines) + 1), b"\x00\x01bin" + rng.choice(WORDS))
    elif kind == "probe":  # a NUL past git's 8,000 bytes, inside aisignoff's 16,384
        lines.insert(0, b"p" * 9000)
        lines.insert(rng.randrange(1, len(lines) + 1), b"\x00late")
    return lines


def new_content(rng, old):
    out = []
    for line in old:
        if b"\x00" in line:
            if rng.random() < 0.5:
                out.append(line.replace(b"\x00", b"").replace(b"\x01", b""))
            continue
        r = rng.random()
        if r < 0.15:
            continue
        if r < 0.25:
            out.append(b"changed " + line)
        elif r < 0.33:
            out.append(b"    " + line.strip())  # whitespace only
        else:
            out.append(line)
        if rng.random() < 0.15:
            out.append(rng.choice(WORDS))
    return out or [b"only line"]


def join(lines, rng):
    data = b"\n".join(lines)
    return data + (b"" if rng.random() < 0.15 else b"\n")


rng = random.Random(seed)
failures = 0
whitespace_only = 0
counts = {}
for i in range(iterations):
    kind = rng.choice(["text", "binary", "binary", "probe"])
    attributes = rng.choice([None, None, "data* -diff", "data* diff", "data* binary"])
    whitespace = rng.random() < 0.7
    rename = rng.random() < 0.2
    old = old_content(rng, kind)
    new = new_content(rng, old)
    old_bytes, new_bytes = join(old, rng), join(new, rng)
    toml = HIST if whitespace else HIST.replace("enabled = true", "enabled = true\nignore-whitespace = false")
    r = Repo(work / "fuzz", exe, toml)
    if attributes:
        r.write(".gitattributes", attributes + "\n")
    r.write("data", old_bytes)
    r.commit("add data\n\n" + DECL)
    r.g("switch", "-qc", "feature")
    name = "data"
    if rename:
        r.g("mv", "data", "data2")
        name = "data2"
    r.write(name, new_bytes)
    r.commit("rewrite as text")
    description = work / "fuzz-description.md"
    description.write_text(H3)
    before = r.lines(name, "--base", "main", "--declare-from", str(description))
    cached_env = {k: v for k, v in ENV.items() if k != "AISIGNOFF_NO_CACHE"}
    r.cli("report", "--json", env=cached_env)  # writes a blame cache at main's commit
    r.g("switch", "-q", "main")
    r.g("merge", "-q", "--no-ff", "feature", "-m", "Merge the text\n\n" + H3)
    after = r.lines(name)
    code, out, err = r.cli("report", "--json", env=cached_env)
    f = next(f for f in json.loads(out)["files"] if f["path"] == name)
    got = {}
    for p in f["parts"]:
        for a, b in p["runs"]:
            for n in range(a, b + 1):
                got[n] = p["Human-Review"]
    cached = [got[n] for n in sorted(got)]
    code, out, err = r.cli("diff", "main~1", "--json")
    total = json.loads(out)["total"] if code == 0 else {"added": None, "removed": None}
    old_is_binary = kind != "text"
    # the removed side: one unit for a binary old side; for text, whatever git's diff removes (not checked here)
    problems = []
    if before != after:
        problems.append("before the merge != after the merge")
    if cached != after:
        problems.append("with the blame cache != without")
    if isinstance(after, list) and total["added"] != after.count("H3"):
        if whitespace:
            # not a failure: with ignore-whitespace, 'diff' still counts a line that changed only in whitespace as
            # added (git diff without -w), with the levels of the commit that keeps owning it
            whitespace_only += 1
        else:
            problems.append(f"diff added {total['added']} != lines the merge owns {after.count('H3')}")
    if old_is_binary and total["removed"] != 1:
        problems.append(f"diff removed {total['removed']} for a binary old side")
    key = (kind, attributes, "rename" if rename else "", "-w" if whitespace else "")
    counts[kind] = counts.get(kind, 0) + 1
    if problems:
        failures += 1
        print(f"FAIL #{i} {key}: {'; '.join(problems)}")
        print(f"   old    = {old_bytes!r}"[:400])
        print(f"   new    = {new_bytes!r}"[:400])
        print(f"   before = {before}\n   after  = {after}\n   cached = {cached}\n   diff   = +{total['added']} -{total['removed']}")
print(f"\n{iterations} cases (seed {seed}; old side: {counts}), {failures} failed")
print(f"{whitespace_only} case(s) with ignore-whitespace where 'diff' counts whitespace-only changes as added lines (noted, not a failure)")
