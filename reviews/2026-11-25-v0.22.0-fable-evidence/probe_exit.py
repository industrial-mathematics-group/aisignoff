"""Probe: exit codes (contract 6.2) and the git version check (contract 2.3).

usage: python probe_exit.py /path/to/aisignoff /scratch/dir"""
import os
import shutil
import stat
import sys
from pathlib import Path

from lib import DECL, ENV, HIST, Repo

exe, work = sys.argv[1], Path(sys.argv[2])
NO_HISTORY = HIST.replace('[history]\nenabled = true\ndefault-branch = "main"\n', "")


def row(name, got, expected):
    code, out, err = got
    first = (err.strip().splitlines() or out.strip().splitlines() or [""])
    trace = " TRACEBACK" if "Traceback" in err else ""
    flag = "ok  " if code in expected else "DIFF"
    print(f"{flag} exit {code} (expected {'/'.join(map(str, expected))}){trace}  {name}\n        {first[-1][:170]}")


def fresh(toml=HIST):
    r = Repo(work / "exit", exe, toml)
    r.write("a.txt", "one\ntwo\n")
    r.commit("a\n\n" + DECL)
    return r


# ---------------------------------------------------------------- git too old, git missing
real_git = shutil.which("git")
old = work / "oldgit"
old.mkdir(exist_ok=True)
(old / "git").write_text(f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "git version 2.30.2"; exit 0; fi\nexec {real_git} "$@"\n')
(old / "git").chmod(0o755)
old_env = {**ENV, "PATH": f"{old}:{ENV['PATH']}"}
nogit = work / "nogit"
nogit.mkdir(exist_ok=True)
for tool in ("python3", "sh", "env"):
    if not (nogit / tool).exists():
        os.symlink(shutil.which(tool), nogit / tool)
none_env = {**ENV, "PATH": str(nogit)}

print("=== X1: git 2.30 (a wrapper that only changes 'git --version'); contract 2.3: stops with exit code 2\n")
for name, toml in (("[history] on", HIST), ("no [history]", NO_HISTORY)):
    r = fresh(toml)
    blob_args = ("attest", "a.txt", "-H", "H2", "--reviewed-by", "Dev")
    for cmd in (("lint",), ("report",), ("report", "--tree"), ("badge", "--out", str(work / "b")), ("diff", "HEAD"),
                blob_args, ("correct", "HEAD", "-H", "H2", "--reviewed-by", "Dev"), ("gc", "--dry-run")):
        expected = (2,)
        row(f"{name}: {' '.join(cmd[:2])}", r.cli(*cmd, env=old_env), expected)
        r.g("checkout", "-q", "--", "SIGNOFF.toml")
print("\n=== X2: git not installed\n")
for name, toml in (("[history] on", HIST), ("no [history]", NO_HISTORY)):
    r = fresh(toml)
    for cmd in (("lint",), ("report",), ("diff", "HEAD")):
        row(f"{name}: {' '.join(cmd)}", r.cli(*cmd, env=none_env), (2,))

# ---------------------------------------------------------------- settings that name nothing
print("\n=== X3: settings that name nothing: exit 2 for every command\n")
for setting in ('default-branch = "develop"', 'ignore-revs-file = "missing-file"', 'require-trailers-since = "abc1234"'):
    r = fresh(HIST.replace('default-branch = "main"', setting))
    for cmd in (("lint",), ("report",), ("badge", "--out", str(work / "b")), ("diff", "HEAD"), ("gc", "--dry-run")):
        row(f"{setting}: {cmd[0]}", r.cli(*cmd), (2,))

# ---------------------------------------------------------------- files that can't be read or written
print("\n=== X4: files that can't be read or written, and usage errors: exit 2, no traceback\n")
r = fresh()
row("no command", r.cli(), (2,))
row("lint --declare-from a missing file", r.cli("lint", "--declare-from", "missing.md"), (2,))
row("lint --declare-from a folder", r.cli("lint", "--declare-from", "."), (2,))
r.write("latin1.md", "AI-Generation: G3 \xe9\n".encode("latin-1"))
row("lint --declare-from a file that isn't UTF-8", r.cli("lint", "--declare-from", "latin1.md"), (2,))
(r.d / "latin1.md").unlink()
row("report --html into a path below a file", r.cli("report", "--html", "a.txt/report.html"), (2,))
row("diff of a commit that doesn't exist", r.cli("diff", "nope"), (2,))
row("--root names a file", r.cli("--root", "a.txt", "lint"), (2,))
r.write("AGENTS.md", b"# agents \xff\xfe\n")
row("guide --agents-md with an AGENTS.md that isn't UTF-8", r.cli("guide", "--agents-md"), (2,))
(r.d / "AGENTS.md").unlink()
r.write("skills", "a file\n")
row("guide --skills into a path below a file", r.cli("guide", "--skills", "skills/x"), (2,))
(r.d / "skills").unlink()
r.write("reviews", "a file, not a folder\n")
r.commit("reviews is a file")
row("attest -a when the review folder is a file",
    r.cli("attest", "a.txt", "-a", "A1", "--findings", "none", "--ai-reviewed-by", "GPT Sol (OpenAI), new session"), (2,))
r = fresh()
(r.d / "reviews").mkdir()
r.write("reviews/r.toml", b"\xff\xfe not utf-8")
row("a record file that isn't UTF-8", r.cli("lint"), (2,))
(r.d / "reviews/r.toml").unlink()
(r.d / "reviews/dir.toml").mkdir()
row("a folder named like a record file (skipped)", r.cli("lint"), (0,))
(r.d / "reviews/dir.toml").rmdir()
if os.geteuid() != 0:
    r.write("reviews/r.toml", "x = 1\n")
    (r.d / "reviews/r.toml").chmod(0)
    row("a record file that can't be read", r.cli("lint"), (2,))
    (r.d / "reviews/r.toml").chmod(0o644)
    (r.d / "reviews/r.toml").unlink()
    (r.d / "SIGNOFF.toml").chmod(0)
    row("SIGNOFF.toml can't be read", r.cli("lint"), (2,))
    (r.d / "SIGNOFF.toml").chmod(stat.S_IRUSR)
    row("SIGNOFF.toml can't be written: annotate", r.cli("annotate", "a.txt", "-g", "G0", "-H", "H1", "-a", "A0",
                                                         "--reviewed-by", "Dev"), (2,))
    row("SIGNOFF.toml can't be written: correct", r.cli("correct", "HEAD", "-H", "H2", "--reviewed-by", "Dev"), (2,))
    (r.d / "SIGNOFF.toml").chmod(0o644)
# ---------------------------------------------------------------- a repository git can't read
print("\n=== X5: git fails\n")
r = fresh()
head = r.g("rev-parse", "HEAD")
obj = r.d / ".git/objects" / head[:2] / head[2:]
obj.chmod(0o644)
obj.write_bytes(b"corrupt")
for cmd in (("lint",), ("report",), ("diff", "HEAD")):
    row(f"HEAD's commit object is corrupt: {' '.join(cmd)}", r.cli(*cmd), (2,))

print("\n=== X6: init next to an AGENTS.md that isn't UTF-8\n")
d = work / "exit-init"
shutil.rmtree(d, ignore_errors=True)
d.mkdir()
(d / "AGENTS.md").write_bytes(b"# agents \xff\xfe\n")
r.d = d
row("init (expected 2, and no SIGNOFF.toml left behind half-done)", r.cli("init"), (2,))
print("        SIGNOFF.toml was written:", (d / "SIGNOFF.toml").exists())
