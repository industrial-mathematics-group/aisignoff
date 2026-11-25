"""Probe: unknown keys and requires-aisignoff (contract 4.2.3, 4.4.2), and exit codes (6.2).

usage: python probe_keys.py /path/to/aisignoff /scratch/dir"""
import itertools
import sys
from pathlib import Path

from lib import DECL, HIST, Repo, show

exe, work = sys.argv[1], Path(sys.argv[2])

# ---------------------------------------------------------------- K1: every place a key can be
r = Repo(work / "keys", exe)
r.write("a.txt", "one\n")
r.commit("a\n\n" + DECL)
blob = r.g("rev-parse", "HEAD:a.txt")
head = r.g("rev-parse", "HEAD")
ATT = f'\n[[attestations]]\npath = "a.txt"\nblob = "{blob}"\nHuman-Review = "H2"\nReviewed-by = "Dev"\n'
CASES = {
    "top level": HIST.replace("version = 4", "version = 4\nfoo = 1"),
    "[history]": HIST.replace("enabled = true", "enabled = true\nignore-whitespce = false"),
    "[review]": HIST + '\n[review]\ndirectory = "r"\n',
    "[policy] generation": HIST + '\n[policy]\nG4 = { human = "H1" }\n',
    "[policy] rule": HIST + '\n[policy]\n"*" = { human = "H1", note = "x" }\n',
    "[[annotations]]": HIST + 'note = "x"\n',
    "[[commits]]": HIST + f'\n[[commits]]\ncommit = "{head}"\nHuman-Review = "H2"\nReviewed-by = "Dev"\nnote = "x"\n',
    "[[attestations]]": HIST + ATT + 'note = "x"\n',
    "a sub-table of [history]": HIST + "\n[history.extra]\nx = 1\n",
    "a table that isn't one": HIST + "\n[annotation]\nx = 1\n",
}
print("=== K1: an unknown key anywhere in SIGNOFF.toml (expected: exit 2 for every command)\n")
for name, text in CASES.items():
    r.write("SIGNOFF.toml", text)
    codes = {c[0]: r.cli(*c)[0] for c in (["lint"], ["report"], ["badge", "--out", str(work / "badges")],
                                          ["diff", "HEAD"], ["gc", "--dry-run"])}
    code, out, err = r.cli("lint")
    print(f"{name:28} {codes}  {err.strip()[:150]}")
r.write("SIGNOFF.toml", HIST)

print("\n=== K2: record files of the review folder\n")
REC = f'[[attestations]]\npath = "a.txt"\nblob = "{blob}"\nAI-Review = "A1"\nAI-Reviewed-by = "GPT Sol (OpenAI), new session"\nAI-Review-Findings = "none"\n'
for name, text in {"valid": REC, "unknown key in an entry": REC + 'note = "x"\n',
                   "unknown top-level key": 'note = "x"\n' + REC,
                   "requires-aisignoff in a record file": 'requires-aisignoff = "0.22"\n' + REC,
                   "Human-Review in an entry": REC + 'Human-Review = "H1"\nReviewed-by = "Dev"\n'}.items():
    r.write("reviews/r.toml", text)
    code, out, err = r.cli("lint")
    print(f"{name:38} exit {code}  {(err or out).strip().splitlines()[0][:230]}")
(r.d / "reviews/r.toml").unlink()

print("\n=== K3: requires-aisignoff\n")
for value in ('"0.22"', '"0.22.0"', '"0.22.1"', '"0.23"', '"1.0"', '" 0.22 "', '"0.22.0.0"', '"v0.22"', '"0"', "0.22",
              '["0.22"]', '""'):
    r.write("SIGNOFF.toml", HIST.replace("version = 4", f"version = 4\nrequires-aisignoff = {value}"))
    code, out, err = r.cli("lint")
    print(f"requires-aisignoff = {value:10} exit {code}  {err.strip()[:170]}")
r.write("SIGNOFF.toml", HIST.replace("version = 4", 'version = 4\nrequires-aisignoff = "9.0"') + "\nnew-key = 1\n")
show("a newer key with requires-aisignoff: the release is named, not the key", *r.cli("lint"))
r.write("SIGNOFF.toml", HIST.replace("version = 4", 'version = 5\nrequires-aisignoff = "9.0"'))
show("version = 5", *r.cli("lint"))
r.write("SIGNOFF.toml", HIST)

# ---------------------------------------------------------------- K4: the pull request that removes an unknown key
print("=== K4: the default branch has a key that 0.20.1 only warned about; a pull request removes it\n")
r = Repo(work / "keys-base", exe, HIST.replace("version = 4", "version = 4\nnotes = \"kept from an older setup\""))
r.write("a.txt", "one\n")
r.commit("a\n\n" + DECL)
r.g("switch", "-qc", "fix")
r.write("SIGNOFF.toml", HIST)
r.commit("Remove the unknown key")
(work / "description.md").write_text(DECL)
show("lint on the fix branch", *r.cli("lint"))
show("lint --base main --declare-from (the check before the merge)",
     *r.cli("lint", "--base", "main", "--declare-from", str(work / "description.md")))
show("lint --declare-from, without --base", *r.cli("lint", "--declare-from", str(work / "description.md")))
show("diff main", *r.cli("diff", "main"))

# ---------------------------------------------------------------- K5: values of the wrong type never crash
print("=== K5: wrong types (expected: exit 2, never 3 and never 0)\n")
VALUES = ["1", "true", '"x"', "[]", "[1]", "{}", '{ a = 1 }', "1.5", '[{ a = 1 }]', "1979-05-27"]
KEYS = ["version", "requires-aisignoff", "exclude", "policy", "annotations", "history", "commits", "attestations", "review"]
bad = []
for key, value in itertools.product(KEYS, VALUES):
    text = (f"{key} = {value}\n" if key == "version" else f"version = 4\n{key} = {value}\n")
    r.write("SIGNOFF.toml", text)
    code, out, err = r.cli("lint")
    if code == 3 or "Traceback" in err:
        bad.append((key, value, code))
SUB = {"history": ["enabled", "require-trailers-since", "ignore-revs-file", "merge-method", "ignore-whitespace",
                   "default-branch", "undeclared"], "review": ["dir", "recheck"]}
for table, keys in SUB.items():
    for key, value in itertools.product(keys, VALUES):
        r.write("SIGNOFF.toml", f"version = 4\n[{table}]\n{key} = {value}\n")
        code, out, err = r.cli("lint")
        if code == 3 or "Traceback" in err:
            bad.append((f"{table}.{key}", value, code))
for table, keys in {"annotations": ["path", "precedence", "AI-Generation", "Assisted-by", "AI-Review-Findings"],
                    "commits": ["commit", "Human-Review", "Reviewed-by"],
                    "attestations": ["path", "blob", "commit", "AI-Review", "AI-Reviewed-by", "AI-Review-Findings"]}.items():
    for key, value in itertools.product(keys, VALUES):
        base = {"annotations": 'path = "**"\n', "commits": f'commit = "{head}"\nHuman-Review = "H1"\n',
                "attestations": f'path = "a.txt"\nblob = "{blob}"\nAI-Review = "A1"\n'}[table]
        lines = [l for l in base.splitlines() if not l.startswith(key + " ")]
        r.write("SIGNOFF.toml", f"version = 4\n[history]\nenabled = true\n[[{table}]]\n" + "\n".join(lines) + f"\n{key} = {value}\n")
        code, out, err = r.cli("lint")
        if code == 3 or "Traceback" in err:
            bad.append((f"[[{table}]].{key}", value, code))
print("internal errors (exit 3 or a traceback):", bad or "none")
