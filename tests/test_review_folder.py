"""The review folder (default reviews/): records of independent AI reviews, never content. It needs
no declaration, a change may only add files to it, and its attestation files (*.toml) attest whole
files (blob) or the lines one commit landed (commit), so that a review lands in a pull request of
its own without touching SIGNOFF.toml."""
import pytest

from aisignoff.cli import main
from aisignoff.config import ConfigError, load
from aisignoff.model import counted_findings
from aisignoff.project import Project

from test_aisignoff import write
from test_history import commit, edit_lines, git, repo  # noqa: F401

REVIEWED = ("AI-Generation: G3\nAssisted-by: Claude Opus (Anthropic)\nHuman-Review: H1\nReviewed-by: Jane\n"
            "AI-Review: A2\nAI-Reviewed-by: GPT Sol (OpenAI), reviews/r.md\nAI-Review-Findings: major\n")
UNREVIEWED = ("AI-Generation: G3\nAssisted-by: Claude Opus (Anthropic)\nHuman-Review: H1\nReviewed-by: Jane\n"
              "AI-Review: A0\n")


def lines(root, path="solver.py"):
    """(AI review, findings level) of each line of a file."""
    r = next(r for r in Project(root).results() if r.path == path)
    out = {}
    for p in r.parts:
        for a, b in p.runs:
            for n in range(a, b + 1):
                out[n] = (p.declaration.ai, counted_findings(p.declaration, p.errors))
    return [out[n] for n in sorted(out)]


def lint(root, capsys, *args):
    capsys.readouterr()
    code = main(["--root", str(root), "lint", *args])
    return code, capsys.readouterr().out


def attestation(sha, findings="none", level="A2", path=None, model="GPT Sol (OpenAI), reviews/second.md"):
    return ("[[attestations]]\n" + f'commit = "{sha}"\n' + (f'path = "{path}"\n' if path else "")
            + f'AI-Review = "{level}"\nAI-Reviewed-by = "{model}"\nAI-Review-Findings = "{findings}"\n')


@pytest.fixture
def landed(repo):
    """solver.py: lines 3-5 landed with an A2 review that found a major problem."""
    write(repo, "reviews/r.md", "# review\n")
    edit_lines(repo, [3, 4, 5])
    sha = commit(repo, "AI change, reviewed", REVIEWED)
    return repo, sha


def test_the_review_folder_needs_no_declaration(landed):
    repo, _ = landed
    assert "reviews/r.md" not in Project(repo).files()
    write(repo, "SIGNOFF.toml", (repo / "SIGNOFF.toml").read_text() + '\n[review]\ndir = "audit"\n')
    assert "reviews/r.md" in Project(repo).files()


def test_a_commit_attestation_covers_the_lines_that_commit_landed(landed):
    repo, sha = landed
    edit_lines(repo, [4], "fixed")
    fix = commit(repo, "fix", UNREVIEWED)
    assert [f for _, f in lines(repo)][2:5] == ["F2", "F-", "F2"]
    # the second review checks the fix and the lines the finding was about: both commits
    write(repo, "reviews/second.md", "# second review\n")
    write(repo, "reviews/second.toml", attestation(sha) + "\n" + attestation(fix))
    commit(repo, "second review")
    got = lines(repo)
    assert [f for _, f in got] == ["F-", "F-", "F0", "F0", "F0", "F-", "F-", "F-", "F-", "F-"]
    assert got[3] == ("A2", "F0")  # the fix's line: raised from A0
    assert got[0] == ("A0", "F-")  # lines of neither commit stay as they were


def test_a_commit_attestation_doesnt_reach_later_changes(landed):
    repo, sha = landed
    write(repo, "reviews/second.md", "# second review\n")
    write(repo, "reviews/second.toml", attestation(sha))
    commit(repo, "second review")
    edit_lines(repo, [5], "later")
    commit(repo, "later", UNREVIEWED)
    assert [f for _, f in lines(repo)][2:5] == ["F0", "F0", "F-"]


def test_the_later_review_counts(landed):
    repo, sha = landed
    write(repo, "reviews/second.md", "# second review\n")
    write(repo, "reviews/second.toml", attestation(sha, "none"))
    commit(repo, "second review")
    write(repo, "reviews/third.md", "# third\n")
    write(repo, "reviews/a-third.toml", attestation(sha, "minor", model="GPT Sol (OpenAI), reviews/third.md"))
    commit(repo, "third review")  # added later, though its name sorts first
    assert [f for _, f in lines(repo)][2:5] == ["F1", "F1", "F1"]


def test_a_commit_attestation_can_name_one_file(landed):
    repo, sha = landed
    write(repo, "other.py", "x\n")
    edit_lines(repo, [1])
    both = commit(repo, "two files", UNREVIEWED)
    write(repo, "reviews/second.md", "# second review\n")
    write(repo, "reviews/second.toml", attestation(both, path="other.py"))
    commit(repo, "second review")
    assert lines(repo, "other.py") == [("A2", "F0")]
    assert lines(repo)[0] == ("A0", "F-")


def test_attestation_files_record_ai_reviews_only(repo):
    sha = git(repo, "rev-parse", "HEAD")
    write(repo, "reviews/x.toml", attestation(sha).replace('AI-Review = "A2"', 'Human-Review = "H3"\nReviewed-by = "P"\n'
                                                                                 'AI-Review = "A2"'))
    with pytest.raises(ConfigError, match="gives AI-Review, AI-Reviewed-by and AI-Review-Findings only"):
        load(repo)
    write(repo, "reviews/x.toml", attestation(sha, level="A0").replace('AI-Reviewed-by = "GPT Sol (OpenAI), '
                                                                       'reviews/second.md"\n', ""))
    with pytest.raises(ConfigError, match="must be A1, A2 or A3"):
        load(repo)
    write(repo, "reviews/x.toml", "[policy]\n'*' = { human = 'H0' }\n")
    with pytest.raises(ConfigError, match="holds \\[\\[attestations\\]\\] and \\[\\[commits\\]\\] tables only"):
        load(repo)
    write(repo, "reviews/x.toml", attestation(sha).replace(f'commit = "{sha}"\n', f'commit = "{sha}"\nblob = "{"a" * 40}"\n'))
    with pytest.raises(ConfigError, match="not both"):
        load(repo)


def test_lint_checks_the_record_of_an_attestation_file(landed, capsys):
    repo, sha = landed
    write(repo, "reviews/second.toml", attestation(sha))  # names a report that isn't there
    commit(repo, "second review")
    code, out = lint(repo, capsys)
    assert code == 1 and "reviews/second.toml [[attestations]] entry 1" in out and "review report" in out
    write(repo, "reviews/second.md", "# second review\n")
    write(repo, "reviews/third.toml", attestation("1234567"))
    commit(repo, "a review of no commit")
    code, out = lint(repo, capsys)
    assert code == 1 and "isn't a commit of the default branch's history" in out


def _pull_request(repo, capsys, body_text, *args):
    git(repo, "checkout", "-q", "--detach", "main")
    git(repo, "merge", "-q", "--no-ff", "pr", "-m", "preview")
    body = write(repo.parent, "body.md", body_text)
    return lint(repo, capsys, "--declare-from", str(body), "--base", "HEAD^1", *args)


def test_a_review_pull_request_declares_nothing(landed, capsys):
    repo, sha = landed
    git(repo, "checkout", "-q", "-b", "pr")
    write(repo, "reviews/second.md", "# second review\n")
    write(repo, "reviews/second.toml", attestation(sha))
    commit(repo, "second review")
    code, out = _pull_request(repo, capsys, "A second review of the change.\n")
    assert code == 0, out
    assert "it is a review, so its description needs no declaration" in out


def test_a_change_may_only_add_files_to_the_review_folder(landed, capsys):
    repo, _ = landed
    git(repo, "checkout", "-q", "-b", "pr")
    write(repo, "reviews/r.md", "# review, edited\n")
    commit(repo, "edit an earlier review")
    code, out = _pull_request(repo, capsys, "Fix a typo in the review.\n")
    assert code == 1 and "the change modifies reviews/r.md" in out and "may only add files" in out


def test_a_change_with_content_is_no_review(landed, capsys):
    repo, sha = landed
    git(repo, "checkout", "-q", "-b", "pr")
    write(repo, "reviews/second.md", "# second review\n")
    write(repo, "reviews/second.toml", attestation(sha))
    edit_lines(repo, [8], "and a fix")
    commit(repo, "a review that also fixes")
    code, out = _pull_request(repo, capsys, "A review.\n")
    assert code == 1 and "it is a review" not in out


def test_attest_commit_to_a_review_file(landed, capsys):
    repo, sha = landed
    write(repo, "reviews/second.md", "# second review\n")
    args = ["--root", str(repo), "attest", "--commit", sha[:7], "-a", "A2", "--findings", "none",
            "--ai-reviewed-by", "GPT Sol (OpenAI), reviews/second.md", "--to", str(repo / "reviews/second.toml")]
    assert main(args) == 0
    text = (repo / "reviews/second.toml").read_text()
    assert f'commit = "{sha}"' in text and "path" not in text.split("[[attestations]]")[1]
    assert main(args) == 2  # the file exists: a later review goes into a new one
    assert "write a new file" in capsys.readouterr().err
    commit(repo, "second review")
    assert [f for _, f in lines(repo)][2:5] == ["F0", "F0", "F0"]
    # a person's review goes into SIGNOFF.toml; --to is for the review folder only
    assert main(["--root", str(repo), "attest", str(repo / "solver.py"), "-H", "H3", "--reviewed-by", "P",
                 "--to", str(repo / "reviews/p.toml")]) == 2
    assert "goes into SIGNOFF.toml" in capsys.readouterr().err
    assert main(["--root", str(repo), "attest", str(repo / "solver.py"), "-a", "A1", "--findings", "none",
                 "--ai-reviewed-by", "Model", "--to", str(repo / "notes.toml")]) == 2
    assert "a .toml file in the review folder" in capsys.readouterr().err
