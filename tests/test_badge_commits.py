"""badge --commits: the declarations of the merged changes, read from the first-parent history."""
import json

from aisignoff.cli import main

from test_history import commit, git
from test_aisignoff import write

TEMPLATE = """## AI declaration

- [ ] **G0** Human-written
- [x] **G2** AI-generated
- [x] **Claude Opus 5.5** (Anthropic)
- [ ] **H0** I checked that it is plausible
- [x] **H1** I ran the tests
- [ ] **H2** I reviewed every line
- [ ] **A1** A context-free check. Model:
"""


def badges(root, tmp_path, *extra):
    out = tmp_path / "out"
    assert main(["--root", str(root), "badge", "--commits", "--out", str(out), *extra]) == 0
    return {f: json.loads((out / f).read_text())["message"]
            for f in ("ai-generation.json", "ai-human-review.json", "ai-review.json")}


def init(root):
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "T")
    git(root, "config", "commit.gpgsign", "false")


def test_counts_boxes_lines_and_legacy_without_signoff_toml(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    init(root)
    write(root, "a.txt", "1\n")
    commit(root, "before the policy")  # not counted
    write(root, "a.txt", "2\n")
    commit(root, "Merge pull request #1", TEMPLATE)
    write(root, "a.txt", "3\n")
    # "Key: value" lines, also when GitHub adds a paragraph after them
    commit(root, "direct", "AI-Generation: G0\nHuman-Review: H2\nAI-Review: A-\n\nCo-authored-by: X <x@example.com>")
    write(root, "a.txt", "4\n")
    commit(root, "first policy", "AI-Generation: G0\nAI-Verification: V0")
    found = badges(root, tmp_path)
    assert found["ai-generation.json"] == "G0 67% · G2 33%"
    assert found["ai-human-review.json"] == "H1 33% · H2 67%"
    assert found["ai-review.json"] == "A0 100%"


def test_highest_ticked_human_review_counts(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    init(root)
    write(root, "a.txt", "1\n")
    # H0 left unticked under a ticked H1: the highest ticked box counts, as in the check before the merge
    commit(root, "Merge pull request #1", TEMPLATE)
    assert badges(root, tmp_path)["ai-human-review.json"] == "H1 100%"


def test_no_declarations_and_summary(tmp_path, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    init(root)
    write(root, "a.txt", "1\n")
    commit(root, "by hand")
    found = badges(root, tmp_path, "--markdown")
    assert set(found.values()) == {"no declarations yet"}
    assert "0 of 1 commits on the default branch are declared." in capsys.readouterr().out


def test_old_template_a1_box_is_the_self_check(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    init(root)
    write(root, "a.txt", "1\n")
    old = TEMPLATE.replace("- [ ] **A1** A context-free check. Model:",
                           "- [x] **A1** The AI checked its own work (self-check)")
    commit(root, "Merge pull request #1", old)
    assert badges(root, tmp_path)["ai-review.json"] == "A0 100%"


def test_markdown_needs_commits(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "badge", "--markdown"]) == 2
