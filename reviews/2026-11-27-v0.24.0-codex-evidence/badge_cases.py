"""Compare commit badges with declarations in disposable repositories."""
import json
from pathlib import Path
import runpy
import sys
import tempfile

tool, helper = (str(Path(arg).resolve()) for arg in sys.argv[1:])
helpers = runpy.run_path(helper)
commit, new_repo, run = (helpers[name] for name in ("commit", "new_repo", "run"))


def display(root, command, path):
    result = run(root, tool, *command, "--out", str(path))
    if command == ["badge", "--commits"]:
        print("commit badge stderr:", result.stderr.strip() or "(empty)")
    for file in sorted(path.glob("*review.json")):
        print(file.name, json.loads(file.read_text())["message"])


with tempfile.TemporaryDirectory() as temp:
    area = Path(temp)
    root = area / "repo"
    root.mkdir()
    new_repo(root)
    conf = root / "SIGNOFF.toml"
    conf.write_text(conf.read_text().replace("version = 4", "version = 3"))
    (root / "solver.py").write_text("print(1)\n")
    run(root, "git", "add", "-A")
    run(root, "git", "commit", "-qm", "Legacy implementation", "-m",
        "AI-Generation: G3\nAssisted-by: Claude Opus (Anthropic)\n"
        "Human-Review: H1\nReviewed-by: Example Reviewer\n"
        "AI-Review: A1\nAI-Reviewed-by: Claude Opus (Anthropic), self-check by the generating session")
    print("Version-3 self-check")
    display(root, ["badge"], area / "files")
    display(root, ["badge", "--commits"], area / "commits")

with tempfile.TemporaryDirectory() as temp:
    area = Path(temp)
    root = area / "repo"
    root.mkdir()
    new_repo(root)
    (root / "solver.py").write_text("print(1)\n")
    body = ("AI-Generation: G0\nHuman-Review: H0\nHuman-Review: H3\n"
            "Reviewed-by: Example Reviewer\nAI-Review: A0\n")
    run(root, "git", "add", "-A")
    run(root, "git", "commit", "-qm", "Conflicting human review", "-m", body)
    desc = area / "description.md"
    desc.write_text(body)
    result = run(root, tool, "lint", "--declare-from", str(desc), check=False)
    print("Conflicting H0 and H3")
    print("lint exit:", result.returncode)
    print(next(line for line in result.stdout.splitlines() if "conflicting" in line))
    display(root, ["badge", "--commits"], area / "commits")
