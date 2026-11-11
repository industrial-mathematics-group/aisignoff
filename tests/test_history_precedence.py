"""How the declarations around a line combine: generation from the most specific, reviews from
the highest; the message formats that declare (scenarios of the second declaration review)."""
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
    s = f"AI-Generation: {g}\nHuman-Review: {h}\nAI-Review: {a}\nReviewed-by: {by}\nAI-Reviewed-by: {ai}"
    return s + ("\nAssisted-by: M" if g != "G0" else "")


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
def test_reviews_take_the_highest_and_generation_the_most_specific(repo):
    git(repo, "checkout", "-q", "-b", "feature")
    edit_lines(repo, [2, 3])
    commit(repo, "agent", D("G3", "H0", "A1", ai="M, self-check"))
    edit_lines(repo, [4], text="hand")
    commit(repo, "by hand", "AI-Generation: G0\nHuman-Review: H3\nReviewed-by: Bob")
    edit_lines(repo, [5])
    commit(repo, "todo", "AI-Generation: G3\nAssisted-by: M\nHuman-Review: TODO\nAI-Review: A1\nAI-Reviewed-by: M")
    merge(repo, "feature", "Merge feature\n\n" + D("G3", "H2", "A2"))
    lines = by_line(result(repo)[0])
    assert lines[2].declaration.short() == "G3 H2 A2"  # the pull request's later review counts
    assert lines[2].kinds == ("branch", "commit", "commit")
    assert lines[4].declaration.short() == "G0 H3 A2" and lines[4].declaration.reviewed_by == ("Bob",)
    assert lines[5].declaration.short() == "G3 H2 A2" and lines[5].errors == []  # TODO yields
    merge_sha = git(repo, "rev-parse", "HEAD")
    with open(repo / "SIGNOFF.toml", "a") as f:  # a correction of the merge reaches all its lines
        f.write(f'\n[[commits]]\ncommit = "{merge_sha}"\nHuman-Review = "H3"\nReviewed-by = "Rita"\n')
    lines = by_line(result(repo)[0])
    assert {lines[n].declaration.short() for n in (2, 3, 5)} == {"G3 H3 A2"}


def test_a_partial_declaration_doesnt_take_the_rest_from_the_file(repo):
    edit_lines(repo, [2])
    commit(repo, "AI change", "AI-Generation: G3\nAssisted-by: M")
    r, _ = result(repo)
    line = by_line(r)[2]
    assert line.declaration.short() == "G3 -- --" and line.kinds == ("commit", "required", "required")
    assert any("declares levels, but no Human-Review" in e for e in line.errors)
    assert shares(r)["G0 H2 A0"] == 9  # lines of commits that declare nothing keep the file's levels


def test_nested_merges_declare_their_lines(repo):
    git(repo, "checkout", "-q", "-b", "a")
    edit_lines(repo, [2])
    commit(repo, "AI part of A")
    git(repo, "checkout", "-q", "-b", "b")
    edit_lines(repo, [3], text="hand")
    commit(repo, "by hand")
    git(repo, "checkout", "-q", "a")
    git(repo, "merge", "-q", "--no-ff", "b", "-m", "Merge B into A\n\n" + D("G0", "H3", "A0", by="Bob"))
    merge(repo, "a", "Merge A\n\n" + D("G3", "H2", "A2"))
    lines = by_line(result(repo)[0])
    assert lines[2].declaration.short() == "G3 H2 A2"
    assert lines[3].declaration.short() == "G0 H3 A2"  # hand-written (B), Bob's review, A's AI review


def test_git_pull_merge_on_main_keeps_the_pull_requests(repo):
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
    lines = by_line(result(repo)[0])
    assert lines[2].declaration.short() == "G3 H2 A2" and lines[9].declaration.short() == "G0 H3 A0"


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
def preview(repo, method):
    text = (repo / "SIGNOFF.toml").read_text().replace("enabled = true", f'enabled = true\nmerge-method = "{method}"')
    (repo / "SIGNOFF.toml").write_text(text)
    commit(repo, "config", D("G0", "H2", "A0"))
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "pr")
    edit_lines(repo, [2])
    commit(repo, "agent", "AI-Generation: G3\nAssisted-by: M\nHuman-Review: TODO\nAI-Review: A1\nAI-Reviewed-by: M")
    merge(repo, "pr", f"Merge {'a' * 40} into {'b' * 40}")
    project = Project(repo)
    from aisignoff.model import Declaration
    declared = Declaration.from_mapping({"AI-Generation": "G3", "Assisted-by": ["M"], "Human-Review": "H2",
                                         "Reviewed-by": ["Jane"], "AI-Review": "A2",
                                         "AI-Reviewed-by": ["M, fresh"]}, "x")
    r = next(r for r in project.results(declared=declared, declared_after=base) if r.path == "solver.py")
    return by_line(r)[2].declaration.short()


def test_preview_of_a_merge(repo):
    assert preview(repo, "merge") == "G3 H2 A2"


def test_preview_of_a_squash_ignores_the_branch_commits(repo):
    assert preview(repo, "squash") == "G3 H2 A2"


def test_preview_of_a_rebase_ignores_the_description(repo):
    assert preview(repo, "rebase") == "G3 TODO A1"


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
