"""One owner per line on the default branch, lines that haven't landed, and snapshots
(aisignoff freeze)."""
import json

import pytest

from aisignoff.cli import main
from aisignoff.config import ConfigError, load
from aisignoff.project import Project

from test_aisignoff import write
from test_history import G3, commit, edit_lines, git, repo, result, shares  # noqa: F401
from test_history_edges import TEMPLATE, nested  # noqa: F401
from test_history_precedence import D, by_line, merge

AGENT = "AI-Generation: G3\nAssisted-by: M\nAI-Review: A1\nAI-Reviewed-by: M"  # the human review comes later


def lint(repo, capsys, *args):
    capsys.readouterr()
    code = main(["--root", str(repo), "lint", *args])
    return code, capsys.readouterr().out


def setting(repo, text):
    toml = (repo / "SIGNOFF.toml").read_text().replace("enabled = true", "enabled = true\n" + text)
    (repo / "SIGNOFF.toml").write_text(toml)


# ------------------------------------------------------------------ lines that haven't landed
def test_a_pull_request_into_another_pull_request_fails_nothing(repo, capsys):
    """The CI run of B, stacked on A: A's agent commits leave the human review to A's pull request."""
    git(repo, "checkout", "-q", "-b", "a")
    edit_lines(repo, [2])
    commit(repo, "A's agent", AGENT)
    git(repo, "checkout", "-q", "-b", "b")
    edit_lines(repo, [3])
    commit(repo, "B's agent", AGENT)
    git(repo, "checkout", "-q", "--detach", "a")
    git(repo, "merge", "-q", "--no-ff", "b", "-m", "the merge preview of B into A")
    code, out = lint(repo, capsys, "--strict")
    assert code == 0 and "2 line(s) that aren't on the default branch yet" in out
    r, _ = result(repo)
    assert by_line(r)[2].declaration.short() == "G3 -- A1" and by_line(r)[2].advisory and r.errors == []
    # B's description declares nothing for main: it is A's pull request that lands the lines there
    body = write(repo.parent, "b.md", D("G3", "H3", "A2"))
    code, out = lint(repo, capsys, "--declare-from", str(body), "--base", "a")
    assert code == 0 and "doesn't go into the default branch" in out
    assert by_line(result(repo)[0])[3].declaration.short() == "G3 -- A1"
    capsys.readouterr()
    assert main(["--root", str(repo), "diff", "a", "--json", "--declare-from", str(body)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total"]["added"] == 1 and data["total"]["levels_added"]["Human-Review"] == {"undeclared": 1}
    assert any("doesn't go into the default branch" in n for n in data["notes"])


def test_lint_checks_the_description_of_a_pull_request_into_the_default_branch(repo, capsys):
    git(repo, "checkout", "-q", "-b", "pr")
    edit_lines(repo, [2])
    commit(repo, "agent", AGENT)
    edit_lines(repo, [3], text="hand")
    commit(repo, "by hand", "AI-Generation: G0\nHuman-Review: H3\nReviewed-by: Bob")
    git(repo, "checkout", "-q", "--detach", "main")
    git(repo, "merge", "-q", "--no-ff", "pr", "-m", "preview")
    body = write(repo.parent, "body.md", TEMPLATE.format(a2="x", model="GPT Sol (OpenAI), fresh session"))
    code, out = lint(repo, capsys, "--declare-from", str(body), "--author", "jane", "--base", "HEAD^1")
    assert code == 0 and "All files are declared" in out
    assert lint(repo, capsys, "--declare-from", str(body))[0] == 1  # the template names nobody for the review
    body.write_text(TEMPLATE.replace("[x]", "[ ]").format(a2=" ", model=""))  # the template, not filled in
    code, out = lint(repo, capsys, "--declare-from", str(body), "--author", "jane")
    assert code == 1 and "Human-Review is still TODO" in out
    body.write_text("Just a description.\n")  # nothing declared at all
    code, out = lint(repo, capsys, "--declare-from", str(body))
    assert code == 1 and "declares no Human-Review (required for a pull request into the default branch)" in out
    assert lint(repo, capsys, "--base", "main")[0] == 2 and lint(repo, capsys, "--author", "x")[0] == 2


def test_an_unfilled_template_or_an_empty_level_line_is_not_a_fallback(repo):
    edit_lines(repo, [2])
    commit(repo, "Merged with the template untouched (#3)", TEMPLATE.replace("[x]", "[ ]").format(a2=" ", model=""))
    edit_lines(repo, [3])
    commit(repo, "Level lines left empty", "AI-Generation:\nHuman-Review:\nAI-Review: A0")
    lines = by_line(result(repo)[0])
    for n in (2, 3):
        assert lines[n].declaration.short() == "TODO TODO A0" and any("TODO" in e for e in lines[n].errors)


def test_undeclared_error_requires_every_commit_of_the_default_branch_to_declare(repo, capsys):
    setting(repo, 'undeclared = "error"')
    commit(repo, "config", D("G0", "H2", "A0"))
    r, _ = result(repo)
    assert any("initial, by hand" in e and 'required by [history] undeclared = "error"' in e for e in r.errors)
    git(repo, "checkout", "-q", "-b", "pr")  # not on a branch, though: its pull request will declare it
    edit_lines(repo, [5])
    commit(repo, "quick fix")
    assert by_line(result(repo)[0])[5].errors == []
    (repo / "SIGNOFF.toml").write_text((repo / "SIGNOFF.toml").read_text().replace('"error"', '"warn"'))
    with pytest.raises(ConfigError, match="'undeclared' must be one of"):
        load(repo)


def test_an_undeclared_revert_is_reported(repo, capsys):
    edit_lines(repo, [2])
    commit(repo, "AI change", G3)
    edit_lines(repo, [2], text="worse")
    bad = commit(repo, "a change to revert", D("G0", "H3", "A0"))
    git(repo, "revert", "--no-edit", bad)
    r, project = result(repo)
    assert by_line(r)[2].declaration.short() == "G0 H2 A0"  # the file-level declaration, not G3 H1 A1
    assert len(project.history_warnings) == 1 and "reverts" in project.history_warnings[0]
    assert lint(repo, capsys)[0] == 0 and lint(repo, capsys, "--strict")[0] == 1
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{git(repo, "rev-parse", "HEAD")}"\nAI-Generation = "G3"\n'
                'Assisted-by = "Model A"\nHuman-Review = "H1"\nReviewed-by = "Jane"\nAI-Review = "A1"\n'
                'AI-Reviewed-by = "Model A"\n')
    r, project = result(repo)
    assert by_line(r)[2].declaration.short() == "G3 H1 A1" and project.history_warnings == []


def test_report_json_says_where_each_level_comes_from(repo, capsys):
    edit_lines(repo, [2])
    commit(repo, "AI change", G3)
    capsys.readouterr()
    assert main(["--root", str(repo), "report", "--json"]) == 0
    parts = next(f for f in json.loads(capsys.readouterr().out)["files"] if f["path"] == "solver.py")["parts"]
    assert parts[0]["kinds"] == {"AI-Generation": "file", "Human-Review": "file", "AI-Review": "file"}
    assert parts[1]["kinds"]["Human-Review"] == "commit" and parts[1]["advisory"] is False


def test_a_squashed_pull_request_whose_commits_live_on_in_the_next_one(repo):
    """A is squashed into main; B, stacked on it, still has A's commit, merges main and lands."""
    git(repo, "checkout", "-q", "-b", "a")
    edit_lines(repo, [2])
    commit(repo, "A", D("G3", "H3", "A2"))  # what the commit claims is gone with the squash
    git(repo, "checkout", "-q", "-b", "b")
    edit_lines(repo, [6], text="hand")
    commit(repo, "B", "AI-Generation: G0")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "a")
    commit(repo, "A (#1)", D("G3", "H1", "A1"))
    git(repo, "checkout", "-q", "b")
    git(repo, "merge", "-q", "--no-ff", "main", "-m", "Merge branch 'main' into b")
    r, _ = result(repo)
    lines = by_line(r)
    assert lines[2].declaration.short() == "G3 H1 A1" and not lines[2].advisory  # main's line, as on main
    assert lines[6].declaration.short() == "G0 -- --" and lines[6].advisory and r.errors == []
    merge(repo, "b", "Merge B\n\n" + D("G3", "H2", "A2"))
    lines = by_line(result(repo)[0])
    assert [lines[n].declaration.short() for n in (1, 2, 6)] == ["G0 H2 A0", "G3 H1 A1", "G0 H2 A2"]


def test_renamed_binary_empty_and_new_files_of_a_change(repo, capsys):
    write(repo, "bin.dat", "a\0b")
    write(repo, "empty.txt", "")
    commit(repo, "units", "AI-Generation: G0\nHuman-Review: H3\nReviewed-by: J\nAI-Review: A0")
    git(repo, "checkout", "-q", "-b", "feature")
    git(repo, "mv", "solver.py", "moved.py")
    edit_lines(repo, [5], path="moved.py")
    commit(repo, "rename and change", G3)
    write(repo, "bin.dat", "a\0c")
    commit(repo, "binary", G3)
    write(repo, "new.py", "x\ny\n")  # not committed

    def levels(path):
        r, _ = result(repo, path)
        return [by_line(r)[n].declaration.short() for n in sorted(by_line(r))]

    assert levels("moved.py") == ["G0 H2 A0"] * 4 + ["G3 H1 A1"] + ["G0 H2 A0"] * 5
    assert levels("bin.dat") == ["G3 H1 A1"] and levels("empty.txt") == ["G0 H3 A0"]
    assert levels("new.py") == ["G0 H2 A0"] * 2
    body = write(repo.parent, "body.md", D("G2", "H2", "A2"))
    capsys.readouterr()
    assert main(["--root", str(repo), "diff", "main", "--json", "--declare-from", str(body)]) == 0
    total = json.loads(capsys.readouterr().out)["total"]
    # the commits of the branch say G3 for what they wrote; the new file isn't committed
    assert total["added"] == 4 and total["levels_added"]["AI-Generation"] == {"G2": 2, "G3": 2}


def test_without_a_default_branch_everything_has_landed(tmp_path, capsys):
    git(tmp_path, "init", "-q", "-b", "trunk")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "T")
    write(tmp_path, "SIGNOFF.toml", 'version = 3\n\n[history]\nenabled = true\n\n[[annotations]]\npath = "**"\n'
          'AI-Generation = "G0"\nHuman-Review = "H2"\nAI-Review = "A0"\nReviewed-by = "J"\n')
    write(tmp_path, "a.py", "1\n")
    assert lint(tmp_path, capsys)[0] == 0  # no commit yet
    commit(tmp_path, "one", "AI-Generation: G3\nAssisted-by: M")
    code, out = lint(tmp_path, capsys)
    assert code == 1 and "declares levels, but no Human-Review" in out
    assert freeze(tmp_path, capsys)[0] == 2


# ------------------------------------------------------------------ snapshots
def freeze(repo, capsys):
    capsys.readouterr()
    code = main(["--root", str(repo), "freeze"])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


@pytest.fixture
def frozen(repo, capsys):
    """Lines 2-3 by an agent, line 4 by hand inside a pull request, an attestation: then frozen."""
    edit_lines(repo, [2, 3])
    commit(repo, "AI change", G3)
    git(repo, "checkout", "-q", "-b", "pr")
    edit_lines(repo, [4], text="hand")
    commit(repo, "by hand", "AI-Generation: G0")
    merge(repo, "pr", "Merge pr\n\n" + D("G3", "H2", "A2"))
    assert freeze(repo, capsys)[0] == 0
    commit(repo, "freeze")
    return repo


def test_freeze_records_the_levels_and_they_stay(frozen, capsys):
    repo = frozen
    before = shares(result(repo)[0])
    assert before == {"G0 H2 A0": 7, "G3 H1 A1": 2, "G0 H2 A2": 1}
    snapshot = json.loads((repo / "SIGNOFF.snapshot.json").read_text())
    assert snapshot["commit"] == git(repo, "rev-parse", "HEAD~1") and set(snapshot["files"]) == {"solver.py"}
    assert result(repo)[0].parts[0].kinds == ("frozen", "frozen", "frozen")
    # what the history says about those lines no longer matters: not the file-level declaration,
    # not a correction of a commit
    toml = (repo / "SIGNOFF.toml").read_text().replace('Human-Review = "H2"', 'Human-Review = "H0"')
    (repo / "SIGNOFF.toml").write_text(toml + f'\n[[commits]]\ncommit = "{git(repo, "rev-parse", "HEAD~1")}"\n'
                                       'Human-Review = "H0"\nReviewed-by = "X"\n')
    commit(repo, "other rules", D("G0", "H2", "A0"))
    r, project = result(repo)
    assert shares(r) == before and project.history_problems == [] and project.history_warnings == []
    # lines changed after it are declared by the commits that land them
    edit_lines(repo, [3, 9], text="newer")
    commit(repo, "new AI change", D("G3", "H3", "A2"))
    edit_lines(repo, [10])
    commit(repo, "quick fix, undeclared")
    assert shares(result(repo)[0]) == {"G0 H2 A0": 5, "G3 H1 A1": 1, "G0 H2 A2": 1, "G3 H3 A2": 2, "G0 H0 A0": 1}
    assert lint(repo, capsys)[0] == 0


def test_a_file_that_is_as_in_the_snapshot_again_has_its_levels(frozen, capsys):
    repo = frozen
    edit_lines(repo, [2], text="worse")
    bad = commit(repo, "a change to revert", D("G0", "H3", "A0"))
    git(repo, "revert", "--no-edit", bad)
    r, project = result(repo)
    assert by_line(r)[2].declaration.short() == "G3 H1 A1" and project.history_warnings == []


def test_frozen_lines_follow_a_rename_and_an_attestation_still_raises_them(frozen, capsys):
    repo = frozen
    git(repo, "mv", "solver.py", "moved.py")
    lines = (repo / "moved.py").read_text().splitlines()
    (repo / "moved.py").write_text("\n".join(["a new first line", *lines]) + "\n")
    commit(repo, "rename and change", D("G0", "H3", "A0"))
    r, _ = result(repo, "moved.py")
    assert [by_line(r)[n].declaration.short() for n in (1, 2, 3, 5)] == ["G0 H3 A0", "G0 H2 A0", "G3 H1 A1", "G0 H2 A2"]
    assert main(["--root", str(repo), "attest", str(repo / "moved.py"), "-H", "H3", "--reviewed-by", "Rita"]) == 0
    commit(repo, "attest", D("G0", "H3", "A0"))
    edit_lines(repo, [11], path="moved.py")
    commit(repo, "a later change", D("G3", "H1", "A1"))  # the attestation stays with the content it checked
    r, project = result(repo, "moved.py")
    assert [by_line(r)[n].declaration.short() for n in (2, 3, 5, 11)] == ["G0 H3 A0", "G3 H3 A1", "G0 H3 A2", "G3 H1 A1"]
    assert project.history_problems == []


def test_a_branch_from_before_the_snapshot_that_merged_main(frozen, capsys):
    repo = frozen
    git(repo, "checkout", "-q", "-b", "old", "HEAD~3")  # before "Merge pr" and the snapshot
    edit_lines(repo, [8])
    commit(repo, "agent on an old branch", AGENT)
    assert not (repo / "SIGNOFF.snapshot.json").exists()
    git(repo, "merge", "-q", "--no-ff", "main", "-m", "Merge branch 'main' into old")  # GitHub's "Update branch"
    r, project = result(repo)
    assert shares(r) == {"G0 H2 A0": 6, "G3 H1 A1": 2, "G0 H2 A2": 1, "G3 -- A1": 1}
    assert r.errors == [] and project.history_problems == []
    capsys.readouterr()
    assert main(["--root", str(repo), "diff", "main", "--json", "-g", "G3", "--assisted-by", "M", "-H", "H1",
                 "--reviewed-by", "J", "-a", "A1", "--ai-reviewed-by", "M"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total"]["added"] == 1 and data["total"]["levels_added"]["Human-Review"] == {"H1": 1}
    assert data["before"] == {k: v for k, v in data["before"].items()} and data["problems"] == []


def test_freeze_needs_the_default_branch_clean_and_valid(repo, capsys):
    edit_lines(repo, [2])
    code, out = freeze(repo, capsys)
    assert code == 2 and "the working tree has changes" in out
    sha = commit(repo, "AI, human review open", "AI-Generation: G3\nAssisted-by: M\nHuman-Review: TODO\nAI-Review: A1\n"
                 "AI-Reviewed-by: M")
    code, out = freeze(repo, capsys)
    assert code == 2 and "'aisignoff lint' fails here" in out and not (repo / "SIGNOFF.snapshot.json").exists()
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{sha}"\nHuman-Review = "H1"\nReviewed-by = "Jane"\n')
    commit(repo, "reviewed", D("G0", "H2", "A0"))
    git(repo, "checkout", "-q", "-b", "feature")
    edit_lines(repo, [5])
    commit(repo, "work")
    code, out = freeze(repo, capsys)
    assert code == 2 and "commits that aren't on the default branch" in out
    git(repo, "checkout", "-q", "main")
    git(repo, "checkout", "-q", "-b", "freeze")  # a new branch at main's commit: the pull request way
    assert freeze(repo, capsys)[0] == 0
    commit(repo, "freeze")
    assert freeze(repo, capsys)[0] == 2  # the snapshot's own commit isn't on main yet
    merge(repo, "freeze", "Merge freeze\n\n" + D("G0", "H2", "A0"))
    edit_lines(repo, [6])
    commit(repo, "more", G3)
    code, out = freeze(repo, capsys)  # again, later: the new lines join it
    assert code == 0 and "Updated SIGNOFF.snapshot.json" in out
    assert git(repo, "status", "--porcelain").split() == ["M", "SIGNOFF.snapshot.json"]
    commit(repo, "freeze again")
    r, project = result(repo)
    assert [by_line(r)[n].declaration.short() for n in (1, 2, 6)] == ["G0 H2 A0", "G3 H1 A1", "G3 H1 A1"]
    assert {k for p in r.parts for k in p.kinds} == {"frozen"}
    assert project.history_problems == []


def test_a_snapshot_that_doesnt_match_its_commit_is_reported(frozen, capsys):
    repo = frozen
    path = repo / "SIGNOFF.snapshot.json"
    good = path.read_text()
    data = json.loads(good)
    path.write_text(good.replace(data["files"]["solver.py"]["blob"], "0" * 40))
    code, out = lint(repo, capsys)
    assert code == 1 and "doesn't match commit" in out
    path.write_text(good.replace(data["commit"], git(repo, "rev-parse", "pr")))  # a commit that isn't main's
    code, out = lint(repo, capsys)
    assert code == 1 and "is not on the default branch" in out
    path.write_text("{}")
    code, out = lint(repo, capsys)
    assert code == 1 and '"format": 1' in out
    path.write_text(good)
    assert lint(repo, capsys)[0] == 0


def test_snapshot_in_a_project_below_the_top_of_the_repository(nested, capsys):
    root = nested / "paper"
    write(root, "a.py", "1\ntwo\n")
    commit(nested, "AI change", G3)
    assert freeze(root, capsys)[0] == 0
    assert set(json.loads((root / "SIGNOFF.snapshot.json").read_text())["files"]) == {"a.py"}
    commit(nested, "freeze")
    git(nested, "mv", "paper/a.py", "paper/b.py")
    write(root, "b.py", "0\n1\ntwo\n")
    commit(nested, "rename and change", D("G0", "H3", "A0"))
    r, project = result(root, "b.py")
    assert [by_line(r)[n].declaration.short() for n in (1, 2, 3)] == ["G0 H3 A0", "G0 H2 A0", "G3 H1 A1"]
    assert project.history_problems == []


def test_the_default_branch_is_origins_unless_the_local_one_is_ahead(repo, tmp_path_factory):
    clone = tmp_path_factory.mktemp("clone") / "c"
    git(repo.parent, "clone", "-q", str(repo), str(clone))
    git(clone, "config", "user.email", "c@x")
    git(clone, "config", "user.name", "C")
    setting(clone, 'undeclared = "error"')
    commit(clone, "config, not pushed", D("G0", "H2", "A0"))
    git(clone, "checkout", "-q", "-b", "feature")
    edit_lines(clone, [4])
    commit(clone, "work")
    from aisignoff.history import History
    h = History(clone, Project(clone).config)
    assert h.base == git(clone, "rev-parse", "main") and len(h.pending) == 1  # main is ahead of origin/main
    git(clone, "branch", "-q", "-f", "main", "origin/main~0")
    git(clone, "update-ref", "refs/remotes/origin/main", "feature~1")  # as after a fetch: origin's main moved on
    h = History(clone, Project(clone).config)
    assert h.base == git(clone, "rev-parse", "feature~1") and len(h.pending) == 1
