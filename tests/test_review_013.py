"""The findings of the review of 0.13: corrections of old commits, release branches, and the
smaller notes and messages."""
import json

from aisignoff.project import Project

from test_history import G3, commit, edit_lines, git, repo, result  # noqa: F401
from test_history_precedence import D, by_line, merge
from test_history_owners import lint
from test_review_012 import levels, run

HAND = D("G0", "H2", "A0")


def test_a_correction_of_an_old_commit_counts_at_once(repo, capsys):
    """Without a snapshot, a [[commits]] entry for any commit of the history applies as soon as it lands."""
    edit_lines(repo, [2])
    commit(repo, "AI change", G3)
    initial = git(repo, "rev-list", "--max-parents=0", "HEAD")
    assert levels(repo)[0] == "G0 H2 A0"
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{initial}"\nAI-Generation = "G1"\nHuman-Review = "H2"\n'
                'AI-Review = "A1"\nAssisted-by = "Model A"\nReviewed-by = "Jane"\nAI-Reviewed-by = "Model A"\n')
    commit(repo, "the first commit was AI-assisted after all", HAND)
    after = levels(repo)
    assert after[0] == "G1 H2 A1" and after[1] == "G3 H1 A1"
    assert lint(repo, capsys)[0] == 0


def test_landed_on_a_release_branch_resolves_mains_lines_as_on_main(repo, capsys):
    git(repo, "checkout", "-q", "-b", "release/1.x")
    git(repo, "checkout", "-q", "main")
    edit_lines(repo, [2])
    commit(repo, "AI change (#3)", G3)
    git(repo, "checkout", "-q", "release/1.x")
    edit_lines(repo, [9], text="fix")
    commit(repo, "backport", HAND)
    git(repo, "merge", "-q", "--no-ff", "main", "-m", "sync with main")  # declares nothing
    project = Project(repo)
    project.landed = True
    lines = by_line(next(r for r in project.results() if r.path == "solver.py"))
    assert lines[2].declaration.short() == "G3 H1 A1"  # PR #3's, not the sync merge's
    assert lines[9].declaration.short() == "G0 H2 A0"
    assert lines[1].declaration.short() == "G0 H2 A0"
    assert lint(repo, capsys, "--landed", "--strict")[0] == 0


def test_a_partial_commits_entry_on_an_undeclared_commit_says_how_to_raise_a_review(repo, capsys):
    edit_lines(repo, [2])
    sha = commit(repo, "undeclared")
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{sha}"\nHuman-Review = "H3"\nReviewed-by = "Rita"\n')
    commit(repo, "a review", HAND)
    r, _ = result(repo)
    errors = " ".join(by_line(r)[2].errors)
    assert "the [[commits]] entry for commit" in errors and "aisignoff attest" in errors


# ================================================================== the review of 0.14
def test_a_personal_ignore_revs_file_doesnt_change_the_levels(repo, capsys, monkeypatch, tmp_path_factory):
    edit_lines(repo, [2], text="styled")
    style = commit(repo, "style", G3)
    other = tmp_path_factory.mktemp("home")
    (other / "revs").write_text(style + "\n")
    (other / "gitconfig").write_text(f"[blame]\n\tignoreRevsFile = {other / 'revs'}\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(other / "gitconfig"))
    assert levels(repo)[1] == "G3 H1 A1"
    monkeypatch.delenv("GIT_CONFIG_GLOBAL")
    assert levels(repo)[1] == "G3 H1 A1"
    assert lint(repo, capsys)[0] == 0


def test_the_json_keys_of_format_1(repo, capsys):
    """What docs/report.md lists: a key removed or renamed raises "format"."""
    edit_lines(repo, [2])
    commit(repo, "AI change", G3)
    code, out = run(repo, capsys, "report", "--json")
    data = json.loads(out)
    assert set(data) == {"format", "aisignoff", "files"} and data["format"] == 1
    f = next(f for f in data["files"] if f["path"] == "solver.py")
    levels = {"AI-Generation", "Human-Review", "AI-Review", "Assisted-by", "Reviewed-by", "AI-Reviewed-by", "source"}
    assert set(f) == levels | {"path", "Findings", "errors", "parts"}
    assert set(f["parts"][0]) == levels | {"Findings", "errors", "lines", "runs", "kinds", "advisory"}
    data = json.loads(run(repo, capsys, "report", "--tree", "--json")[1])
    assert {"format", "aisignoff", "name", "path", "type", "files", "lines", "errors", "counts", "children"} <= set(data)
    assert set(data["counts"]["AI-Generation"]) == {"files", "lines"}
    data = json.loads(run(repo, capsys, "diff", "HEAD~1", "--json")[1])
    assert {"format", "aisignoff", "base", "base_name", "base_tip", "files", "history", "rows", "total", "attested",
            "before", "after", "problems", "notes", "note"} <= set(data)
    assert set(data["total"]) == {"name", "added", "removed", "levels_added", "levels_removed"}


def test_a_pull_requests_run_needs_the_default_branch(tmp_path, capsys, monkeypatch):
    git(tmp_path, "init", "-q", "-b", "develop")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "T")
    (tmp_path / "SIGNOFF.toml").write_text('version = 4\n\n[history]\nenabled = true\n\n[[annotations]]\npath = "**"\n'
                                           'AI-Generation = "G0"\nHuman-Review = "H2"\nAI-Review = "A0"\nReviewed-by = "J"\n')
    (tmp_path / "a.py").write_text("1\n")
    commit(tmp_path, "one", HAND)
    git(tmp_path, "checkout", "-q", "-b", "pr")
    (tmp_path / "a.py").write_text("2\n")
    commit(tmp_path, "agent", G3)
    body = tmp_path.parent / "body.md"
    body.write_text("Just a description.\n")
    code, out = lint(tmp_path, capsys, "--declare-from", str(body), "--base", "HEAD^1")
    assert code == 1 and "there is no default branch here" in out
    # GitHub's event names it
    event = tmp_path.parent / "event.json"
    event.write_text(json.dumps({"repository": {"default_branch": "develop"}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    code, out = lint(tmp_path, capsys, "--declare-from", str(body), "--base", "HEAD^1")
    assert code == 1 and "declares no Human-Review" in out and "no default branch" not in out


def test_a_branch_commit_that_says_only_its_generation_takes_the_models_of_the_pull_request(repo, capsys):
    git(repo, "checkout", "-q", "-b", "pr")
    edit_lines(repo, [2])
    commit(repo, "agent", "AI-Generation: G3")
    merge(repo, "pr", "Merge pull request #5\n\n" + D("G1", "H2", "A1"))
    lines = by_line(result(repo)[0])
    assert lines[2].declaration.short() == "G3 H2 A1" and lines[2].declaration.assisted_by == ("M",)
    assert lint(repo, capsys)[0] == 0
    # a description that names no model: the message says which commit
    git(repo, "checkout", "-q", "-b", "pr2")
    edit_lines(repo, [3])
    commit(repo, "agent 2", "AI-Generation: G3")
    merge(repo, "pr2", "Merge pull request #6\n\n" + D("G0", "H2", "A0"))
    code, out = lint(repo, capsys)
    assert code == 1 and "agent 2" in out and "but no Assisted-by" in out


def test_a_declared_commit_in_the_ignore_revs_file_is_a_warning(repo, capsys):
    edit_lines(repo, [2])
    sha = commit(repo, "AI change (#4)", G3)
    (repo / ".git-blame-ignore-revs").write_text(sha + "\n")
    commit(repo, "ignore it", HAND)
    code, out = lint(repo, capsys, "--strict")
    assert code == 1 and ".git-blame-ignore-revs lists commit" in out and "declares levels" in out


def test_a_pull_request_merged_into_one_that_says_less_ai_is_a_warning(repo, capsys):
    git(repo, "checkout", "-q", "-b", "a")
    edit_lines(repo, [2], text="a")
    commit(repo, "a")
    git(repo, "checkout", "-q", "-b", "b")
    edit_lines(repo, [3], text="b")
    commit(repo, "b")
    git(repo, "checkout", "-q", "a")
    git(repo, "merge", "-q", "--no-ff", "b", "-m", "Merge pull request #2 (b into a)\n\n" + D("G3", "H1", "A1"))
    merge(repo, "a", "Merge pull request #1\n\n" + D("G1", "H2", "A1"))
    code, out = lint(repo, capsys, "--strict")
    assert code == 1 and "declares G1, but" in out and "declares G3" in out


