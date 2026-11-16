"""The fixes of 1.0.0rc8, from the two reviews of 1.0.0rc7: the report must be a file of the change, a
landed severe finding is cleared by its fix, a commit is judged by the threshold it landed under, the
findings line is read only next to A2 and A3, .git-blame-ignore-revs is protected, and the model
name heuristics."""
import pytest

from aisignoff.cli import main
from aisignoff.model import Declaration, _same_model, mentions_self_check, validate

from test_aisignoff import write
from test_history import BASE_TOML, commit, git, repo  # noqa: F401

G3_A2 = ("AI-Generation: G3\nAssisted-by: Claude Opus (Anthropic)\nHuman-Review: H1\nReviewed-by: Jane\n"
         "AI-Review: A2\nAI-Reviewed-by: GPT Sol (OpenAI), {report}\nAI-Review-Findings: {findings}\n")


def a2(findings="none", report="reviews/r.md"):
    return G3_A2.format(findings=findings, report=report)


def lint(root, *args, capsys):
    capsys.readouterr()
    code = main(["--root", str(root), "lint", *args])
    return code, capsys.readouterr().out


def pr(root, tmp_path, text, capsys, *more):
    desc = tmp_path.parent / f"{tmp_path.name}-description.md"
    desc.write_text(text)
    return lint(root, "--declare-from", str(desc), "--base", "main", "--author", "jane", *more, capsys=capsys)


# ------------------------------------------------------------------ the report is a file of the change
@pytest.fixture
def feature(repo):
    write(repo, "reviews/old.md", "# an earlier review\n")
    commit(repo, "an earlier pull request's report", a2(report="reviews/old.md"))
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "solver.py", "changed\n")
    commit(repo, "change")
    return repo


def test_the_report_must_be_added_or_modified_by_the_change(feature, tmp_path, capsys):
    code, out = pr(feature, tmp_path, a2(report="reviews/old.md"), capsys)
    assert code == 1 and "reviews/old.md isn't part of this change: it was there before" in out
    for name in ("README.md", "SIGNOFF.toml", "solver.py"):
        write(feature, "README.md", "# readme\n") if name == "README.md" else None
        if name == "README.md":
            commit(feature, "readme on the branch")  # part of the change now: skip, checked below
            continue
        code, out = pr(feature, tmp_path, a2(report=name), capsys)
        assert code == 1 and f"{name} isn't part of this change" in out or name == "solver.py"
    code, out = pr(feature, tmp_path, a2(report="../../../../../../../../etc/hostname"), capsys)
    assert code == 1 and "is outside the repository" in out
    # a report of this change, also one whose path has a space, or one not committed yet
    write(feature, "reviews/pull 7.md", "# this review\n")
    assert pr(feature, tmp_path, a2(report="reviews/pull 7.md"), capsys)[0] == 0
    write(feature, "reviews/new.md", "# this review\n")
    assert pr(feature, tmp_path, a2(report="reviews/new.md"), capsys)[0] == 0
    # an earlier report that the change modifies counts as this review's
    write(feature, "reviews/old.md", "# replaced by this review\n")
    assert pr(feature, tmp_path, a2(report="reviews/old.md"), capsys)[0] == 0


def test_a_report_without_a_model_fails(feature, tmp_path, capsys):
    write(feature, "reviews/new.md", "# this review\n")
    text = a2().replace("GPT Sol (OpenAI), reviews/r.md", "reviews/new.md")
    code, out = pr(feature, tmp_path, text, capsys)
    assert code == 1 and "names the report, but not the reviewing model" in out


# ------------------------------------------------------------------ the findings line
def test_the_findings_line_is_read_only_for_a2_and_a3(feature, tmp_path, capsys):
    a1 = ("AI-Generation: G3\nAssisted-by: Claude Opus (Anthropic)\nHuman-Review: H1\nReviewed-by: Jane\n"
          "AI-Review: A1\nAI-Reviewed-by: Claude Opus, new session\n")
    for value in ("n/a", "-", "major", ""):
        assert pr(feature, tmp_path, a1 + f"AI-Review-Findings: {value}\n", capsys)[0] == 0
    write(feature, "reviews/new.md", "# this review\n")
    code, out = pr(feature, tmp_path, a2("critical", "reviews/new.md") + "AI-Review-Findings: none\n", capsys)
    assert code == 1 and "found a critical problem" in out
    assert pr(feature, tmp_path, a2("minor", "reviews/new.md") + "AI-Review-Findings:\n", capsys)[0] == 0


# ------------------------------------------------------------------ a severe finding that has landed
def test_a_later_fix_with_a_new_review_clears_a_landed_finding(repo, capsys):
    write(repo, "reviews/r.md", "# review\n")
    write(repo, "other.py", "a\nb\n")
    commit(repo, "the change, landed with its finding", a2("major"))
    code, out = lint(repo, capsys=capsys)
    assert code == 1 and "found a major problem" in out and "clears this" in out
    # a later change of another file, even with a review, doesn't
    write(repo, "unrelated.py", "x\n")
    commit(repo, "unrelated", a2("none"))
    assert lint(repo, capsys=capsys)[0] == 1
    # the fix: one line of one of its files, reviewed again
    write(repo, "other.py", "a\nfixed\n")
    commit(repo, "the fix", a2("none"))
    code, out = lint(repo, capsys=capsys)
    assert code == 0, out


def test_a_fix_that_is_reviewed_again_isnt_enough_with_a_severe_finding(repo, capsys):
    write(repo, "reviews/r.md", "# review\n")
    write(repo, "other.py", "a\nb\n")
    commit(repo, "the change, landed with its finding", a2("major"))
    write(repo, "reviews/r.md", "# review, still bad\n")
    commit(repo, "a fix whose review found another major", a2("major"))
    code, out = lint(repo, capsys=capsys)
    assert code == 1 and "(the change, landed with its finding)" in out and "(a fix whose review" in out


def test_the_fix_pull_request_passes_while_main_has_the_finding(repo, tmp_path, capsys):
    write(repo, "reviews/r.md", "# review\n")
    commit(repo, "the change, landed with its finding", a2("major"))
    git(repo, "checkout", "-q", "-b", "fix")
    write(repo, "reviews/r.md", "# the new review\n")
    commit(repo, "the fix")
    code, out = pr(repo, tmp_path, a2("none"), capsys)
    assert code == 0, out
    code, out = pr(repo, tmp_path, a2("major"), capsys)
    assert code == 1


def test_an_attestation_clears_a_landed_finding_for_its_file(repo, capsys, monkeypatch):
    monkeypatch.chdir(repo)
    write(repo, "reviews/r.md", "# review\n")
    write(repo, "solver.py", "".join(f"agent {i}\n" for i in range(1, 11)))
    commit(repo, "the change, landed with its finding", a2("major"))
    assert lint(repo, capsys=capsys)[0] == 1
    assert main(["--root", str(repo), "attest", "solver.py", "-a", "A2",
                 "--ai-reviewed-by", "GPT Fable (OpenAI), reviews/r2.md"]) == 0
    code, out = lint(repo, capsys=capsys)
    errors = out.split("files have")[0]
    assert "solver.py" not in errors and "reviews/r.md" in errors, out  # only the file it attests


def test_a_landed_commit_is_judged_by_the_threshold_it_landed_under(repo, capsys):
    write(repo, "reviews/r.md", "# review\n")
    commit(repo, "fine under the default", a2("minor"))
    assert lint(repo, capsys=capsys)[0] == 0
    write(repo, "SIGNOFF.toml", BASE_TOML + '\n[review]\nrecheck = "minor"\n')
    commit(repo, "tighten the threshold", a2("minor", "SIGNOFF.toml"))  # lands under major: fine
    code, out = lint(repo, capsys=capsys)
    assert code == 0, out
    write(repo, "reviews/r.md", "# review 2\n")
    commit(repo, "lands under minor", a2("minor"))
    code, out = lint(repo, capsys=capsys)
    assert code == 1 and "a finding from minor on" in out


# ------------------------------------------------------------------ .git-blame-ignore-revs
def test_a_pull_request_cant_change_the_blame_ignore_file(repo, tmp_path, capsys):
    write(repo, "solver.py", "".join(f"agent {i}\n" for i in range(1, 11)))
    sha = commit(repo, "agent rewrite", "AI-Generation: G3\nAssisted-by: M\nHuman-Review: H0\nReviewed-by: Jane\n"
                                        "AI-Review: A0\n")
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, ".git-blame-ignore-revs", sha + "\n")
    commit(repo, "ignore it")
    text = ("AI-Generation: G0\nHuman-Review: H2\nReviewed-by: jane\nAI-Review: A0\n")
    code, out = pr(repo, tmp_path, text, capsys)
    assert code == 1 and "edits the entries of .git-blame-ignore-revs" in out
    code, out = pr(repo, tmp_path, text, capsys, "--allow-policy-change")
    assert code == 0 and "edits the entries of .git-blame-ignore-revs (allowed" in out
    # a comment changes no entry
    git(repo, "checkout", "-q", "main")
    write(repo, ".git-blame-ignore-revs", sha + "\n")
    commit(repo, "ignore it on main")
    git(repo, "checkout", "-q", "feature")
    git(repo, "merge", "-q", "main")
    write(repo, ".git-blame-ignore-revs", "# the agent's rewrite\n" + sha + "\n")
    commit(repo, "a comment")
    assert pr(repo, tmp_path, text, capsys)[0] == 0


# ------------------------------------------------------------------ model names
@pytest.mark.parametrize("assisted, reviewer, same", [
    ("Claude Opus (Anthropic)", "claude-opus-5-5, reviews/r.md", True),
    ("claude-opus-5-5", "Claude Opus 5.5 (Anthropic), new session", True),
    ("Claude Opus 5.5 (Anthropic)", "Claude-Opus-5.5, new session", True),
    ("Claude Opus (Anthropic)", "anthropic/claude-opus-5.5", True),
    ("Claude Opus (Anthropic)", "Claude Code (Opus 5.5), reviews/r.md", True),
    ("Claude Opus (Anthropic)", "Claude Opus 5.5 Thinking, reviews/r.md", True),
    ("Claude Opus (Anthropic)", "Opus 5.5 via Claude Code, reviews/r.md", True),
    ("Opus", "Claude Opus 5.5 (Anthropic), reviews/r.md", True),
    ("Claude Code, Claude Opus 5.5 (Anthropic)", "Claude Opus 5.5, reviews/r.md", True),
    ("GPT Sol (OpenAI)", "gpt-sol-2, reviews/r.md", True),
    ("GPT-5.5 Sol (OpenAI)", "GPT 5.5 Sol (OpenAI), new session", True),
    ("Claude Opus (Anthropic)", "Claude Fable 5.2 (Anthropic), reviews/r.md", False),
    ("Claude Code (Claude Opus 5.5)", "Claude Code (Claude Fable 5.2), reviews/r.md", False),
    ("Claude Opus (Anthropic)", "Claude (Fable 5.2), reviews/r.md", False),
    ("Claude", "Claude Fable, reviews/r.md", False),
    ("X", "X Pro, fresh", False),
])
def test_model_names(assisted, reviewer, same):
    assert _same_model(reviewer, (assisted,)) is same


@pytest.mark.parametrize("text, self_check", [
    ("Claude Opus 5.5, self-check", True),
    ("Claude Opus 5.5, the same session", True),
    ("Claude Opus 5.5, new session without the generating session", False),
    ("Claude Opus 5.5, new session, independent of the generating session", False),
    ("Claude Opus 5.5, new session (not the same session)", False),
    ("GPT Sol (OpenAI), not the generating session, reviews/r.md", False),
    ("Claude Opus 5.5, new session without access to the generating session", False),
    ("Claude Fable, outside the generating session", False),
])
def test_self_check_words(text, self_check):
    assert mentions_self_check(text) is self_check
    d = Declaration("G3", "H1", "A1", ("Claude Opus (Anthropic)",), ("Jane",), (text,), "test")
    assert any("self-check" in e for e in validate(d)) is self_check


# ------------------------------------------------------------------ the open items of the first round
def test_a_respelled_annotation_path_is_caught_when_the_version_changes(repo, tmp_path, capsys):
    old = BASE_TOML.replace("version = 4", "version = 3").replace('AI-Review = "A0"', 'AI-Review = "A2"\n'
                                                                    'AI-Reviewed-by = "M, new session"')
    write(repo, "SIGNOFF.toml", old)
    commit(repo, "the scale before")
    git(repo, "checkout", "-q", "-b", "feature")
    # the same files, with the path written another way, and the level not converted
    write(repo, "SIGNOFF.toml", old.replace("version = 3", "version = 4").replace('path = "**"', 'path = "*"'))
    commit(repo, "version 4")
    text = "AI-Generation: G0\nHuman-Review: H2\nReviewed-by: jane\nAI-Review: A0\n"
    code, out = pr(repo, tmp_path, text, capsys, "--allow-policy-change")
    assert code == 1 and "the entry for * gives solver.py AI-Review A2 now, and A1 before" in out


def test_a_pull_request_is_read_on_the_base_branchs_scale(repo, tmp_path, capsys):
    """A pull request that changes version 4 to 3 is still read, and checked, on version 4's scale."""
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "SIGNOFF.toml", BASE_TOML.replace("version = 4", "version = 3"))
    write(repo, "solver.py", "changed\n")
    commit(repo, "back to version 3")
    code, out = pr(repo, tmp_path, a2("critical", "reviews/none.md"), capsys, "--allow-policy-change")
    assert code == 1 and "found a critical problem" in out and "isn't in this change" in out


def test_a_misspelt_findings_line_in_a_landed_commit_is_a_warning(repo, capsys):
    write(repo, "reviews/r.md", "# review\n")
    commit(repo, "typo", a2("none").replace("AI-Review-Findings: none", "AI-Review-Finding: major"))
    code, out = lint(repo, capsys=capsys)
    assert code == 0 and "has a line 'AI-Review-Finding: major' that looks like 'AI-Review-Findings:'" in out
    assert lint(repo, "--strict", capsys=capsys)[0] == 1
