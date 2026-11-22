"""Check the two binary-classification boundaries through report and diff."""
import json
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory

helpers = runpy.run_path(str(Path(sys.argv[2]).resolve()))
commit, new_repo, run = (helpers[name] for name in ("commit", "new_repo", "run"))


def compare(tool, before, after, attributes):
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        new_repo(root)
        if attributes:
            (root / ".gitattributes").write_text("data -diff\n", encoding="utf-8")
        path = root / "data"
        path.write_bytes(before)
        commit(root, "Initial file", "H1")
        run(root, "git", "switch", "-qc", "feature")
        path.write_bytes(after)
        commit(root, "Edit file", "H3")
        description = ("AI-Generation: G0\nHuman-Review: H3\n"
                       "Reviewed-by: Example Reviewer\nAI-Review: A0\n")
        with TemporaryDirectory() as external:
            declaration = Path(external) / "description.md"
            declaration.write_text(description, encoding="utf-8")
            result = run(root, tool, "report", "--json", "--base", "main",
                         "--declare-from", str(declaration))
        entry = next(item for item in json.loads(result.stdout)["files"] if item["path"] == "data")
        parts = [(p["runs"], p["Human-Review"]) for p in entry["parts"]]
        raw = run(root, "git", "diff", "--numstat", "main", "--", "data").stdout.strip()
        totals = json.loads(run(root, tool, "diff", "main", "--json").stdout)["total"]
        return parts, raw, (totals["added"], totals["removed"])


def check(tool):
    binary = (b"x" * 10000) + b"\x00\n"
    tail = b"same line 2\nsame line 3\n"
    print("NUL byte at 10000, without attributes:",
          compare(tool, binary + tail, b"new line 1\n" + tail, False))
    text_by_byte_rule = ("é" * 9000).encode() + b"\x00\n"
    print("NUL byte at 18000, after 9000 UTF-8 characters, with -diff:",
          compare(tool, text_by_byte_rule + tail, b"new line 1\n" + tail, True))


if __name__ == "__main__":
    for tool in (str(Path(sys.executable).with_name("aisignoff")), str(Path(sys.argv[1]).resolve())):
        print(run(Path.cwd(), tool, "--version").stdout.strip())
        check(tool)
