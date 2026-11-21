"""Check filename boundaries and cache reuse across versions in disposable repositories."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import os
import subprocess

environment = {**os.environ, "AISIGNOFF_NO_CACHE": "1", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
config = """version = 4
[history]
enabled = true

[[annotations]]
path = "**"
AI-Generation = "G0"
Human-Review = "H1"
Reviewed-by = "Example Reviewer"
AI-Review = "A0"
"""

def run(root, *args, cache=False, check=True):
    return subprocess.run(args, cwd=root, env={**environment, "AISIGNOFF_NO_CACHE": "0" if cache else "1"},
                          check=check, text=True, capture_output=True)

def commit(root, title, review):
    run(root, "git", "add", "-A")
    run(root, "git", "commit", "-qm", title, "-m",
        f"AI-Generation: G0\nHuman-Review: {review}\nReviewed-by: Example Reviewer\nAI-Review: A0")

def new_repo(root):
    run(root, "git", "init", "-qb", "main")
    run(root, "git", "config", "user.name", "Example Reviewer")
    run(root, "git", "config", "user.email", "reviewer@example.invalid")
    (root / "SIGNOFF.toml").write_text(config, encoding="utf-8")


def report(root, tool, path, *, cache):
    result = run(root, tool, "report", "--json", cache=cache)
    return next(item["Human-Review"] for item in json.loads(result.stdout)["files"]
                if item["path"] == path)


def after_edit(first_tool, second_tool, name, *, prime_after_edit):
    with TemporaryDirectory() as directory:
        root = Path(directory)
        new_repo(root)
        (root / name).write_bytes(b"\x00first")
        commit(root, "Add binary", "H1")
        print("before edit:", report(root, first_tool, name, cache=True))
        (root / name).write_bytes(b"\x00second")
        commit(root, "Edit binary", "H3")
        if prime_after_edit:
            print("after edit in v0.19.1:", report(root, first_tool, name, cache=True))
        print("after edit, cache enabled:", report(root, second_tool, name, cache=True))
        print("after edit, cache disabled:", report(root, second_tool, name, cache=False))


if __name__ == "__main__":
    old = str(Path(sys.executable).with_name("aisignoff"))
    new = str(Path(sys.argv[1]).resolve())
    for label, first, second, name, prime in (
        ("v0.19.2 cold start", new, new, "données.bin", False),
        ("v0.19.1 cache reused by v0.19.2", old, new, "données.bin", True),
        ("leading newline in v0.19.1", old, old, "\nreport.bin", False),
        ("leading newline in v0.19.2", new, new, "\nreport.bin", False),
    ):
        print(label)
        after_edit(first, second, name, prime_after_edit=prime)
