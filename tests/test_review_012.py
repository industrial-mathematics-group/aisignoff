"""The findings of the review of 0.12: attestations of content from before the snapshot, merge
queues, a pull request's report, reverts and pulls, and what a snapshot leaves out."""
import json

import pytest

from aisignoff.cli import main
from aisignoff.model import Declaration, counted_level, error_axes, validate

from test_aisignoff import write
from test_history import G3, commit, edit_lines, git, repo, result, shares  # noqa: F401
from test_history_precedence import D, by_line, merge
from test_history_snapshot import AGENT, freeze, lint, setting


def run(repo, capsys, *args):
    capsys.readouterr()
    code = main(["--root", str(repo), *args])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def levels(repo, path="solver.py"):
    lines = by_line(result(repo, path)[0])
    return [lines[n].declaration.short() for n in sorted(lines)]


# ------------------------------------------------------------------ M1
def test_an_attestation_of_content_from_before_the_snapshot_raises_the_lines_it_had(repo, capsys):
    edit_lines(repo, [2, 3])
    reviewed = commit(repo, "AI change", G3)
    edit_lines(repo, [3, 9], text="later")
    commit(repo, "a later AI change", G3)
    assert freeze(repo, capsys)[0] == 0
    commit(repo, "freeze", D("G0", "H2", "A0"))
    assert run(repo, capsys, "attest", str(repo / "solver.py"), "--at", reviewed, "-H", "H3", "--reviewed-by", "Rita")[0] == 0
    commit(repo, "attest", D("G0", "H2", "A0"))
    r, project = result(repo)
    lines = by_line(r)
    # line 2 was in the checked content and hasn't changed; lines 3 and 9 were written after it
    assert lines[2].declaration.short() == "G3 H3 A1" and lines[2].kinds == ("frozen", "attestation", "frozen")
    assert lines[3].declaration.short() == lines[9].declaration.short() == "G3 H1 A1"
    assert lines[1].declaration.short() == "G0 H3 A0" and project.history_problems == []
    with_snapshot = levels(repo)
    git(repo, "rm", "-q", "SIGNOFF.snapshot.json")
    commit(repo, "without the snapshot", D("G0", "H2", "A0"))
    assert levels(repo) == with_snapshot  # the same lines as history says


def test_an_old_attestation_follows_frozen_lines_through_later_changes(repo, capsys):
    edit_lines(repo, [2])
    reviewed = commit(repo, "AI change", G3)
    edit_lines(repo, [5], text="later")
    commit(repo, "a later AI change", G3)
    assert freeze(repo, capsys)[0] == 0
    commit(repo, "freeze", D("G0", "H2", "A0"))
    assert run(repo, capsys, "attest", str(repo / "solver.py"), "--at", reviewed, "-H", "H3", "--reviewed-by", "Rita")[0] == 0
    lines = (repo / "solver.py").read_text().splitlines()
    (repo / "solver.py").write_text("\n".join(["a new first line", *lines]) + "\n")  # the frozen lines move down
    commit(repo, "attest, and a change after the snapshot", D("G3", "H0", "A1"))
    assert levels(repo)[:4] == ["G3 H0 A1", "G0 H3 A0", "G3 H3 A1", "G0 H3 A0"]
    assert levels(repo)[5] == "G3 H1 A1"  # "later 5": not in the checked content


# ------------------------------------------------------------------ M2
def queue(repo):
    """A merge queue's commit: the pull request merged on top of main, with its final message,
    checked out before main moves to it."""
    git(repo, "checkout", "-q", "-b", "pr")
    edit_lines(repo, [2])
    commit(repo, "agent", AGENT)
    git(repo, "checkout", "-q", "--detach", "main")
    git(repo, "merge", "-q", "--no-ff", "pr", "-m", "Merge pull request #7\n\n" + AGENT + "\nHuman-Review: TODO")


def test_landed_checks_the_commit_a_merge_queue_will_land(repo, capsys, monkeypatch):
    queue(repo)
    assert lint(repo, capsys)[0] == 0  # as a pull request's preview: nothing fails
    code, out = lint(repo, capsys, "--landed")
    assert code == 1 and "Human-Review is still TODO" in out
    assert run(repo, capsys, "report", "--json", "--landed")[0] == 0
    body = write(repo.parent, "body.md", D("G3", "H1", "A1"))
    assert lint(repo, capsys, "--landed", "--declare-from", str(body))[0] == 2
    # GitHub's merge queue is recognised by its ref
    monkeypatch.setenv("GITHUB_REF", "refs/heads/gh-readonly-queue/main/pr-7-0123abc")
    code, out = lint(repo, capsys)
    assert code == 1 and "merge queue" in out and "Human-Review is still TODO" in out
    monkeypatch.setenv("GITHUB_REF", "refs/pull/7/merge")
    assert lint(repo, capsys)[0] == 0


def test_landed_enforces_a_release_branch(repo, capsys):
    setting(repo, 'undeclared = "error"')
    commit(repo, "config", D("G0", "H2", "A0"))
    git(repo, "checkout", "-q", "-b", "release/1.x")
    edit_lines(repo, [4])
    commit(repo, "backport, undeclared")
    assert lint(repo, capsys)[0] == 1  # the first commit declares nothing: as on main
    code, out = lint(repo, capsys, "--landed")
    assert code == 1 and "backport, undeclared" in out
    assert "backport, undeclared" not in lint(repo, capsys)[1]


# ------------------------------------------------------------------ M3
def test_a_pull_requests_report_shows_no_review_its_commits_claim(repo, capsys):
    git(repo, "checkout", "-q", "-b", "pr")
    edit_lines(repo, [2])
    commit(repo, "agent", D("G3", "H3", "A3", by="The Agent"))
    git(repo, "checkout", "-q", "--detach", "main")
    git(repo, "merge", "-q", "--no-ff", "pr", "-m", "preview")
    line = by_line(result(repo)[0])[2]
    assert line.declaration.short() == "G3 -- --" and line.advisory
    code, out = run(repo, capsys, "report", "--tree", "--weight", "lines", "--files")
    assert code == 0 and "H3" not in out and "A3" not in out and "G3 10%" in out
    assert "1 line(s) that aren't on the default branch yet" in out
    assert "aren't on the default branch yet" in run(repo, capsys, "report", "--tree", "--markdown")[1]
    # with the description, the report shows what the diff shows
    body = write(repo.parent, "body.md", D("G3", "H1", "A1"))
    code, out = run(repo, capsys, "report", "--tree", "--weight", "lines", "--files", "--declare-from", str(body),
                    "--base", "HEAD^1")
    assert code == 0 and "H1 10%" in out and "A1 10%" in out and "aren't on the default branch" not in out
    assert run(repo, capsys, "report", "--base", "HEAD^1")[0] == 2


def test_commits_that_land_as_they_are_keep_their_reviews_in_the_report(repo):
    setting(repo, 'merge-method = "rebase"')
    commit(repo, "config", D("G0", "H2", "A0"))
    git(repo, "checkout", "-q", "-b", "pr")
    edit_lines(repo, [2])
    commit(repo, "agent", D("G3", "H1", "A1"))
    assert by_line(result(repo)[0])[2].declaration.short() == "G3 H1 A1"


# ------------------------------------------------------------------ M4
def test_a_revert_through_a_pull_request_is_reported(repo, capsys):
    edit_lines(repo, [2])
    commit(repo, "AI change", G3)
    git(repo, "checkout", "-q", "-b", "feat")
    edit_lines(repo, [2], text="worse")
    commit(repo, "a change to revert")
    merge(repo, "feat", "Merge pull request #12 from o/feat\n\n" + D("G0", "H3", "A0"))
    bad = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "revert-12-feat")
    git(repo, "revert", "--no-edit", "-m", "1", bad)
    # GitHub's Revert button: the merge commit's message has the pull request's title and "Reverts o/r#12"
    merge(repo, "revert-12-feat", 'Merge pull request #13 from o/revert-12-feat\n\nRevert "Merge pull request #12"')
    r, project = result(repo)
    assert by_line(r)[2].declaration.short() == "G0 H2 A0"
    assert len(project.history_warnings) == 1 and "reverts" in project.history_warnings[0]
    assert lint(repo, capsys)[0] == 0 and lint(repo, capsys, "--strict")[0] == 1
    git(repo, "reset", "-q", "--hard", bad)
    edit_lines(repo, [2])
    commit(repo, 'Revert "a change to revert" (#13)', "Reverts o/r#12")  # squashed
    project = result(repo)[1]
    assert len(project.history_warnings) == 1 and "reverts o/r#12" in project.history_warnings[0]
    git(repo, "commit", "-q", "--amend", "-m", 'Revert "a change to revert" (#13)\n\nReverts o/r#12\n\n' + G3)
    assert result(repo)[1].history_warnings == []  # declared: nothing to report


def test_a_pull_that_brings_in_squash_commits_is_reported(repo):
    origin = repo / ".." / f"{repo.name}-origin"
    git(repo.parent, "clone", "-q", str(repo), str(origin))
    git(origin, "config", "user.email", "o@x")
    git(origin, "config", "user.name", "O")
    edit_lines(origin, [2])
    commit(origin, "A pull request (#5)", D("G3", "H2", "A2"))  # squash merged there
    edit_lines(repo, [9], text="direct")
    commit(repo, "direct", D("G0", "H3", "A0"))
    git(repo, "pull", "-q", "--no-rebase", "--no-edit", str(origin), "main")
    r, project = result(repo)
    assert by_line(r)[2].declaration.short() == "G0 H2 A0"
    assert len(project.history_warnings) == 1 and "1 commit(s) inside it that declare" in project.history_warnings[0]


# ------------------------------------------------------------------ rule 3
def test_a_commit_inside_a_pull_request_can_raise_the_generation_but_not_lower_it(repo):
    git(repo, "checkout", "-q", "-b", "pr")
    edit_lines(repo, [2])
    commit(repo, "agent", "AI-Generation: G3\nAssisted-by: M")
    edit_lines(repo, [3], text="hand")
    hand = commit(repo, "claims to be by hand", "AI-Generation: G0")
    merge(repo, "pr", "Merge pr\n\n" + D("G1", "H2", "A1", ai="M, self-check"))
    lines = by_line(result(repo)[0])
    assert lines[2].declaration.short() == "G3 H2 A1" and lines[2].kinds[0] == "branch"
    assert lines[3].declaration.short() == "G1 H2 A1"  # the AI review requirement stays with the line
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{hand}"\nAI-Generation = "G0"\n')
    line = by_line(result(repo)[0])[3]
    assert line.declaration.short() == "G0 H2 A0" and line.errors == []  # a self-check doesn't reach G0


# ------------------------------------------------------------------ L1
def test_a_stale_base_doesnt_declare_the_default_branchs_own_lines(repo):
    stale = git(repo, "rev-parse", "HEAD")
    edit_lines(repo, [2])
    commit(repo, "A pull request that landed (#9)", G3)
    git(repo, "checkout", "-q", "-b", "pr")
    edit_lines(repo, [5])
    commit(repo, "agent", AGENT)
    from aisignoff.history import parse_message
    from aisignoff.project import Project
    pieces = parse_message(D("G1", "H3", "A2"), "", "the description")[0]
    lines = by_line(next(r for r in Project(repo).results(declared=pieces, base=stale) if r.path == "solver.py"))
    assert lines[2].declaration.short() == "G3 H1 A1"  # main's own line, although the base given is older
    assert lines[5].declaration.short() == "G3 H3 A2"


# ------------------------------------------------------------------ L2, L3, L4, L5
def test_a_binary_file_keeps_its_frozen_levels_through_a_rename(repo, capsys):
    write(repo, "img.bin", "a\0b")
    commit(repo, "a binary file", G3)
    assert freeze(repo, capsys)[0] == 0
    commit(repo, "freeze", D("G0", "H2", "A0"))
    git(repo, "mv", "img.bin", "img2.bin")
    commit(repo, "rename")
    r, _ = result(repo, "img2.bin")
    assert r.parts[0].declaration.short() == "G3 H1 A1" and r.parts[0].kinds == ("frozen",) * 3
    write(repo, "img2.bin", "a\0c")
    commit(repo, "change it", D("G0", "H3", "A0"))
    assert result(repo, "img2.bin")[0].parts[0].declaration.short() == "G0 H3 A0"


def test_a_file_the_snapshot_doesnt_have_is_resolved_from_history(repo, capsys):
    toml = (repo / "SIGNOFF.toml").read_text()
    (repo / "SIGNOFF.toml").write_text(toml.replace("\n[history]", 'exclude = ["gen/**"]\n\n[history]'))
    write(repo, "gen/a.py", "one\ntwo\n")
    commit(repo, "generated code", G3)
    assert freeze(repo, capsys)[0] == 0
    assert "gen/a.py" not in json.loads((repo / "SIGNOFF.snapshot.json").read_text())["files"]
    commit(repo, "freeze", D("G0", "H2", "A0"))
    (repo / "SIGNOFF.toml").write_text((repo / "SIGNOFF.toml").read_text().replace('exclude = ["gen/**"]\n', ""))
    commit(repo, "include gen/", D("G0", "H2", "A0"))
    assert levels(repo, "gen/a.py") == ["G3 H1 A1"] * 2  # not the file-level declaration
    edit_lines(repo, [2], path="gen/a.py")
    commit(repo, "change it", D("G0", "H3", "A0"))
    assert levels(repo, "gen/a.py") == ["G3 H1 A1", "G0 H3 A0"]


def test_a_snapshot_whose_runs_dont_cover_a_file_is_reported(repo, capsys):
    edit_lines(repo, [2])
    commit(repo, "AI change", G3)
    assert freeze(repo, capsys)[0] == 0
    path = repo / "SIGNOFF.snapshot.json"
    data = json.loads(path.read_text())
    runs = data["files"]["solver.py"]["runs"]
    assert runs[-1][1] == 10
    runs[-1][1] = 8  # cut short by hand
    path.write_text(json.dumps(data))
    commit(repo, "freeze, edited", D("G0", "H2", "A0"))
    code, out = lint(repo, capsys)
    assert code == 1 and "SIGNOFF.snapshot.json doesn't match commit" in out and "solver.py" in out
    assert levels(repo)[1] == "G3 H1 A1"  # resolved from history meanwhile


def test_freeze_shows_the_errors_and_refuses_warnings(repo, capsys):
    edit_lines(repo, [2])
    bad = commit(repo, "a change to revert", D("G3", "H1", "A0"))
    code, out = freeze(repo, capsys)
    assert code == 2 and "G3 requires at least A1" in out and "solver.py" in out
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{bad}"\nAI-Review = "A1"\nAI-Reviewed-by = "M"\n')
    commit(repo, "correct it", D("G0", "H2", "A0"))
    git(repo, "revert", "--no-edit", bad)
    code, out = freeze(repo, capsys)
    assert code == 2 and "reverts" in out and "--allow-warnings" in out
    assert not (repo / "SIGNOFF.snapshot.json").exists()
    assert run(repo, capsys, "freeze", "--allow-warnings")[0] == 0


# ------------------------------------------------------------------ 0.11 L2, L4
def test_attest_refuses_a_file_declared_as_a_whole(repo, capsys):
    write(repo, "vendor/lib.py", "x\n")
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write('\n[[annotations]]\npath = "vendor/**"\nprecedence = "override"\nAI-Generation = "G0"\n'
                'Human-Review = "H0"\nAI-Review = "A0"\nReviewed-by = "Jane"\n')
    commit(repo, "vendored", D("G0", "H2", "A0"))
    code, out = run(repo, capsys, "attest", str(repo / "vendor/lib.py"), "-H", "H3", "--reviewed-by", "Rita")
    assert code == 2 and 'precedence = "override"' in out
    blob = git(repo, "hash-object", "vendor/lib.py")
    with open(repo / "SIGNOFF.toml", "a") as f:  # written by hand: lint says that it doesn't count
        f.write(f'\n[[attestations]]\npath = "vendor/lib.py"\nblob = "{blob}"\nHuman-Review = "H3"\nReviewed-by = "Rita"\n')
    project = result(repo, "vendor/lib.py")[1]
    assert any("doesn't count" in w for w in project.history_warnings)


@pytest.mark.parametrize("values, undeclared", [
    ({"AI-Generation": "G3", "Assisted-by": ["M"], "Human-Review": "H2", "Reviewed-by": ["J"], "AI-Review": "A2"},
     {"AI-Review"}),  # the reviewing model is missing
    ({"AI-Generation": "G3", "Human-Review": "H2", "Reviewed-by": ["J"], "AI-Review": "A1", "AI-Reviewed-by": ["M"]},
     {"AI-Generation"}),
    ({"AI-Generation": "G3", "Assisted-by": ["M"], "Human-Review": "TODO", "AI-Review": "A1", "AI-Reviewed-by": ["M"]},
     {"Human-Review"}),
    ({"AI-Generation": "G3", "Assisted-by": ["M"], "Human-Review": "H1", "Reviewed-by": ["J"], "AI-Review": "A0"},
     {"AI-Review"}),  # policy: AI-written content must be self-checked
    ({"AI-Generation": "G0", "Human-Review": "H1", "Reviewed-by": ["J"], "AI-Review": "A1", "AI-Reviewed-by": ["M"]},
     {"AI-Review"}),
    ({"AI-Generation": "G0", "Human-Review": "H1", "AI-Review": "A0"}, {"Human-Review"}),
    ({"AI-Generation": "G7", "Human-Review": "H1", "Reviewed-by": ["J"], "AI-Review": "A0"}, {"AI-Generation"}),
])
def test_an_error_makes_only_its_own_axis_undeclared(values, undeclared):
    d = Declaration.from_mapping(values, "test")
    errors = validate(d)
    assert errors
    assert {k for k in ("AI-Generation", "Human-Review", "AI-Review") if counted_level(d, errors, k) == "undeclared"} == undeclared


def test_errors_that_name_no_axis_count_for_all():
    assert len(error_axes("commit 1a2b3c4 declares levels both as trailers and as ticked checkboxes")) == 3
    assert error_axes("Human-Review needs Reviewed-by (the responsible human)") == ("Human-Review",)
    assert error_axes("A2 needs AI-Reviewed-by (reviewing model and session)") == ("AI-Review",)
    d = Declaration()
    assert counted_level(d, validate(d), "AI-Generation") == "undeclared"


def test_the_pull_request_diff_shows_a_todo_on_its_own_axis(repo, capsys):
    git(repo, "checkout", "-q", "-b", "pr")
    edit_lines(repo, [2])
    commit(repo, "agent", AGENT)
    body = write(repo.parent, "body.md", AGENT + "\nHuman-Review: TODO")
    code, out = run(repo, capsys, "diff", "main", "--json", "--declare-from", str(body))
    added = json.loads(out)["total"]["levels_added"]
    assert added == {"AI-Generation": {"G3": 1}, "Human-Review": {"undeclared": 1}, "AI-Review": {"A1": 1}}
