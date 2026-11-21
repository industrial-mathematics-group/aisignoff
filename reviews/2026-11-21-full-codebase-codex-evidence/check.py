"""CLI checks in isolated repositories. Pass the path to aisignoff as argv[1]."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

tool = str(Path(sys.argv[1]).resolve()) if len(sys.argv) > 1 else str(Path(sys.executable).with_name("aisignoff"))
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

def report(root, path, *, cache=False):
    data = json.loads(run(root, tool, "report", "--json", cache=cache).stdout)
    return next(f["Human-Review"] for f in data["files"] if f["path"] == path)

def new_repo(root):
    run(root, "git", "init", "-qb", "main")
    run(root, "git", "config", "user.name", "Example Reviewer")
    run(root, "git", "config", "user.email", "reviewer@example.invalid")
    (root / "SIGNOFF.toml").write_text(config, encoding="utf-8")

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    new_repo(root)
    run(root, "git", "config", "core.quotePath", "true")
    file = root / "données.bin"
    file.write_bytes(b"\x00first")
    commit(root, "First binary", "H1")
    print("binary before edit, cached:", report(root, file.name, cache=True))
    file.write_bytes(b"\x00second")
    commit(root, "Edit binary", "H3")
    print("binary after edit, cached:", report(root, file.name, cache=True))
    print("binary after edit, uncached:", report(root, file.name))

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    new_repo(root)
    (root / "keep.txt").write_text("Keep\n", encoding="utf-8")
    commit(root, "Base", "H1")
    (root / "empty.txt").touch()
    data = json.loads(run(root, tool, "diff", "HEAD", "--json").stdout)
    print("untracked empty file, added units:", data["total"]["added"])
    run(root, "git", "add", "empty.txt")
    data = json.loads(run(root, tool, "diff", "HEAD", "--json").stdout)
    print("staged empty file, added units:", data["total"]["added"])
    commit(root, "Add empty file", "H3")
    (root / "empty.txt").unlink()
    data = json.loads(run(root, tool, "diff", "HEAD", "--json").stdout)
    print("removed empty file, removed units:", data["total"]["removed"])

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    new_repo(root)
    link = root / "link"
    link.symlink_to("file-added-later.txt")
    commit(root, "Add a symlink", "H1")
    args = (tool, "attest", "link", "-a", "A1", "--findings", "none", "--ai-reviewed-by", "Example Reviewer")
    result = run(root, *args, "--at", "HEAD", "--to", "reviews/link-at-head.toml")
    print("symlink attest --at HEAD:", result.stdout.strip())
    result = run(root, tool, "lint", check=False)
    print("symlink lint exit:", result.returncode)
    print(next((line for line in result.stdout.splitlines() if "reviews/link-at-head.toml" in line), ""))
    result = run(root, *args, "--to", "reviews/link-current.toml", check=False)
    print("symlink attest from working tree exit:", result.returncode, result.stderr.strip())

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    new_repo(root)
    for name in ("dead", "live"):
        (root / name).write_text(name + "\n", encoding="utf-8")
    commit(root, "Add files", "H1")
    def oid(name):
        return run(root, "git", "rev-parse", "HEAD:" + name).stdout.strip()
    def table(name, header):
        return (f'\n{header}\npath = "{name}"\nblob = "{oid(name)}"\n'
                'Human-Review = "H3"\nReviewed-by = "Example Reviewer"\n')
    original = (config + table("dead", '[[ "attestations" ]]') + table("live", "[[attestations]]"))
    (root / "SIGNOFF.toml").write_text(original, encoding="utf-8")
    commit(root, "Record reviews", "H1")
    (root / "dead").unlink()
    dry = run(root, tool, "gc", "--dry-run").stdout.strip()
    print("quoted record dry-run:", dry)

    # Exercise the deletion transform in memory and use CLI report on its projected file.
    # The actual gc deletion command is unnecessary.
    from aisignoff.cli import remove_tables
    from aisignoff.config import load_text
    path = root / "SIGNOFF.toml"
    projected = remove_tables(original, "attestations", {1})
    before = load_text(original, path).attestations
    after = load_text(projected, path).attestations
    print("expected retained paths:", [a.path for a in before[1:]])
    print("projected retained paths:", [a.path for a in after])
    print("gc's values-only check accepts projection:", [a.values for a in before[1:]] == [a.values for a in after])
    print("live path before projection:", report(root, "live"))
    path.write_text(projected, encoding="utf-8")
    print("live path after projection:", report(root, "live"))
