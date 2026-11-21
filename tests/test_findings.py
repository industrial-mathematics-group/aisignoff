"""The findings axis: the highest finding that the last independent AI review (A1-A3) of a line
left open, F0-F3, and F- for lines that no such review has covered since they last changed. A
finding is recorded, never a threshold: lint passes with it."""
import json

import pytest

from aisignoff import visualize
from aisignoff.cli import main
from aisignoff.model import counted_findings
from aisignoff.project import Project

from test_aisignoff import write
from test_history import BASE_TOML, commit, edit_lines, git, repo  # noqa: F401

REVIEWED = ("AI-Generation: G3\nAssisted-by: Claude Opus (Anthropic)\nHuman-Review: H1\nReviewed-by: Jane\n"
            "AI-Review: A2\nAI-Reviewed-by: GPT Sol (OpenAI), reviews/r.md\nAI-Review-Findings: {findings}\n")
UNREVIEWED = ("AI-Generation: G3\nAssisted-by: Claude Opus (Anthropic)\nHuman-Review: H1\nReviewed-by: Jane\n"
              "AI-Review: A0\n")


def reviewed(findings):
    return REVIEWED.format(findings=findings)


def findings(root, path="solver.py"):
    """The findings level of each line of a file."""
    r = next(r for r in Project(root).results() if r.path == path)
    out = []
    for p in r.parts:
        for a, b in p.runs:
            out += [(n, counted_findings(p.declaration, p.errors)) for n in range(a, b + 1)]
    return [lv for _, lv in sorted(out)]


def lint(root, capsys, *args):
    capsys.readouterr()
    code = main(["--root", str(root), "lint", *args])
    return code, capsys.readouterr().out


@pytest.fixture
def landed(repo):
    """solver.py: lines 3-5 landed with a review that found a major problem."""
    write(repo, "reviews/r.md", "# review\n")
    edit_lines(repo, [3, 4, 5])
    commit(repo, "AI change, reviewed", reviewed("major"))
    return repo


def test_a_finding_is_recorded_not_a_threshold(landed, capsys):
    assert findings(landed) == ["F-", "F-", "F2", "F2", "F2", "F-", "F-", "F-", "F-", "F-"]
    code, out = lint(landed, capsys)
    assert code == 0, out


def test_lines_a_later_change_touches_go_back_to_unreviewed(landed):
    # the fix without a review of its own: the fixed line is unreviewed, never clean
    edit_lines(landed, [4], "fixed")
    commit(landed, "fix", UNREVIEWED)
    assert findings(landed)[2:5] == ["F2", "F-", "F2"]
    # a pull request without a review leaves the other lines as they are
    edit_lines(landed, [9], "more")
    commit(landed, "unrelated", UNREVIEWED)
    assert findings(landed)[2:5] == ["F2", "F-", "F2"] and findings(landed)[8] == "F-"


def test_only_a_new_review_sets_its_lines_clean(landed):
    edit_lines(landed, [3, 4, 5], "fixed")
    commit(landed, "fix, reviewed again", reviewed("none"))
    assert findings(landed)[2:5] == ["F0", "F0", "F0"]
    edit_lines(landed, [7], "next")
    commit(landed, "next, a minor finding", reviewed("minor"))
    edit_lines(landed, [8], "trivial")
    commit(landed, "a trivial finding counts as clean", reviewed("trivial"))
    edit_lines(landed, [9], "critical")
    commit(landed, "a critical finding", reviewed("critical"))
    assert findings(landed)[6:9] == ["F1", "F0", "F3"]


def test_an_a1_review_gives_findings(repo):
    # a context-free check by the same model is a reference for what a different model finds
    a1 = UNREVIEWED.replace("A0\n", "A1\nAI-Reviewed-by: Claude Opus, new session\n")
    edit_lines(repo, [1])
    commit(repo, "A1 with a findings line", a1 + "AI-Review-Findings: none\n")
    edit_lines(repo, [2])
    commit(repo, "A1, a major finding", a1 + "AI-Review-Findings: major\n")
    # a commit of A1 without the line (from before A1 gave findings) leaves its lines at F-
    edit_lines(repo, [3])
    commit(repo, "A1 without a findings line", a1)
    assert findings(repo)[:3] == ["F0", "F2", "F-"]
    # A0 has no findings: its line isn't read
    edit_lines(repo, [4])
    commit(repo, "A0 with a findings line", UNREVIEWED + "AI-Review-Findings: none\n")
    assert findings(repo)[3] == "F-"


def test_an_attestation_is_a_review_of_the_whole_file(landed, capsys, monkeypatch):
    monkeypatch.chdir(landed)
    # a review of the file as it is: its findings for every line, the newer ones over the commit's
    assert main(["--root", str(landed), "attest", "solver.py", "-a", "A2", "--findings", "minor",
                 "--ai-reviewed-by", "GPT Sol (OpenAI), reviews/file.md"]) == 0
    commit(landed, "attest", UNREVIEWED.replace("G3\nAssisted-by: Claude Opus (Anthropic)", "G0"))
    assert findings(landed) == ["F1"] * 10
    # an A1 attestation is a review too: the newest review counts, not the highest level
    assert main(["--root", str(landed), "attest", "solver.py", "-a", "A1", "--findings", "none",
                 "--ai-reviewed-by", "Claude Opus, new session"]) == 0
    assert findings(landed) == ["F0"] * 10
    # what changes after it is unreviewed again
    edit_lines(landed, [6], "after")
    commit(landed, "after the attestation", UNREVIEWED)
    assert findings(landed)[5] == "F-" and findings(landed)[4] == "F0"


def test_attest_needs_the_findings_of_an_independent_review(repo, capsys, monkeypatch):
    monkeypatch.chdir(repo)
    capsys.readouterr()
    assert main(["--root", str(repo), "attest", "solver.py", "-a", "A2", "--ai-reviewed-by", "GPT Sol (OpenAI)"]) == 2
    assert "give --findings" in capsys.readouterr().err
    assert main(["--root", str(repo), "attest", "solver.py", "-a", "A1", "--ai-reviewed-by", "Claude Opus, new session"]) == 2
    assert "an AI review of A1 records what it found: give --findings" in capsys.readouterr().err
    assert main(["--root", str(repo), "attest", "solver.py", "-a", "A0", "--findings", "none"]) == 2
    assert "-a A1, A2 or A3" in capsys.readouterr().err


def test_an_older_review_recorded_later_doesnt_replace_a_newer_one(landed, capsys, monkeypatch):
    # the review of the newest content counts, however late an older review is recorded with --at
    monkeypatch.chdir(landed)
    old = git(landed, "rev-parse", "HEAD")
    edit_lines(landed, [7], "later")
    commit(landed, "later change", UNREVIEWED)
    args = ["--root", str(landed), "attest", "solver.py", "-a", "A2"]
    assert main([*args, "--findings", "major", "--ai-reviewed-by", "GPT Sol (OpenAI), reviews/new.md"]) == 0
    commit(landed, "attest the current file", UNREVIEWED.replace("G3\nAssisted-by: Claude Opus (Anthropic)", "G0"))
    assert findings(landed) == ["F2"] * 10
    assert main([*args, "--at", old, "--findings", "none", "--ai-reviewed-by", "GPT Sol (OpenAI), reviews/old.md"]) == 0
    assert findings(landed) == ["F2"] * 10
    r = next(r for r in Project(landed).results() if r.path == "solver.py")
    assert {p.declaration.get("AI-Reviewed-by")[0] for p in r.parts} == {"GPT Sol (OpenAI), reviews/new.md"}


def test_init_refuses_findings_without_levels(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "init", "--findings", "major"]) == 2
    assert "--findings goes with the levels" in capsys.readouterr().err
    assert not (tmp_path / "SIGNOFF.toml").exists()


def test_diff_lists_the_findings_of_an_attestation(landed, capsys, monkeypatch):
    monkeypatch.chdir(landed)
    base = git(landed, "rev-parse", "HEAD")
    assert main(["--root", str(landed), "attest", "solver.py", "-a", "A2", "--findings", "major",
                 "--ai-reviewed-by", "GPT Sol (OpenAI), reviews/file.md"]) == 0
    capsys.readouterr()
    assert main(["--root", str(landed), "diff", base]) == 0
    assert "solver.py  A2, findings: major" in capsys.readouterr().out
    assert main(["--root", str(landed), "diff", base, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["attested"][0]["findings"] == "major"


def test_a_commits_entry_corrects_the_findings(landed):
    sha = git(landed, "rev-parse", "HEAD")
    text = (landed / "SIGNOFF.toml").read_text()
    write(landed, "SIGNOFF.toml", text + f'\n[[commits]]\ncommit = "{sha[:12]}"\nAI-Review = "A2"\n'
                                         'AI-Reviewed-by = ["GPT Sol (OpenAI), reviews/r.md"]\nAI-Review-Findings = "critical"\n')
    assert findings(landed)[2:5] == ["F3"] * 3


def test_a_misspelt_findings_line_leaves_the_lines_unreviewed(repo, capsys):
    write(repo, "reviews/r.md", "# review\n")
    edit_lines(repo, [1])
    commit(repo, "typo", reviewed("none").replace("AI-Review-Findings:", "AI-Review-Finding:"))
    assert findings(repo)[0] == "F-"
    code, out = lint(repo, capsys)
    assert code == 0 and "its lines stay at F-" in out


def test_an_invalid_findings_line_of_a_landed_commit_fails(repo, capsys):
    write(repo, "reviews/r.md", "# review\n")
    edit_lines(repo, [1])
    commit(repo, "high", reviewed("high"))
    code, out = lint(repo, capsys)
    assert code == 1 and "invalid AI-Review-Findings 'high'" in out


def test_reports_show_the_findings_axis(landed, capsys, tmp_path):
    tree = visualize.build_tree(landed, Project(landed).results())
    solver = next(c for c in tree["children"] if c["name"] == "solver.py")
    assert solver["counts"]["Findings"]["lines"] == {"F2": 3, "F-": 7}
    # reviews/r.md, landed with it, is in the review folder: a record, not content
    assert tree["counts"]["Findings"]["files"]["F2"] == pytest.approx(0.3)
    assert "Findings" in visualize.render_text(tree).splitlines()[0]
    capsys.readouterr()
    assert main(["--root", str(landed), "report"]) == 0
    out = capsys.readouterr().out
    assert "Findings (of the last independent AI review)" in out and "F2" in out and "Major finding open" in out
    assert main(["--root", str(landed), "report", "--html", str(tmp_path.parent / f"{tmp_path.name}-r.html")]) == 0
    html = (tmp_path.parent / f"{tmp_path.name}-r.html").read_text()
    assert '"key":"Findings"' in html and '"unset":"F-"' in html and "GAP" not in html
    assert main(["--root", str(landed), "badge", "--out", str(tmp_path.parent / f"{tmp_path.name}-badges"), "--weight", "lines"]) == 0
    badge = json.loads((tmp_path.parent / f"{tmp_path.name}-badges" / "aisignoff-findings.json").read_text())
    assert badge["color"] == "orange" and badge["message"].startswith("F2 "), badge


def test_without_history_an_annotation_gives_the_findings(tmp_path):
    write(tmp_path, "SIGNOFF.toml", 'version = 4\n[[annotations]]\npath = "**"\nAI-Generation = "G0"\n'
                                    'Human-Review = "H1"\nReviewed-by = "J"\nAI-Review = "A2"\n'
                                    'AI-Reviewed-by = "GPT Sol (OpenAI)"\nAI-Review-Findings = "minor"\n')
    write(tmp_path, "a.py", "x\n")
    (r,) = Project(tmp_path).results()
    assert counted_findings(r.declaration, r.errors) == "F1"
