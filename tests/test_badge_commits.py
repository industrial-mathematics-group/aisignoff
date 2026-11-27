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


# ------------------------------------------------------------------ 0.25.0: the review of 0.24.0
SELF_CHECK = ("AI-Generation: G3\nAssisted-by: Claude Opus (Anthropic)\nHuman-Review: H1\nReviewed-by: R\n"
              "AI-Review: A1\nAI-Reviewed-by: Claude Opus (Anthropic), self-check by the generating session")


def repo_with(tmp_path, toml=None):
    root = tmp_path / "repo"
    root.mkdir()
    init(root)
    if toml is not None:
        write(root, "SIGNOFF.toml", toml)
    write(root, "a.txt", "1\n")
    return root


def test_a_version_3_repository_counts_on_its_scale(tmp_path):
    """version = 3: an A1 trailer was the generating session's self-check, today's A0, as the file badge says."""
    root = repo_with(tmp_path, "version = 3\n")
    commit(root, "legacy", SELF_CHECK.replace(", self-check by the generating session", ""))
    write(root, "a.txt", "2\n")
    commit(root, "a new session, on the old scale", SELF_CHECK.replace("AI-Review: A1", "AI-Review: A2")
           .replace("self-check by the generating session", "new session"))
    assert badges(root, tmp_path)["ai-review.json"] == "A0 50% · A1 50%"


def test_a_self_check_counts_as_no_review(tmp_path):
    """Without SIGNOFF.toml (today's scale), an A1 whose reviewer is only a self-check is A0 by definition."""
    root = repo_with(tmp_path)
    commit(root, "self-check", SELF_CHECK)
    assert badges(root, tmp_path)["ai-review.json"] == "A0 100%"


def test_a_different_model_level_by_the_writing_model_is_a1(tmp_path):
    root = repo_with(tmp_path)
    commit(root, "same model", SELF_CHECK.replace("AI-Review: A1", "AI-Review: A2")
           .replace("self-check by the generating session", "new session, reviews/r.md"))
    assert badges(root, tmp_path)["ai-review.json"] == "A1 100%"


def test_conflicting_levels_are_unknown_and_reported(tmp_path, capsys):
    root = repo_with(tmp_path)
    commit(root, "conflict", "AI-Generation: G0\nHuman-Review: H0\nHuman-Review: H3\nReviewed-by: R\nAI-Review: A0\n")
    found = badges(root, tmp_path, "--markdown")
    assert found["ai-human-review.json"] == "unknown 100%"
    assert found["ai-generation.json"] == "G0 100%" and found["ai-review.json"] == "A0 100%"  # the other axes stand
    out = capsys.readouterr()
    assert "conflicting Human-Review" in out.err and "conflicting levels" in out.out


def test_commits_entries_of_signoff_toml_correct_the_counts(tmp_path):
    root = repo_with(tmp_path, "version = 4\n")
    sha = commit(root, "undeclared")
    write(root, "a.txt", "2\n")
    commit(root, "declared", "AI-Generation: G3\nAssisted-by: M (V)\nHuman-Review: TODO\nAI-Review: A0\n")
    with open(root / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{sha}"\nAI-Generation = "G0"\nHuman-Review = "H2"\nAI-Review = "A0"\n'
                'Reviewed-by = "R"\n')
    found = badges(root, tmp_path)
    assert found["ai-generation.json"] == "G0 50% · G3 50%"
    assert found["ai-human-review.json"] == "H2 50% · unknown 50%"
