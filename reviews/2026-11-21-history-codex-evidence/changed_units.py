"""Compare provenance after a binary is replaced with text on a feature branch."""
import json
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory

helpers = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "2026-11-21-pull57-codex-evidence/cache_cases.py"
))
commit, new_repo, run = (helpers[name] for name in ("commit", "new_repo", "run"))


def check(tool):
    with TemporaryDirectory() as directory:
        root = Path(directory)
        new_repo(root)
        path = root / "data"
        path.write_bytes(b"\x00binary\nold line 2\nold line 3\n")
        commit(root, "Add binary", "H1")
        run(root, "git", "switch", "-qc", "feature")
        path.write_text("new line 1\nnew line 2\nnew line 3\n", encoding="utf-8")
        commit(root, "Replace with text", "H3")
        description = ("AI-Generation: G0\nHuman-Review: H3\nReviewed-by: Example Reviewer\n"
                       "AI-Review: A0\n")
        with TemporaryDirectory() as external:
            declaration = Path(external) / "description.md"
            declaration.write_text(description, encoding="utf-8")
            result = run(root, tool, "report", "--json", "--base", "main",
                         "--declare-from", str(declaration))
        file = next(f for f in json.loads(result.stdout)["files"] if f["path"] == path.name)
        return [(p["runs"], p["Human-Review"]) for p in file["parts"]]


if __name__ == "__main__":
    old = str(Path(sys.executable).with_name("aisignoff"))
    new = str(Path(sys.argv[1]).resolve())
    for tool in (old, new):
        print(run(Path.cwd(), tool, "--version").stdout.strip(), check(tool))
