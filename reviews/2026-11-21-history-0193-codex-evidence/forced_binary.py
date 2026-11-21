"""Compare provenance of unchanged text lines when Git is configured to omit the patch."""
import json
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory

helpers = runpy.run_path(str(Path(sys.argv[2]).resolve()))
commit, new_repo, run = (helpers[name] for name in ("commit", "new_repo", "run"))


def check(tool, suppress_patch):
    with TemporaryDirectory() as directory:
        root = Path(directory)
        new_repo(root)
        if suppress_patch:
            (root / ".gitattributes").write_text("data.txt -diff\n", encoding="utf-8")
        path = root / "data.txt"
        path.write_text("old line 1\nsame line 2\nsame line 3\n", encoding="utf-8")
        commit(root, "Add text", "H1")
        run(root, "git", "switch", "-qc", "feature")
        path.write_text("new line 1\nsame line 2\nsame line 3\n", encoding="utf-8")
        commit(root, "Edit line one", "H3")
        description = ("AI-Generation: G0\nHuman-Review: H3\n"
                       "Reviewed-by: Example Reviewer\nAI-Review: A0\n")
        with TemporaryDirectory() as external:
            declaration = Path(external) / "description.md"
            declaration.write_text(description, encoding="utf-8")
            result = run(root, tool, "report", "--json", "--base", "main",
                         "--declare-from", str(declaration))
        file = next(f for f in json.loads(result.stdout)["files"] if f["path"] == path.name)
        totals = json.loads(run(root, tool, "diff", "main", "--json").stdout)["total"]
        runs = [(p["runs"], p["Human-Review"]) for p in file["parts"]]
        return runs, (totals["added"], totals["removed"])


if __name__ == "__main__":
    old = str(Path(sys.executable).with_name("aisignoff"))
    new = str(Path(sys.argv[1]).resolve())
    for tool in (old, new):
        version = run(Path.cwd(), tool, "--version").stdout.strip()
        for suppress_patch in (False, True):
            label = "-diff" if suppress_patch else "normal text"
            print(version, label, check(tool, suppress_patch))
