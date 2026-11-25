"""Compare whole-unit counts and unknown-key cleanup on two aisignoff releases."""
import json
from pathlib import Path
import runpy
import sys
import tempfile

helpers = runpy.run_path(str(Path(sys.argv[2]).resolve()))
commit, new_repo, run = (helpers[name] for name in ("commit", "new_repo", "run"))


def compare(tool, prepare, change):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        new_repo(root)
        path = root / "data"
        prepare(path)
        commit(root, "Original", "H1")
        run(root, "git", "switch", "-qc", "feature")
        change(path)
        commit(root, "Edit", "H3")
        data = json.loads(run(root, tool, "diff", "main", "--files", "--json").stdout)
        totals = data["total"]
        return totals["added"], totals["removed"]


def replace_link(path):
    path.unlink()
    path.symlink_to("other\nsecond\nthird")


def initial_binary(path):
    path.write_bytes(b"\x00first\nunchanged\n")


def move_nul_past_probe(path):
    path.write_bytes((b"a" * 17000) + b"\n" + path.read_bytes())


def remove_unknown_key(tool):
    with tempfile.TemporaryDirectory() as directory:
        area = Path(directory)
        root = area / "repo"
        root.mkdir()
        new_repo(root)
        signoff = root / "SIGNOFF.toml"
        original = signoff.read_text()
        signoff.write_text(original.replace("version = 4", 'version = 4\nnotes = "legacy"'))
        (root / "data").write_text("one\n")
        commit(root, "Base with a legacy key", "H1")
        run(root, "git", "switch", "-qc", "feature")
        signoff.write_text(original)
        commit(root, "Remove the legacy key", "H1")
        description = area / "description.md"
        description.write_text("AI-Generation: G0\nHuman-Review: H1\n"
                               "Reviewed-by: Example Reviewer\nAI-Review: A0\n")
        plain = run(root, tool, "lint", check=False)
        preview = run(root, tool, "lint", "--base", "main", "--declare-from",
                      str(description), check=False)
        print(f"Remove unknown base key: plain={plain.returncode}, with base={preview.returncode}")
        print(preview.stderr.strip())


if __name__ == "__main__":
    for tool in (str(Path(sys.executable).with_name("aisignoff")), str(Path(sys.argv[1]).resolve())):
        print(run(Path.cwd(), tool, "--version").stdout.strip())
        print("Changed multiline link target (+, -):",
              compare(tool, lambda p: p.symlink_to("first\nold\nsecond"), replace_link))
        print("Insert one line before the binary region (+, -):",
              compare(tool, initial_binary, move_nul_past_probe))
        remove_unknown_key(tool)
