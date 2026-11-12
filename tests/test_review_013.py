"""The findings of the review of 0.13: a second snapshot, hand edits of one, corrections after
--prune, release branches, and the smaller notes and messages."""
import json

from aisignoff.project import Project

from test_history import G3, commit, edit_lines, git, repo, result  # noqa: F401
from test_history_precedence import D, by_line, merge
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
    # taking the made-up item out again, straight on the default branch, drops an archived entry
    code, out = lint(repo, capsys)
    assert code == 1 and "drops 1 archived" in out
    edit_lines(repo, [9], text="later")
    commit(repo, "the next commit", HAND)
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


# ================================================================== the review of 0.14
def test_a_hand_edit_fails_whatever_version_or_rules_the_snapshot_says(repo, capsys):
    assert run(repo, capsys, "freeze")[0] == 0
    commit(repo, "freeze", HAND)
    path = repo / "SIGNOFF.snapshot.json"
    good = json.loads(path.read_text())
    assert good["rules"] == 1
    for key, value in [("aisignoff", "0.13.0"), ("aisignoff", None), ("rules", 0), ("rules", None)]:
        data = json.loads(json.dumps(good))
        data["declarations"][0]["Human-Review"] = "H3"
        if value is None:
            del data[key]
        else:
            data[key] = value
        path.write_text(json.dumps(data, indent=1) + "\n")
        commit(repo, "edited, with another version", HAND)
        code, out = lint(repo, capsys, "--strict")
        assert code == 1 and ("isn't what 'aisignoff freeze' writes" in out or "under other rules" in out), out
        assert run(repo, capsys, "freeze", "--check")[0] == 1
    # the source of a declaration is only words: another version may say it differently
    data = json.loads(json.dumps(good))
    data["aisignoff"] = "0.13.0"
    data["declarations"][0]["source"] = "said differently"
    path.write_text(json.dumps(data, indent=1) + "\n")
    commit(repo, "another version's words", HAND)
    code, out = lint(repo, capsys, "--strict")
    assert code == 0, out


def test_a_personal_ignore_revs_file_doesnt_change_the_levels(repo, capsys, monkeypatch, tmp_path_factory):
    edit_lines(repo, [2], text="styled")
    style = commit(repo, "style", G3)
    other = tmp_path_factory.mktemp("home")
    (other / "revs").write_text(style + "\n")
    (other / "gitconfig").write_text(f"[blame]\n\tignoreRevsFile = {other / 'revs'}\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(other / "gitconfig"))
    assert levels(repo)[1] == "G3 H1 A1"
    assert run(repo, capsys, "freeze")[0] == 0
    commit(repo, "freeze", HAND)
    monkeypatch.delenv("GIT_CONFIG_GLOBAL")
    assert lint(repo, capsys)[0] == 0


def test_a_snapshot_cant_go_back_or_drop_archived_entries(repo, capsys):
    assert run(repo, capsys, "freeze")[0] == 0
    commit(repo, "freeze", HAND)
    old = (repo / "SIGNOFF.snapshot.json").read_text()
    frozen_with_entries(repo, capsys)  # a second freeze, with --prune
    assert lint(repo, capsys, "--strict")[0] == 0
    git(repo, "checkout", "-q", "-b", "back")
    (repo / "SIGNOFF.snapshot.json").write_text(old)
    commit(repo, "the first snapshot again", HAND)
    code, out = lint(repo, capsys)
    assert code == 1 and "only moves forward" in out and "drops 2 archived" in out
    git(repo, "rm", "-q", "SIGNOFF.snapshot.json")
    commit(repo, "no snapshot", HAND)
    code, out = lint(repo, capsys)
    assert code == 1 and "was deleted" in out


def test_archived_hashes_are_full(repo, capsys):
    edit_lines(repo, [2])
    sha = commit(repo, "undeclared")
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{sha[:7]}"\n' + "".join(
            f'{k.strip()} = "{v.strip()}"\n' for k, v in (line.split(":", 1) for line in G3.splitlines())))
    commit(repo, "backfill", HAND)
    assert run(repo, capsys, "freeze", "--prune")[0] == 0
    (item,) = json.loads((repo / "SIGNOFF.snapshot.json").read_text())["archive"]
    assert item["commits"][0]["commit"] == sha
    commit(repo, "freeze", HAND)
    assert lint(repo, capsys, "--strict")[0] == 0


def test_a_snapshot_changed_below_the_last_commit_of_a_push_is_checked(repo, capsys, monkeypatch):
    assert run(repo, capsys, "freeze")[0] == 0
    before = commit(repo, "freeze", HAND)
    path = repo / "SIGNOFF.snapshot.json"
    data = json.loads(path.read_text())
    data["declarations"][0]["Human-Review"] = "H3"
    path.write_text(json.dumps(data, indent=1) + "\n")
    commit(repo, "edited", HAND)
    edit_lines(repo, [9], text="later")
    commit(repo, "something else", HAND)
    assert lint(repo, capsys)[0] == 0  # only HEAD's commit is looked at
    event = repo.parent / "event.json"
    event.write_text(json.dumps({"before": before}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert lint(repo, capsys)[0] == 1


def test_freeze_runs_again_before_the_snapshot_is_committed(repo, capsys):
    edit_lines(repo, [2])
    commit(repo, "AI change", G3)
    assert run(repo, capsys, "freeze")[0] == 0
    commit(repo, "freeze", HAND)
    assert run(repo, capsys, "freeze", "--reset", str(repo / "solver.py"))[0] == 0
    code, out = run(repo, capsys, "freeze")
    assert code == 0, out
    assert "reset" not in json.loads((repo / "SIGNOFF.snapshot.json").read_text())
    commit(repo, "freeze again", HAND)
    assert lint(repo, capsys)[0] == 0


def test_the_note_counts_only_entries_added_since_the_snapshot(repo, capsys):
    edit_lines(repo, [2])
    sha = commit(repo, "undeclared")
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{sha}"\n' + "".join(
            f'{k.strip()} = "{v.strip()}"\n' for k, v in (line.split(":", 1) for line in G3.splitlines())))
    commit(repo, "backfill", HAND)
    assert run(repo, capsys, "freeze")[0] == 0  # without --prune: the entry stays
    commit(repo, "freeze", HAND)
    assert "from before the snapshot" not in lint(repo, capsys)[1]


# ================================================================== the v1.0 readiness review
def test_the_json_keys_of_format_1(repo, capsys):
    """What docs/report.md lists: a key removed or renamed raises "format"."""
    edit_lines(repo, [2])
    commit(repo, "AI change", G3)
    code, out = run(repo, capsys, "report", "--json")
    data = json.loads(out)
    assert set(data) == {"format", "aisignoff", "files"} and data["format"] == 1
    f = next(f for f in data["files"] if f["path"] == "solver.py")
    levels = {"AI-Generation", "Human-Review", "AI-Review", "Assisted-by", "Reviewed-by", "AI-Reviewed-by", "source"}
    assert set(f) == levels | {"path", "errors", "parts"}
    assert set(f["parts"][0]) == levels | {"errors", "lines", "runs", "kinds", "advisory"}
    data = json.loads(run(repo, capsys, "report", "--tree", "--json")[1])
    assert {"format", "aisignoff", "name", "path", "type", "files", "lines", "errors", "counts", "children"} <= set(data)
    assert set(data["counts"]["AI-Generation"]) == {"files", "lines"}
    data = json.loads(run(repo, capsys, "diff", "HEAD~1", "--json")[1])
    assert {"format", "aisignoff", "base", "base_name", "base_tip", "files", "history", "rows", "total", "attested",
            "before", "after", "problems", "notes", "note"} <= set(data)
    assert set(data["total"]) == {"name", "added", "removed", "levels_added", "levels_removed"}


def test_a_snapshot_of_other_rules_is_accepted_only_as_it_is(repo, capsys):
    assert run(repo, capsys, "freeze")[0] == 0
    path = repo / "SIGNOFF.snapshot.json"
    data = json.loads(path.read_text())
    data["aisignoff"] = "0.11.0"
    del data["rules"]
    data["declarations"][0]["Human-Review"] = "H3"  # an older version worked it out differently
    path.write_text(json.dumps(data, indent=1) + "\n")
    commit(repo, "freeze with an older version", HAND)
    edit_lines(repo, [9], text="later")
    commit(repo, "later", HAND)
    # on the default branch, unchanged: accepted as it is, by lint and freeze --check
    assert lint(repo, capsys, "--strict")[0] == 0
    code, out = run(repo, capsys, "freeze", "--check")
    assert code == 0 and "under other rules" in out and "accepted as it is" in out
    # as a change it fails
    git(repo, "checkout", "-q", "-b", "edit")
    data["declarations"][0]["Reviewed-by"] = ["Someone"]
    path.write_text(json.dumps(data, indent=1) + "\n")
    commit(repo, "changed", HAND)
    code, out = lint(repo, capsys)
    assert code == 1 and "under other rules" in out
    assert run(repo, capsys, "freeze", "--check")[0] == 1


def test_a_0_13_archive_with_short_hashes_passes(repo, capsys):
    edit_lines(repo, [2])
    sha = commit(repo, "undeclared")
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{sha[:7]}"\n' + "".join(
            f'{k.strip()} = "{v.strip()}"\n' for k, v in (line.split(":", 1) for line in G3.splitlines())))
    commit(repo, "backfill", HAND)
    assert run(repo, capsys, "freeze", "--prune")[0] == 0
    path = repo / "SIGNOFF.snapshot.json"
    path.write_text(path.read_text().replace(sha, sha[:7]))  # as 0.13 archived it
    commit(repo, "freeze", HAND)
    code, out = run(repo, capsys, "freeze", "--check")
    assert code == 0, out


def test_a_pull_requests_run_needs_the_default_branch(tmp_path, capsys, monkeypatch):
    git(tmp_path, "init", "-q", "-b", "develop")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "T")
    (tmp_path / "SIGNOFF.toml").write_text('version = 3\n\n[history]\nenabled = true\n\n[[annotations]]\npath = "**"\n'
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


def test_a_snapshot_deleted_straight_on_the_default_branch_fails(repo, capsys):
    frozen_with_entries(repo, capsys)
    git(repo, "rm", "-q", "SIGNOFF.snapshot.json")
    commit(repo, "no snapshot", HAND)
    code, out = lint(repo, capsys)
    assert code == 1 and "was deleted" in out


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


def test_freeze_refuses_commits_that_arent_pushed(repo, capsys, tmp_path_factory):
    origin = tmp_path_factory.mktemp("origin") / "o.git"
    git(repo, "clone", "-q", "--bare", str(repo), str(origin))
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "fetch", "-q", "origin")
    edit_lines(repo, [9], text="local")
    commit(repo, "not pushed", HAND)
    code, out = run(repo, capsys, "freeze")
    assert code == 2 and "aren't pushed" in out
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    assert run(repo, capsys, "freeze")[0] == 0
