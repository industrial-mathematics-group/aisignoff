"""How the declarations around a line combine: generation from the most specific, reviews from
the highest; the message formats that declare (scenarios of the second declaration review)."""
import json

from aisignoff.history import parse_checkboxes, parse_trailers
from aisignoff.project import Project

from test_aisignoff import write
from test_history import G3, commit, edit_lines, git, repo, result, shares  # noqa: F401
from test_history_edges import TEMPLATE


def by_line(r):
    return {n: p for p in r.parts for a, b in p.runs for n in range(a, b + 1)}


def merge(repo, branch, message):
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", branch, "-m", message)


def D(g, h, a, by="Jane", ai="M, fresh session"):
    s = f"AI-Generation: {g}\nHuman-Review: {h}\nAI-Review: {a}\nReviewed-by: {by}"
    return s + (f"\nAI-Reviewed-by: {ai}" if a != "A0" else "") + ("\nAssisted-by: M" if g != "G0" else "")


# ------------------------------------------------------------------ message formats
def test_trailers_anywhere_in_the_body():
    tr = D("G3", "H1", "A1")
    for body in (f"Body.\n\n{tr}\n\nCo-Authored-By: C <c@x>",  # a co-author paragraph after them
                 f"Body.\n\n{tr}\n\n---------\n\nCo-authored-by: Bob <b@x>",  # GitHub's squash
                 f"{tr}\nThanks to Bob for the idea."):  # a prose line
        pieces = parse_trailers(body, "c")
        assert {i: p.level for i, p in pieces.items()} == {0: "G3", 1: "H1", 2: "A1"}, body
    assert parse_trailers("```\nAI-Generation: G3\n```\n<!--\nHuman-Review: H2\n-->\n", "c") == {}


def test_unticked_ai_boxes_and_the_a0_box_mean_a0():
    old = TEMPLATE.replace("- [ ] **A0** No AI review\n", "").replace("- [x] **A1**", "- [ ] **A1**")
    assert parse_checkboxes(old.format(a2=" ", model=""), "J", "c")[2].level == "A0"
    ticked = TEMPLATE.replace("- [ ] **A0**", "- [x] **A0**").replace("- [x] **A1**", "- [ ] **A1**")
    pieces = parse_checkboxes(ticked.format(a2=" ", model=""), "J", "c")
    assert pieces[2].level == "A0" and pieces[2].names == ()


def test_boxes_in_code_blocks_and_other_bold_items_dont_count():
    text = "Docs\n\n```\n- [x] **G3** AI\n- [x] **H2** read\n```\n\n- [x] **Breaking change**\n"
    assert parse_checkboxes(text, "J", "c") == {}
    text = TEMPLATE.format(a2=" ", model="") + "\n## Checklist\n- [x] **Breaking change**\n"
    assert parse_checkboxes(text, "J", "c")[0].names == ("Claude Opus (Anthropic)", "Some Model 2")


def test_trailers_and_boxes_both_count_until_a_correction_settles_it(repo):
    edit_lines(repo, [1])
    boxes = TEMPLATE.format(a2=" ", model="")
    sha = commit(repo, "Docs\n\n" + boxes, "Human-Review: H2\nReviewed-by: Max")
    r, _ = result(repo)
    line = by_line(r)[1]
    assert line.declaration.short() == "G3 H2 A1"  # boxes give G3 and A1, the trailer H2
    assert any("both as trailers and as ticked checkboxes" in e for e in line.errors)
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{sha}"\nAI-Review = "A1"\nAI-Reviewed-by = "M"\n')
    r, _ = result(repo)
    assert not any("both" in e for e in r.errors)


# ------------------------------------------------------------------ precedence
def test_the_merge_commit_owns_its_lines_and_a_branch_commit_only_says_generation(repo):
    git(repo, "checkout", "-q", "-b", "feature")
    edit_lines(repo, [2, 3])
    commit(repo, "agent", D("G3", "H0", "A1", ai="M, self-check"))
    edit_lines(repo, [4], text="hand")
    commit(repo, "by hand", "AI-Generation: G0\nHuman-Review: H3\nReviewed-by: Bob")
    edit_lines(repo, [5])
    commit(repo, "todo", "AI-Generation: TODO\nHuman-Review: TODO\nAI-Review: A1\nAI-Reviewed-by: M")
    merge(repo, "feature", "Merge feature\n\n" + D("G3", "H2", "A2"))
    r, project = result(repo)
    lines = by_line(r)
    assert lines[2].declaration.short() == "G3 H2 A2" and lines[2].kinds == ("branch", "commit", "commit")
    # the review that a commit inside claims doesn't count, higher or lower: the pull request's does
    assert lines[4].declaration.short() == "G0 H2 A2" and lines[4].declaration.reviewed_by == ("Jane",)
    assert lines[5].declaration.short() == "G3 H2 A2" and lines[5].kinds[0] == "commit"  # a TODO says nothing
    assert r.errors == [] and project.history_warnings == []
    merge_sha = git(repo, "rev-parse", "HEAD")
    with open(repo / "SIGNOFF.toml", "a") as f:  # a correction of the merge reaches all its lines
        f.write(f'\n[[commits]]\ncommit = "{merge_sha}"\nHuman-Review = "H3"\nReviewed-by = "Rita"\n')
    lines = by_line(result(repo)[0])
    assert {lines[n].declaration.short() for n in (2, 3, 5)} == {"G3 H3 A2"} and lines[4].declaration.short() == "G0 H3 A2"


def test_a_partial_declaration_doesnt_take_the_rest_from_the_file(repo):
    edit_lines(repo, [2])
    commit(repo, "AI change", "AI-Generation: G3\nAssisted-by: M")
    r, _ = result(repo)
    line = by_line(r)[2]
    assert line.declaration.short() == "G3 -- --" and line.kinds == ("commit", "required", "required")
    assert any("declares levels, but no Human-Review" in e for e in line.errors)
    assert shares(r)["G0 H2 A0"] == 9  # lines of commits that declare nothing keep the file's levels


def test_a_pull_request_merged_into_another_declares_nothing(repo):
    """Stacked pull requests: B is merged into A, A into main. Only A's merge lands lines on main."""
    git(repo, "checkout", "-q", "-b", "a")
    edit_lines(repo, [2])
    commit(repo, "AI part of A")
    git(repo, "checkout", "-q", "-b", "b")
    edit_lines(repo, [3], text="hand")
    commit(repo, "by hand")
    edit_lines(repo, [4], text="hand")
    commit(repo, "by hand, and saying so", "AI-Generation: G0")
    git(repo, "checkout", "-q", "a")
    git(repo, "merge", "-q", "--no-ff", "b", "-m", "Merge B into A\n\n" + D("G0", "H3", "A0", by="Bob"))
    merge(repo, "a", "Merge A\n\n" + D("G3", "H2", "A2"))
    r, project = result(repo)
    lines = by_line(r)
    assert lines[2].declaration.short() == "G3 H2 A2"
    assert lines[3].declaration.short() == "G3 H2 A2"  # B's description doesn't count
    assert lines[4].declaration.short() == "G0 H2 A2"  # the commit that wrote it says G0
    assert r.errors == [] and project.history_warnings == []


def test_stacked_pull_requests_land_the_same_whatever_the_method_and_order(repo):
    """The lines a commit lands on the default branch are the diff its pull request showed."""
    def stack():
        git(repo, "checkout", "-q", "-b", "a", "main")
        edit_lines(repo, [2])
        commit(repo, "A's agent", "AI-Generation: G3\nAssisted-by: M\nAI-Review: A1\nAI-Reviewed-by: M")
        git(repo, "checkout", "-q", "-b", "b")
        edit_lines(repo, [3], text="hand")
        commit(repo, "B, by hand", D("G0", "H3", "A0", by="Bob"))

    stack()  # B is merged into A, then A is squashed into main: one commit, A's description
    git(repo, "checkout", "-q", "a")
    git(repo, "merge", "-q", "--no-ff", "b", "-m", "Merge B into A\n\n" + D("G0", "H3", "A0", by="Bob"))
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "a")
    commit(repo, "A (#1)", D("G3", "H1", "A1"))
    lines = by_line(result(repo)[0])
    assert lines[2].declaration.short() == lines[3].declaration.short() == "G3 H1 A1"

    git(repo, "reset", "-q", "--hard", "HEAD~1")
    git(repo, "branch", "-q", "-D", "a", "b")
    stack()  # B lands first (it contains A's commit), then A, whose merge brings nothing new
    merge(repo, "b", "Merge B\n\n" + D("G3", "H2", "A2"))
    merge(repo, "a", "Merge A\n\n" + D("G3", "H1", "A1"))
    r, project = result(repo)
    lines = by_line(r)
    assert lines[2].declaration.short() == "G3 H2 A2"  # landed by B's merge, as B's diff into main showed it
    assert lines[3].declaration.short() == "G0 H2 A2"
    assert r.errors == []


def test_a_git_pull_merge_on_main_owns_what_it_brought_in(repo, capsys):
    from aisignoff.cli import main
    origin = repo.parent / "origin"
    git(repo.parent, "clone", "-q", str(repo), str(origin))
    git(origin, "config", "user.email", "o@x")
    git(origin, "config", "user.name", "O")
    git(origin, "checkout", "-q", "-b", "pr")
    edit_lines(origin, [2])
    commit(origin, "AI part")
    git(origin, "checkout", "-q", "main")
    git(origin, "merge", "-q", "--no-ff", "pr", "-m", "Merge PR 7\n\n" + D("G3", "H2", "A2"))
    edit_lines(repo, [9], text="direct")
    commit(repo, "direct", D("G0", "H3", "A0"))
    git(repo, "pull", "-q", "--no-rebase", "--no-edit", str(origin), "main")
    r, project = result(repo)
    lines = by_line(r)
    # the pull's merge commit landed the pull request's line on this main, and declares nothing
    assert lines[2].declaration.short() == "G0 H2 A0" and lines[9].declaration.short() == "G0 H3 A0"
    assert len(project.history_warnings) == 1 and "declared merge(s) inside it" in project.history_warnings[0]
    capsys.readouterr()
    assert main(["--root", str(repo), "lint"]) == 0 and main(["--root", str(repo), "lint", "--strict"]) == 1
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{git(repo, "rev-parse", "HEAD")}"\nAI-Generation = "G3"\n'
                'Assisted-by = "M"\nHuman-Review = "H2"\nReviewed-by = "Jane"\nAI-Review = "A2"\nAI-Reviewed-by = "M"\n')
    r, project = result(repo)
    assert by_line(r)[2].declaration.short() == "G3 H2 A2" and project.history_warnings == []


def test_attestation_from_a_pull_request_survives_a_change_on_main(repo):
    git(repo, "checkout", "-q", "-b", "fix")
    edit_lines(repo, [1], text="fixed")
    commit(repo, "fix", D("G3", "H1", "A1"))
    blob = git(repo, "hash-object", "solver.py")
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[attestations]]\npath = "solver.py"\nblob = "{blob}"\nHuman-Review = "H3"\nReviewed-by = "P"\n')
    commit(repo, "attest", D("G3", "H1", "A1"))
    git(repo, "checkout", "-q", "main")
    edit_lines(repo, [10], text="main")
    commit(repo, "main moves on", D("G0", "H2", "A0"))
    git(repo, "merge", "-q", "--no-ff", "fix", "-m", "Merge fix\n\n" + D("G3", "H1", "A1"))
    r, project = result(repo)
    assert project.history_problems == []
    lines = by_line(r)
    assert all(lines[n].declaration.short().startswith("G") and lines[n].declaration.get("Human-Review") == "H3"
               for n in range(1, 10))
    assert lines[10].declaration.short() == "G0 H2 A0"  # main's change since: not what was checked


# ------------------------------------------------------------------ the merge preview
def preview(repo, method, declare=True):
    """The merge preview that a pull request's CI run checks out: a merge of the pull request
    into the default branch that isn't on it."""
    text = (repo / "SIGNOFF.toml").read_text().replace("enabled = true", f'enabled = true\nmerge-method = "{method}"')
    (repo / "SIGNOFF.toml").write_text(text)
    commit(repo, "config", D("G0", "H2", "A0"))
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "pr")
    edit_lines(repo, [2])
    commit(repo, "agent", "AI-Generation: G3\nAssisted-by: M\nHuman-Review: TODO\nAI-Review: A1\nAI-Reviewed-by: M")
    edit_lines(repo, [3], text="hand")
    commit(repo, "by hand", "AI-Generation: G0")
    git(repo, "checkout", "-q", "--detach", "main")
    git(repo, "merge", "-q", "--no-ff", "pr", "-m", "Merge the pull request into main")
    project = Project(repo)
    from aisignoff.model import Declaration
    declared = Declaration.from_mapping({"AI-Generation": "G3", "Assisted-by": ["M"], "Human-Review": "H2",
                                         "Reviewed-by": ["Jane"], "AI-Review": "A2",
                                         "AI-Reviewed-by": ["M, fresh"]}, "x") if declare else None
    r = next(r for r in project.results(declared=declared, base=base) if r.path == "solver.py")
    return [by_line(r)[n].declaration.short() for n in (2, 3)], r


def test_preview_of_a_merge(repo):
    assert preview(repo, "merge")[0] == ["G3 H2 A2", "G0 H2 A2"]


def test_preview_of_a_squash_ignores_the_branch_commits(repo):
    assert preview(repo, "squash")[0] == ["G3 H2 A2", "G3 H2 A2"]


def test_preview_of_a_rebase_ignores_the_description(repo):
    levels, r = preview(repo, "rebase")
    assert levels == ["G3 TODO A1", "G0 -- --"] and len(r.errors) > 1  # each commit lands as it is


def test_preview_without_the_description_fails_nothing(repo, capsys):
    from aisignoff.cli import main
    levels, r = preview(repo, "merge", declare=False)
    assert levels == ["G3 TODO A1", "G0 -- --"]  # what the commits say, shown
    assert r.errors == [] and all(p.advisory for n, p in by_line(r).items() if n in (2, 3))
    capsys.readouterr()
    assert main(["--root", str(repo), "lint", "--strict"]) == 0
    assert "2 line(s) that aren't on the default branch yet" in capsys.readouterr().out


# ------------------------------------------------------------------ settings and warnings
def test_commits_entries_that_dont_apply_are_reported(repo):
    git(repo, "checkout", "-q", "-b", "gone")
    edit_lines(repo, [1])
    gone = commit(repo, "rebased away")
    git(repo, "checkout", "-q", "main")
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{gone}"\nHuman-Review = "H3"\nReviewed-by = "R"\n')
    project = Project(repo)
    project.results(quiet=True)
    assert any("is not in the history of HEAD" in p for p in project.history_problems)


def test_ignore_whitespace_setting(repo):
    edit_lines(repo, [3])
    commit(repo, "hand", D("G0", "H3", "A0"))
    text = (repo / "solver.py").read_text().replace("new 3", "    new 3")
    (repo / "solver.py").write_text(text)
    commit(repo, "AI reindents", D("G3", "H1", "A1"))
    assert by_line(result(repo)[0])[3].declaration.short() == "G0 H3 A0"  # -w: a reindent keeps the line's
    toml = (repo / "SIGNOFF.toml").read_text().replace("enabled = true", "enabled = true\nignore-whitespace = false")
    (repo / "SIGNOFF.toml").write_text(toml)
    assert by_line(result(repo)[0])[3].declaration.short() == "G3 H1 A1"


# ------------------------------------------------------------------ 0.10 review
def test_a_hand_written_commit_inside_a_self_checked_pull_request(repo):
    """A1 is the generating session checking itself: it doesn't reach lines a human wrote."""
    git(repo, "checkout", "-q", "-b", "feature")
    edit_lines(repo, [2], text="hand")
    commit(repo, "by hand", "AI-Generation: G0\nHuman-Review: H2\nReviewed-by: Jane")
    edit_lines(repo, [3])
    commit(repo, "agent")
    merge(repo, "feature", "Merge feature\n\n" + D("G3", "H1", "A1", ai="M, self-check"))
    lines = by_line(result(repo)[0])
    assert lines[2].declaration.short() == "G0 H1 A0" and lines[2].errors == []
    assert lines[3].declaration.short() == "G3 H1 A1" and lines[3].errors == []


def test_a_review_claimed_inside_a_pull_request_doesnt_count(repo, capsys):
    from aisignoff.cli import main
    git(repo, "checkout", "-q", "-b", "contrib")
    edit_lines(repo, [2])
    sha = commit(repo, "contribution", D("G3", "H3", "A1", by="Jane Doe"))
    merge(repo, "contrib", "Merge contrib\n\n" + D("G3", "H0", "A1", by="Maintainer"))
    r, project = result(repo)
    assert by_line(r)[2].declaration.short() == "G3 H0 A1" and project.history_warnings == []
    capsys.readouterr()
    assert main(["--root", str(repo), "lint", "--strict"]) == 0
    with open(repo / "SIGNOFF.toml", "a") as f:  # a correction of the commit inside: only generation would count
        f.write(f'\n[[commits]]\ncommit = "{sha[:7]}"\nHuman-Review = "H3"\nReviewed-by = "Jane Doe"\n')
    r, project = result(repo)
    assert by_line(r)[2].declaration.short() == "G3 H0 A1"
    assert len(project.history_warnings) == 1 and "inside a pull request" in project.history_warnings[0]
    git(repo, "reset", "-q", "--hard", "HEAD~1")  # a pull request that leaves an axis to its commits: missing
    merge(repo, "contrib", "Merge contrib\n\nAI-Generation: G3\nAssisted-by: M\nAI-Review: A1\nAI-Reviewed-by: M")
    assert any("declares levels, but no Human-Review" in e for e in by_line(result(repo)[0])[2].errors)


def test_the_pull_requests_todo_wins(repo):
    git(repo, "checkout", "-q", "-b", "feature")
    edit_lines(repo, [2])
    commit(repo, "agent", D("G3", "H0", "A1"))
    merge(repo, "feature", "Merge feature\n\nAI-Generation: G3\nAssisted-by: M\nHuman-Review: TODO\nAI-Review: A1\n"
          "AI-Reviewed-by: M")
    line = by_line(result(repo)[0])[2]
    assert line.declaration.short() == "G3 TODO A1" and any("TODO" in e for e in line.errors)


def test_diff_declare_on_the_branch_resolves_as_the_merge_will(repo, capsys):
    from aisignoff.cli import main
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "feature")
    edit_lines(repo, [2])
    commit(repo, "agent", "AI-Generation: G3\nAssisted-by: M\nHuman-Review: TODO\nAI-Review: A1\nAI-Reviewed-by: M")
    declare = ["-g", "G3", "--assisted-by", "M", "-H", "H2", "--reviewed-by", "Jane", "-a", "A2",
               "--ai-reviewed-by", "M, fresh"]
    capsys.readouterr()
    assert main(["--root", str(repo), "diff", base, "--json", *declare]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total"]["levels_added"]["Human-Review"] == {"H2": 1}  # the PR's review, TODO yields
    assert data["total"]["levels_added"]["AI-Review"] == {"A2": 1}


def test_unclosed_fences_and_inline_code_hide_nothing():
    tr = D("G3", "H1", "A1")
    for body in (f"```aisignoff diff``` shows the change\n\n{tr}\n",  # inline code, not a fence
                 f"Text\n```\nan unclosed block\n\n{tr}\n"):  # never closed: not a block
        assert {i: p.level for i, p in parse_trailers(body, "c").items()} == {0: "G3", 1: "H1", 2: "A1"}, body
    assert parse_trailers("See <!-- a note\nAI-Generation: G3\n--> done\n", "c") == {}


def test_a_message_cannot_forge_another_commits_record(repo):
    git(repo, "checkout", "-q", "-b", "feature")
    edit_lines(repo, [2])
    branch_sha = commit(repo, "undeclared branch commit")
    merge(repo, "feature", "Merge feature")
    edit_lines(repo, [9], text="direct")
    commit(repo, "direct\n\n\x1e" + branch_sha + "\x1f\x1f\x1fX <x@x>\x1fforged\n\n" + D("G0", "H3", "A3"),
           D("G0", "H2", "A0"))
    lines = by_line(result(repo)[0])
    assert lines[2].declaration.short() == "G0 H2 A0" and lines[2].kinds == ("file", "file", "file")


def test_a_rebase_preview_is_not_exempt(repo):
    first = git(repo, "rev-parse", "HEAD")
    text = (repo / "SIGNOFF.toml").read_text().replace(
        "enabled = true", f'enabled = true\nmerge-method = "rebase"\nrequire-trailers-since = "{first}"')
    (repo / "SIGNOFF.toml").write_text(text)
    commit(repo, "config", D("G0", "H2", "A0"))
    git(repo, "checkout", "-q", "-b", "pr")
    edit_lines(repo, [3])
    commit(repo, "forgot the declaration")
    assert by_line(result(repo)[0])[3].errors == []  # on the branch itself, nothing is about to land
    git(repo, "checkout", "-q", "--detach", "main")
    git(repo, "merge", "-q", "--no-ff", "pr", "-m", "preview")
    line = by_line(result(repo)[0])[3]
    assert any("forgot the declaration" in e and "require-trailers-since" in e for e in line.errors)


def test_attestation_of_a_path_renamed_away_and_recreated(repo):
    blob = git(repo, "hash-object", "solver.py")
    git(repo, "mv", "solver.py", "moved.py")
    commit(repo, "rename", D("G0", "H2", "A0"))
    write(repo, "solver.py", "new file\n")
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[attestations]]\npath = "solver.py"\nblob = "{blob}"\nHuman-Review = "H3"\nReviewed-by = "P"\n')
    commit(repo, "new solver", D("G0", "H2", "A0"))
    project = Project(repo)
    project.results(quiet=True)
    assert any("was renamed to moved.py" in p for p in project.history_problems)


def test_what_is_landed_follows_the_default_branch_not_the_subject_or_the_environment(repo, monkeypatch):
    first = git(repo, "rev-parse", "HEAD")
    text = (repo / "SIGNOFF.toml").read_text().replace("enabled = true", f'enabled = true\nrequire-trailers-since = "{first}"')
    (repo / "SIGNOFF.toml").write_text(text)
    commit(repo, "config", D("G0", "H2", "A0"))
    git(repo, "checkout", "-q", "-b", "pr")
    edit_lines(repo, [3])
    commit(repo, "undeclared")
    git(repo, "checkout", "-q", "--detach", "main")
    git(repo, "merge", "-q", "--no-ff", "pr", "-m", "any subject")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    assert by_line(result(repo)[0])[3].errors == []  # not on main: the pull request isn't merged yet
    git(repo, "checkout", "-q", "-B", "main")  # the same commit, now main's
    assert any("require-trailers-since" in e for e in by_line(result(repo)[0])[3].errors)
    toml = (repo / "SIGNOFF.toml").read_text().replace("enabled = true", 'enabled = true\ndefault-branch = "trunk"')
    (repo / "SIGNOFF.toml").write_text(toml)
    project = Project(repo)
    project.results(quiet=True)
    assert any("default-branch: there is no branch trunk" in p for p in project.history_problems)


# ------------------------------------------------------------------ 0.10.1 review
def test_an_attestation_fills_the_landing_todo(repo, capsys):
    from aisignoff.cli import main
    edit_lines(repo, [2])
    commit(repo, "agent", "AI-Generation: G3\nAssisted-by: M\nHuman-Review: TODO\nAI-Review: A1\nAI-Reviewed-by: M")
    assert "TODO" in by_line(result(repo)[0])[2].declaration.short()
    assert main(["--root", str(repo), "attest", str(repo / "solver.py"), "-H", "H2", "--reviewed-by", "Jane"]) == 0
    line = by_line(result(repo)[0])[2]
    assert line.declaration.short() == "G3 H2 A1" and line.errors == []


def test_comments_in_code_spans_and_unclosed_comments_hide_nothing():
    tr = D("G3", "H1", "A1")
    for body in (f"Skip `<!--` comments in PR bodies.\n\n{tr}\n", f"Text\n<!-- never closed\n\n{tr}\n"):
        assert {i: p.level for i, p in parse_trailers(body, "c").items()} == {0: "G3", 1: "H1", 2: "A1"}, body


def test_a_stray_fence_keeps_earlier_blocks_closed():
    body = "Example:\n```\nHuman-Review: H3\nReviewed-by: Jane Doe\n```\n\n" + D("G3", "H1", "A1") + "\n```\n"
    pieces = parse_trailers(body, "c")
    assert pieces[1].level == "H1" and pieces[1].names == ("Jane",) and not pieces[1].problems


def test_diff_declare_after_merging_the_base_into_the_branch(repo, capsys):
    from aisignoff.cli import main
    git(repo, "checkout", "-q", "-b", "feat")
    edit_lines(repo, [2])
    commit(repo, "agent part")
    git(repo, "checkout", "-q", "main")
    write(repo, "b.py", "main moved on\n")
    commit(repo, "direct on main", D("G0", "H3", "A0"))
    git(repo, "checkout", "-q", "feat")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge branch 'main' into feat", "main")
    capsys.readouterr()
    assert main(["--root", str(repo), "diff", "main", "--json", "-g", "G3", "--assisted-by", "M", "-H", "H1",
                 "--reviewed-by", "J", "-a", "A1", "--ai-reviewed-by", "M"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total"]["levels_added"]["AI-Generation"] == {"G3": 1}
    r = next(r for r in Project(repo).results(quiet=True) if r.path == "b.py")
    assert r.parts[0].declaration.short() == "G0 H3 A0"  # main's line stays main's


def test_a_commit_declaring_g0_with_a1_itself_is_an_error(repo):
    edit_lines(repo, [2])
    commit(repo, "by hand", "AI-Generation: G0\nHuman-Review: H1\nReviewed-by: J\nAI-Review: A1\nAI-Reviewed-by: M")
    line = by_line(result(repo)[0])[2]
    assert line.declaration.short() == "G0 H1 A1" and any("G0 has no generating AI session" in e for e in line.errors)


