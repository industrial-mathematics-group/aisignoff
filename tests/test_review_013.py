"""The findings of the review of 0.13: a second snapshot, hand edits of one, corrections after
--prune, release branches, and the smaller notes and messages."""
import json

from aisignoff.project import Project

from test_history import G3, commit, edit_lines, git, repo, result  # noqa: F401
from test_history_precedence import D, by_line
from test_history_snapshot import lint
from test_review_012 import frozen_with_entries, levels, run

HAND = D("G0", "H2", "A0")


# ------------------------------------------------------------------ H1
def test_a_second_snapshot_passes_lint_when_a_line_came_back_or_moved(repo, capsys):
    assert run(repo, capsys, "freeze")[0] == 0
    commit(repo, "freeze", HAND)
    edit_lines(repo, [5], text="tuned")
    commit(repo, "tune line 5", G3)
    edit_lines(repo, [5], text="line")  # back as it was: the line is this commit's now
    lines = (repo / "solver.py").read_text().splitlines()
    (repo / "solver.py").write_text("\n".join([lines[2], *lines[:2], *lines[3:]]) + "\n")  # line 3 moves up
    commit(repo, "back to line 5, move line 3", G3)
    before = levels(repo)
    assert before[4] == "G3 H1 A1"
    assert run(repo, capsys, "freeze")[0] == 0
    commit(repo, "second freeze", HAND)
    code, out = lint(repo, capsys, "--strict")
    assert code == 0, out
    assert levels(repo) == before
    code, out = run(repo, capsys, "freeze", "--check")
    assert code == 0 and "is what 'aisignoff freeze' writes" in out


# ------------------------------------------------------------------ M1
def test_freeze_check_and_lint_catch_any_hand_edit(repo, capsys):
    assert run(repo, capsys, "freeze")[0] == 0
    commit(repo, "freeze", HAND)
    path = repo / "SIGNOFF.snapshot.json"
    good = json.loads(path.read_text())

    def edited(change):
        data = json.loads(json.dumps(good))
        change(data)
        path.write_text(json.dumps(data, indent=1) + "\n")
        commit(repo, "edited by hand", HAND)
        code, out = lint(repo, capsys)
        checked = run(repo, capsys, "freeze", "--check")[0]
        path.write_text(json.dumps(good, indent=1) + "\n")
        commit(repo, "restored", HAND)
        return code, out, checked

    # the first snapshot: there is none before it to compare with
    code, out, checked = edited(lambda d: d["declarations"][0].update({"Human-Review": "H3"}))
    assert code == 1 and checked == 1 and "isn't what 'aisignoff freeze' writes" in out
    code, out, checked = edited(lambda d: d["declarations"][0].update({"Reviewed-by": ["Someone Else"]}))
    assert code == 1 and checked == 1
    # a made-up archive item
    code, out, checked = edited(lambda d: d.update(archive=[{"commit": d["commit"], "commits": [], "attestations": [
        {"path": "solver.py", "blob": "0" * 40, "Human-Review": "H3", "Reviewed-by": "Mallory"}]}]))
    assert code == 1 and checked == 1 and "its archive isn't" in out
    assert lint(repo, capsys)[0] == 0


def test_an_unchanged_snapshot_isnt_worked_out_again(repo, capsys, monkeypatch):
    assert run(repo, capsys, "freeze")[0] == 0
    commit(repo, "freeze", HAND)
    edit_lines(repo, [2])
    commit(repo, "later", G3)
    calls = []
    monkeypatch.setattr(Project, "verify_snapshot", lambda self: calls.append(1) or ([], []))
    assert lint(repo, capsys)[0] == 0 and calls == []


# ------------------------------------------------------------------ M2 and L2
def test_freeze_reset_works_a_file_out_again_with_its_archived_corrections(repo, capsys):
    before = frozen_with_entries(repo, capsys)  # the corrections are in the archive now
    initial = git(repo, "rev-list", "--max-parents=0", "HEAD")
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{initial}"\nAI-Generation = "G1"\nHuman-Review = "H2"\n'
                'AI-Review = "A1"\nAssisted-by = "Model A"\nReviewed-by = "Jane"\nAI-Reviewed-by = "Model A"\n')
    commit(repo, "the first commit was AI-assisted after all", HAND)
    code, out = lint(repo, capsys)
    assert "for commits from before the snapshot" in out and "freeze --reset" in out  # L1
    assert levels(repo) == before  # frozen: the entry changes nothing yet
    assert run(repo, capsys, "freeze", "--reset", str(repo / "solver.py"))[0] == 0
    commit(repo, "freeze, solver.py worked out again", HAND)
    assert json.loads((repo / "SIGNOFF.snapshot.json").read_text())["reset"] == ["solver.py"]
    after = levels(repo)
    assert after[0] == "G1 H3 A1"  # the new entry, with the archived attestation's H3
    assert after[1] == before[1] == "G3 H3 A2"  # the archived [[commits]] entry still counts
    code, out = lint(repo, capsys)
    assert code == 0, out  # lint works it out again the same way
    assert run(repo, capsys, "freeze", "--reset", str(repo.parent))[0] == 2


def test_a_file_included_after_a_prune_keeps_its_archived_correction(repo, capsys):
    toml = repo / "SIGNOFF.toml"
    toml.write_text(toml.read_text().replace("version = 3\n", 'version = 3\nexclude = ["gen/**"]\n'))
    (repo / "gen").mkdir()
    (repo / "gen" / "a.py").write_text("generated\n")
    sha = commit(repo, "add gen, undeclared")
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{sha}"\n' + "".join(
            f'{k.strip()} = "{v.strip()}"\n' for k, v in (line.split(":", 1) for line in G3.splitlines())))
    commit(repo, "backfill", HAND)
    assert run(repo, capsys, "freeze", "--prune")[0] == 0
    commit(repo, "freeze", HAND)
    toml.write_text(toml.read_text().replace('exclude = ["gen/**"]\n', ""))
    commit(repo, "include gen", HAND)
    assert levels(repo, "gen/a.py") == ["G3 H1 A1"]


# ------------------------------------------------------------------ M3
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


# ------------------------------------------------------------------ L4 and L5
def test_prune_keeps_the_comment_of_the_next_table(repo, capsys):
    sha = git(repo, "rev-parse", "HEAD")
    text = (repo / "SIGNOFF.toml").read_text().replace(
        "[[annotations]]", f'[[commits]]\ncommit = "{sha}"\nAI-Generation = "G0"\nHuman-Review = "H2"\nAI-Review = "A0"\nReviewed-by = "Jane"\n\n'
        "# Vendored code: reviewed upstream\n[[annotations]]")
    (repo / "SIGNOFF.toml").write_text(text)
    commit(repo, "toml", HAND)
    code, out = run(repo, capsys, "freeze", "--prune")
    assert code == 0, out
    text = (repo / "SIGNOFF.toml").read_text()
    assert "[[commits]]" not in text and "\n\n# Vendored code: reviewed upstream\n[[annotations]]" in text


def test_a_partial_commits_entry_on_an_undeclared_commit_says_how_to_raise_a_review(repo, capsys):
    edit_lines(repo, [2])
    sha = commit(repo, "undeclared")
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{sha}"\nHuman-Review = "H3"\nReviewed-by = "Rita"\n')
    commit(repo, "a review", HAND)
    r, _ = result(repo)
    errors = " ".join(by_line(r)[2].errors)
    assert "the [[commits]] entry for commit" in errors and "aisignoff attest" in errors
