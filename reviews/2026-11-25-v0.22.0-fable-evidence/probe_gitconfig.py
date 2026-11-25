"""New evidence for contract 2.2: "a result doesn't depend on the user's or the system's git configuration".

A differential test: the same repository and the same commands, each time with a user-level git
configuration (GIT_CONFIG_GLOBAL) that holds one setting. The result (report --json, before and after
the merge) must be the same as with an empty configuration. The same for a few environment variables of git
(contract 2.1 and 8: only the variables of section 8 are inputs).

usage: python probe_gitconfig.py /path/to/aisignoff /scratch/dir"""
import json
import sys
from pathlib import Path

from lib import DECL, ENV, H3, Repo

exe, work = sys.argv[1], Path(sys.argv[2])

OLD = "".join(f"line {n}\n" for n in range(1, 21))
NEW = OLD.replace("line 5\n", "LINE 5\n").replace("line 8\n", "LINE 8\n").replace("line 15\n", "LINE 15\n")
FUNCS = "def a():\n    x = 1\n    return x\n\n\ndef b():\n    y = 2\n    return y\n"
FUNCS_NEW = FUNCS.replace("def b():", "def c():\n    z = 3\n    return z\n\n\ndef b():")

r = Repo(work / "gitconfig", exe)
r.write("text.txt", OLD)
r.write("funcs.py", FUNCS)
r.write("moved.txt", "".join(f"moved {n}\n" for n in range(1, 31)))
r.write("crlf.txt", b"a\r\nb\r\nc\r\n")
r.write("unit.bin", b"\x00\x01\n")
r.commit("content\n\n" + DECL)
r.g("switch", "-qc", "feature")
r.write("text.txt", NEW)
r.write("funcs.py", FUNCS_NEW)
r.g("mv", "moved.txt", "renamed.txt")
r.write("renamed.txt", "".join(f"moved {n}\n" for n in range(1, 31)).replace("moved 7\n", "MOVED 7\n"))
r.write("crlf.txt", b"a\r\nB\r\nc\r\n")
r.write("unit.bin", b"\x00\x02\n")
r.commit("change\n\nAI-Generation: G3\nAssisted-by: Claude Opus 5.5 (Anthropic)\n")
description = work / "gitconfig-description.md"
description.write_text(H3)
attributes = work / "global-attributes"
attributes.write_text("*.txt -diff\n")
ignore = work / "global-ignore-revs"
ignore.write_text(r.g("rev-parse", "main") + "\n")

SETTINGS = [
    None,
    ("diff", "interHunkContext = 10"),
    ("diff", "context = 7"),
    ("diff", "algorithm = histogram"),
    ("diff", "indentHeuristic = false"),
    ("diff", "renames = false"),
    ("diff", "renameLimit = 1"),
    ("diff", "noprefix = true"),
    ("diff", "mnemonicPrefix = true"),
    ("diff", "suppressBlankEmpty = true"),
    ("diff", "ignoreSubmodules = all"),
    ("diff", "external = false"),
    ("diff", "orderFile = /dev/null"),
    ("core", "autocrlf = true"),
    ("core", "autocrlf = input"),
    ("core", "quotePath = false"),
    ("core", "abbrev = 4"),
    ("core", f"attributesFile = {attributes}"),
    ("blame", f"ignoreRevsFile = {ignore}"),
    ("blame", "markIgnoredLines = true"),
    ("status", "showUntrackedFiles = no"),
    ("status", "branch = true"),
    ("status", "relativePaths = false"),
    ("log", "showSignature = true"),
    ("log", "follow = true"),
    ("i18n", "logOutputEncoding = latin1"),
    ("color", "ui = always"),
    ("color", "diff = always"),
]


ENVIRONMENT = [("GIT_DIFF_OPTS", "--unified=3"), ("GIT_EXTERNAL_DIFF", "false"), ("GIT_PAGER", "false"),
               ("GIT_TEXTDOMAINDIR", "/nonexistent"), ("LANG", "de_DE.UTF-8"), ("GIT_OPTIONAL_LOCKS", "0")]


def results(config, *args):
    path = work / "gitconfig-global"
    path.write_text("" if config is None or config[0].isupper() else f"[{config[0]}]\n\t{config[1]}\n")
    env = {**ENV, "GIT_CONFIG_GLOBAL": str(path)}
    if config is not None and config[0].isupper():  # an environment variable instead of a setting
        env[config[0]] = config[1]
    code, out, err = r.cli("report", "--json", *args, env=env)
    if code != 0:
        return f"exit {code}: {err.strip()[-200:]}"
    return {f["path"]: [(p["runs"], p["AI-Generation"], p["Human-Review"]) for p in f["parts"]]
            for f in json.loads(out)["files"]}


def compare(stage, *args):
    print(f"=== {stage}\n")
    reference = results(None, *args)
    different = 0
    for config in SETTINGS[1:] + ENVIRONMENT:
        got = results(config, *args)
        name = f"{config[0]}={config[1]} (environment)" if config[0].isupper() else f"{config[0]}.{config[1]}"
        if got == reference:
            print(f"same  {name}")
            continue
        different += 1
        print(f"DIFF  {name}")
        if isinstance(got, str):
            print("        ", got)
            continue
        for path in sorted(set(reference) | set(got)):
            if reference.get(path) != got.get(path):
                print(f"         {path}: empty configuration {reference.get(path)}")
                print(f"         {' ' * len(path)}  with the setting    {got.get(path)}")
    print(f"\n{different} of {len(SETTINGS) - 1 + len(ENVIRONMENT)} settings and variables change the result\n")


compare("before the merge: report --json --base main --declare-from", "--base", "main", "--declare-from", str(description))
r.g("switch", "-q", "main")
r.g("merge", "-q", "--no-ff", "feature", "-m", "Merge\n\n" + H3)
compare("after the merge: report --json")
