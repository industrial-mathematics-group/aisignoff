"""lint --declare-from as the check of a pull request before the merge: the description must be complete
on its own, a bot needs a responsible person, the base branch's rules apply and the change can't alter
them, and a repository without SIGNOFF.toml has its description checked alone."""
import json

import pytest

from aisignoff.cli import main
from aisignoff.pullrequest import is_bot, responsible_person

from test_aisignoff import write
from test_history import BASE_TOML, commit, git, repo  # noqa: F401

FILLED = """Change things.

- [x] **G0** Written by a human, without AI
- [ ] **G3** AI-autonomous
- [ ] **Claude Opus** (Anthropic)
- [x] **H0** I checked the result as a whole
- [x] **H1** I ran the tests
- [ ] **A1** A new AI session checked the whole change. Model, if not one of the above:
- [ ] **A2** A different, capable model did that check. Model:
"""
EMPTY = FILLED.replace("[x]", "[ ]")


@pytest.fixture
def branch(repo):
    """A feature branch off main, as a pull request's checkout (main is its base)."""
    git(repo, "checkout", "-q", "-b", "feature")
    return repo


def lint(root, tmp_path, text, *more, capsys=None):
    desc = tmp_path / "description.md"
    desc.write_text(text)
    if capsys:
        capsys.readouterr()
    code = main(["--root", str(root), "lint", "--declare-from", str(desc), "--base", "main", *more])
    return code, (capsys.readouterr().out if capsys else "")


def test_a_change_to_signoff_toml_alone_needs_a_description(branch, tmp_path, capsys):
    write(branch, "SIGNOFF.toml", BASE_TOML + '\n[[annotations]]\npath = "solver.py"\nAI-Generation = "G0"\n'
          'Human-Review = "H3"\nAI-Review = "A0"\nReviewed-by = "Jane"\n')
    commit(branch, "raise the review of solver.py")
    code, out = lint(branch, tmp_path, EMPTY, "--author", "jane", capsys=capsys)
    assert code == 1 and "the pull request description: AI-Generation is still TODO" in out
    code, out = lint(branch, tmp_path, "Nothing here.\n", "--author", "jane", capsys=capsys)
    assert code == 1 and "the pull request description: it declares nothing" in out
    assert lint(branch, tmp_path, FILLED, "--author", "jane")[0] == 0


def test_names_the_levels_need(branch, tmp_path, capsys):
    write(branch, "solver.py", "changed\n")
    commit(branch, "change")
    g3 = FILLED.replace("[x] **G0**", "[ ] **G0**").replace("[ ] **G3**", "[x] **G3**")
    code, out = lint(branch, tmp_path, g3, "--author", "jane", capsys=capsys)
    assert code == 1 and "G3 needs Assisted-by" in out
    g3 = g3.replace("[ ] **Claude Opus**", "[x] **Claude Opus**")
    assert lint(branch, tmp_path, g3, "--author", "jane")[0] == 0   # no independent AI review: A0
    a1 = g3.replace("[ ] **A1**", "[x] **A1**")
    assert lint(branch, tmp_path, a1, "--author", "jane")[0] == 0   # A1 names the model that wrote it
    code, out = lint(branch, tmp_path, g3.replace("[ ] **A2**", "[x] **A2**"), "--author", "jane", capsys=capsys)
    assert code == 1 and "A2 needs AI-Reviewed-by" in out           # a different model has to be named
    code, out = lint(branch, tmp_path, a1.replace("Model:", "Model: Claude Opus (Anthropic)")
                     .replace("[ ] **A2**", "[x] **A2**"), "--author", "jane", capsys=capsys)
    assert code == 1 and "names only models that wrote it" in out
    assert lint(branch, tmp_path, g3.replace("Model:", "Model: GPT Sol (OpenAI)").replace("[ ] **A2**", "[x] **A2**"),
                "--author", "jane")[0] == 0
    # the levels of human review build on each other: H1 without H0 is refused before the merge
    code, out = lint(branch, tmp_path, FILLED.replace("[x] **H0**", "[ ] **H0**"), "--author", "jane", capsys=capsys)
    assert code == 1 and "ticks H1 but not H0" in out
    code, out = lint(branch, tmp_path, FILLED, capsys=capsys)  # no --author: nobody is responsible
    assert code == 1 and "Human-Review needs Reviewed-by" in out


def test_a_bot_names_the_responsible_person(branch, tmp_path, capsys):
    write(branch, "solver.py", "changed\n")
    commit(branch, "change")
    code, out = lint(branch, tmp_path, FILLED, "--author", "github-actions[bot]", capsys=capsys)
    assert code == 1 and "opened by the bot account github-actions[bot]" in out
    with_person = FILLED + "\nResponsible person: @jane\n"
    assert lint(branch, tmp_path, with_person, "--author", "signoff-bot[bot]")[0] == 0
    code, out = lint(branch, tmp_path, FILLED + "\nResponsible person: @other[bot]\n",
                     "--author", "github-actions[bot]", capsys=capsys)
    assert code == 1 and "is a bot account; name a human" in out
    code, out = lint(branch, tmp_path, with_person.replace("@jane", "@other"), "--author", "jane", capsys=capsys)
    assert code == 0 and "is only read for pull requests opened by bots" in out
    # the reviewer is the responsible person, as the report shows
    desc = tmp_path / "d.md"
    desc.write_text(with_person)
    capsys.readouterr()
    assert main(["--root", str(branch), "report", "--json", "--declare-from", str(desc), "--author",
                 "github-actions[bot]", "--base", "main"]) == 0
    pr = json.loads(capsys.readouterr().out)["pull_request"]
    assert pr["applies"] and pr["Reviewed-by"] == ["jane"] and pr["Human-Review"] == "H1" and pr["errors"] == []


def test_the_base_branch_sets_the_rules(branch, tmp_path, capsys):
    git(branch, "checkout", "-q", "main")
    write(branch, "SIGNOFF.toml", BASE_TOML + '\n[policy]\n"*" = { human = "H1" }\n')
    commit(branch, "policy")
    git(branch, "checkout", "-q", "feature")
    git(branch, "merge", "-q", "main")
    write(branch, "SIGNOFF.toml", BASE_TOML + '\n[policy]\n"*" = { human = "H0" }\n')
    write(branch, "solver.py", "changed\n")
    commit(branch, "lower the policy")
    h0 = FILLED.replace("[x] **H1**", "[ ] **H1**")
    code, out = lint(branch, tmp_path, h0, "--author", "jane", capsys=capsys)
    assert code == 1 and "G0 requires at least H1 by policy" in out   # the base's policy
    assert "the change alters [policy] in SIGNOFF.toml" in out
    # a maintainer's change may alter the policy, but can't lower the bar for itself
    code, out = lint(branch, tmp_path, h0, "--author", "jane", "--allow-policy-change", capsys=capsys)
    assert code == 1 and "G0 requires at least H1 by policy" in out
    assert "the change alters [policy] in SIGNOFF.toml, which only" not in out
    code, out = lint(branch, tmp_path, FILLED, "--author", "jane", "--allow-policy-change", capsys=capsys)
    assert code == 0, out   # it meets the base's policy: the new one applies to the pull requests after it
    assert "the change alters [policy] in SIGNOFF.toml (allowed by --allow-policy-change)" in out
    assert "still checked under the base branch's [policy] (main)" in out
    # after it has landed, the lower policy is main's
    git(branch, "checkout", "-q", "main")
    git(branch, "merge", "-q", "--no-ff", "-m", "Merge the policy change\n\nAI-Generation: G0\nHuman-Review: H1\n"
        "AI-Review: A0\nReviewed-by: jane", "feature")
    git(branch, "checkout", "-q", "-b", "next")
    write(branch, "solver.py", "changed again\n")
    commit(branch, "next change")
    assert lint(branch, tmp_path, h0, "--author", "jane")[0] == 0


@pytest.mark.parametrize("change, what", [
    ('exclude = ["solver.py"]\n', "exclude"),
    (None, "[history]"),
])
def test_exclude_and_history_are_protected(branch, tmp_path, capsys, change, what):
    toml = BASE_TOML.replace("version = 4\n", "version = 4\n" + change) if change else \
        BASE_TOML.replace("enabled = true\n", 'enabled = true\nundeclared = "error"\n')
    write(branch, "SIGNOFF.toml", toml)
    commit(branch, "change settings")
    code, out = lint(branch, tmp_path, FILLED, "--author", "jane", capsys=capsys)
    assert code == 1 and f"the change alters {what} in SIGNOFF.toml" in out


def test_a_first_signoff_toml_is_allowed(tmp_path, capsys):
    root = tmp_path / "r"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "T")
    write(root, "a.py", "1\n")
    commit(root, "start")
    git(root, "checkout", "-q", "-b", "feature")
    write(root, "SIGNOFF.toml", BASE_TOML + '\n[policy]\n"*" = { human = "H1" }\n')
    commit(root, "declare")
    code, out = lint(root, tmp_path, FILLED, "--author", "jane", capsys=capsys)
    assert code == 0, out


def test_without_signoff_toml_only_the_description_is_checked(tmp_path, capsys):
    root = tmp_path / "r"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "T")
    write(root, "Pkg.jl", "module Pkg end\n")
    commit(root, "start")
    git(root, "checkout", "-q", "-b", "feature")
    write(root, "Pkg.jl", "module Pkg\nend\n")
    commit(root, "change")
    code, out = lint(root, tmp_path, FILLED, "--author", "jane", capsys=capsys)
    assert code == 0 and "files aren't checked" in out
    code, out = lint(root, tmp_path, EMPTY, "--author", "jane", capsys=capsys)
    assert code == 1 and "Human-Review is still TODO" in out
    assert main(["--root", str(root), "lint"]) == 1   # without --declare-from, files still need declarations


def test_removing_signoff_toml_is_protected(branch, tmp_path, capsys):
    git(branch, "rm", "-q", "SIGNOFF.toml")
    commit(branch, "remove")
    code, out = lint(branch, tmp_path, FILLED, "--author", "jane", capsys=capsys)
    assert code == 1 and "the change removes SIGNOFF.toml" in out


def test_a_pull_request_into_another_branch_is_not_checked(branch, tmp_path, capsys):
    git(branch, "checkout", "-q", "-b", "stacked")
    write(branch, "solver.py", "changed\n")
    commit(branch, "change")
    desc = tmp_path / "d.md"
    desc.write_text(EMPTY)
    write(branch, "solver.py", "changed\n")
    git(branch, "checkout", "-q", "feature")
    write(branch, "other.py", "x\n")
    commit(branch, "feature work")
    git(branch, "checkout", "-q", "stacked")
    git(branch, "merge", "-q", "feature")
    capsys.readouterr()
    assert main(["--root", str(branch), "lint", "--declare-from", str(desc), "--base", "feature",
                 "--author", "jane"]) == 0
    assert "doesn't go into the default branch" in capsys.readouterr().out


def test_helpers():
    assert is_bot("github-actions[bot]") and is_bot("My-App[BOT]") and not is_bot("jane")
    assert responsible_person("x\nResponsible person: @jane-doe\n") == "jane-doe"
    assert responsible_person("```\nResponsible person: @jane\n```\n") is None
    assert responsible_person("<!-- Responsible person: @jane -->\n") is None


def test_allowed_removal_of_signoff_toml_is_said(branch, tmp_path, capsys):
    git(branch, "rm", "-q", "SIGNOFF.toml")
    commit(branch, "remove SIGNOFF.toml")
    code, out = lint(branch, tmp_path, FILLED, "--author", "jane", capsys=capsys)
    assert code == 1 and "the change removes SIGNOFF.toml" in out
    code, out = lint(branch, tmp_path, FILLED, "--author", "jane", "--allow-policy-change", capsys=capsys)
    assert code == 0 and "the change removes SIGNOFF.toml (allowed by --allow-policy-change)" in out


COMMIT_ENTRY = ('\n[[commits]]\ncommit = "{c}"\nAI-Generation = "G3"\nAssisted-by = ["Model A"]\n'
                'Human-Review = "H0"\nReviewed-by = ["Jane"]\nAI-Review = "A1"\n')


def test_a_commits_entry_is_checked_against_the_policy_also_without_lines(repo, tmp_path, capsys):
    """A correction for a commit that owns no checked line (it changed only SIGNOFF.toml) still has to
    meet the rules: playground PR #9 recorded a G3 with less review than its policy needs for G3."""
    write(repo, "SIGNOFF.toml", BASE_TOML + '\n[policy]\nG3 = { human = "H1", ai = "A2" }\n')
    target = commit(repo, "policy", "AI-Generation: G0\nHuman-Review: H2\nAI-Review: A0\nReviewed-by: Jane")
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "SIGNOFF.toml", (repo / "SIGNOFF.toml").read_text() + COMMIT_ENTRY.format(c=target[:7]))
    commit(repo, "correct the policy commit")
    code, out = lint(repo, tmp_path, FILLED, "--author", "jane", capsys=capsys)
    assert code == 1, out
    assert f"[[commits]] entry 1 ({target[:7]}): G3 requires at least H1 by policy (declared H0)" in out
    assert "G3 requires at least A2" in out and "A1 needs AI-Reviewed-by" in out
    good = COMMIT_ENTRY.replace('"H0"', '"H1"').replace('"A1"', '"A2"\nAI-Reviewed-by = ["Model B"]')
    write(repo, "SIGNOFF.toml", BASE_TOML + '\n[policy]\nG3 = { human = "H1", ai = "A2" }\n' + good.format(c=target[:7]))
    commit(repo, "a valid correction")
    assert lint(repo, tmp_path, FILLED, "--author", "jane")[0] == 0
    # a partial entry is checked together with the commit's own message: G1 without a model breaks a built-in rule
    write(repo, "SIGNOFF.toml", BASE_TOML + f'\n[[commits]]\ncommit = "{target[:7]}"\nAI-Generation = "G1"\n')
    commit(repo, "partial")
    capsys.readouterr()
    code, out = main(["--root", str(repo), "lint"]), capsys.readouterr().out
    assert code == 1 and f"[[commits]] entry 1 ({target[:7]}): " in out, out
