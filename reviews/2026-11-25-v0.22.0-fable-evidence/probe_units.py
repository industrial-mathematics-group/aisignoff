"""Probe: units (contract 5.6) at the edges of the 0.21.0 and 0.22.0 changes.

U1  'diff' counts of a binary file replaced by text, where the old side has no line parts
    (no [history], or precedence = "override").
U2  a file that git converts (working-tree-encoding) and that a pull request changes or adds:
    the check before the merge against what lands.
U3  the same for a clean/smudge filter (as Git LFS: git stores a text pointer).

usage: python probe_units.py /path/to/aisignoff /scratch/dir"""
import json
import sys
from pathlib import Path

from lib import DECL, H3, HIST, Repo, show

exe, work = sys.argv[1], Path(sys.argv[2])
TAIL = b"same line 2\nsame line 3\nsame line 4\n"
description = work / "units-description.md"
description.write_text(H3)


def diff_counts(r, *args):
    code, out, err = r.cli("diff", *args, "--json")
    if code != 0:
        return f"exit {code}: {err.strip()[-200:]}"
    t = json.loads(out)["total"]
    return f"+{t['added']} -{t['removed']}"


print("=== U1: binary (6 'lines', 3 of them not in the text) -> text, 'diff main': the docs say the binary version is one removed unit\n")
for name, toml in {
    "[history] on": HIST,
    "no [history]": HIST.replace("[history]\nenabled = true\ndefault-branch = \"main\"\n", ""),
    'precedence = "override"': HIST.replace('path = "**"', 'path = "**"\nprecedence = "override"'),
}.items():
    r = Repo(work / "units", exe, toml)
    r.write("data", b"\x00binary\nold a\nold b\n" + TAIL)
    r.commit("add binary data\n\n" + DECL)
    r.g("switch", "-qc", "feature")
    r.write("data", b"new line 1\n" + TAIL)
    r.commit("text")
    print(f"{name:26} diff main: {diff_counts(r, 'main')}")
print()

print("=== U2: working-tree-encoding=UTF-16 (git stores UTF-8 text; the work tree has NUL bytes)\n")
r = Repo(work / "units", exe)
r.write(".gitattributes", "*.u16 text working-tree-encoding=UTF-16\n")
r.write("old.u16", "line 1\nline 2\nline 3\nline 4\n".encode("utf-16"))
r.commit("add a UTF-16 file\n\n" + DECL)
print("landed, unchanged:           old.u16", r.lines("old.u16"))
r.g("switch", "-qc", "feature")
r.write("old.u16", "line 1\nLINE 2\nline 3\nline 4\n".encode("utf-16"))
r.write("new.u16", "a\nb\nc\n".encode("utf-16"))
r.commit("edit one line, add a file")
args = ("--base", "main", "--declare-from", str(description))
print("before the merge (committed): old.u16", r.lines("old.u16", *args), " new.u16", r.lines("new.u16", *args))
print("before the merge, diff main: ", diff_counts(r, "main", "--declare-from", str(description)))
code, out, err = r.cli("diff", "main", "--declare-from", str(description), "--json", "--files")
for row in json.loads(out)["rows"]:
    print("    ", row["name"], f"+{row['added']} -{row['removed']}", row["levels_added"]["Human-Review"])
r.g("switch", "-q", "main")
r.g("merge", "-q", "--no-ff", "feature", "-m", "Merge\n\n" + H3)
print("after the merge:             old.u16", r.lines("old.u16"), " new.u16", r.lines("new.u16"))
print("after the merge, diff main~1:", diff_counts(r, "main~1"))
print()

print("=== U3: a clean/smudge filter (as Git LFS: git stores a three-line text pointer, the work tree binary)\n")
r = Repo(work / "units", exe)
# the filter is set in the repository's own configuration, as 'git lfs install --local' does
filt = Path(__file__).with_name("ptr_filter.py")
r.g("config", "filter.ptr.clean", f"python3 {filt} clean {work / 'ptr-store'}")
r.g("config", "filter.ptr.smudge", f"python3 {filt} smudge {work / 'ptr-store'}")
r.write(".gitattributes", "*.bin filter=ptr\n")
r.write("blob.bin", b"\x00\x01\x02 first version\n")
r.commit("add a filtered binary\n\n" + DECL)
print("landed, unchanged:           blob.bin", r.lines("blob.bin"))
r.g("switch", "-qc", "feature")
r.write("blob.bin", b"\x00\x01\x02 second version, longer\n")
r.commit("new binary")
print("before the merge (committed): blob.bin", r.lines("blob.bin", *args))
print("before the merge, diff main: ", diff_counts(r, "main", "--declare-from", str(description)))
r.g("switch", "-q", "main")
r.g("merge", "-q", "--no-ff", "feature", "-m", "Merge\n\n" + H3)
print("after the merge:             blob.bin", r.lines("blob.bin"))
print("after the merge, diff main~1:", diff_counts(r, "main~1"))
print()

print("=== U4: a UTF-16 file that the change only renames\n")
r = Repo(work / "units", exe)
r.write(".gitattributes", "*.u16 text working-tree-encoding=UTF-16\n")
r.write("old.u16", "line 1\nline 2\nline 3\nline 4\n".encode("utf-16"))
r.commit("add a UTF-16 file\n\n" + DECL)
r.g("switch", "-qc", "feature")
r.g("mv", "old.u16", "moved.u16")
r.commit("rename")
print("before the merge: moved.u16", r.lines("moved.u16", *args))
r.g("switch", "-q", "main")
r.g("merge", "-q", "--no-ff", "feature", "-m", "Merge\n\n" + H3)
print("after the merge:  moved.u16", r.lines("moved.u16"))
print()

print("=== U5: report --html --since, binary (6 'lines', 3 of them not in the text) -> text, with [history]\n")
r = Repo(work / "units", exe)
r.write("data", b"\x00binary\nold a\nold b\n" + TAIL)
r.commit("add binary data\n\n" + DECL)
r.g("switch", "-qc", "feature")
r.write("data", b"new line 1\n" + TAIL)
r.commit("text")
code, out, err = r.cli("report", "--html", str(work / "units-report.html"), "--since", "main")
import re
html = (work / "units-report.html").read_text()
m = re.search(r'"added":(\d+),"removed":(\d+)', html[html.index('"path":"data"'):])
print("report --html --since main: data", f"+{m.group(1)} -{m.group(2)}" if m else "(counts not found in the report's data)")
print("diff main:                  data", diff_counts(r, "main"))
