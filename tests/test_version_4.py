"""Changing a repository over from SIGNOFF.toml version 3 (the AI review scale before 1.0.0rc6) to
version 4: what is read at version 3, and examples/convert-to-version-4.py, which keeps the AI reviews
of the commit messages so far with [[commits]] entries."""
import importlib.util
from pathlib import Path

import pytest

from aisignoff import config

from test_history import commit, edit_lines, git, repo  # noqa: F401
from test_review_012 import levels, run

OLD = ("AI-Generation: G3\nAssisted-by: M\nHuman-Review: H1\nReviewed-by: J\n"
       "AI-Review: {a}\nAI-Reviewed-by: {by}")


def converter():
    path = Path(__file__).parent.parent / "examples/convert-to-version-4.py"
    spec = importlib.util.spec_from_file_location("convert_to_version_4", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_repository_keeps_its_levels_through_the_change_to_version_4(repo, capsys, monkeypatch):
    toml = (repo / "SIGNOFF.toml").read_text().replace("version = 4", "version = 3")
    (repo / "SIGNOFF.toml").write_text(toml)
    edit_lines(repo, [2])
    commit(repo, "agent", OLD.format(a="A1", by="M, self-check by the generating session"))
    edit_lines(repo, [3])
    commit(repo, "reviewed", OLD.format(a="A2", by="M, new session"))
    before = levels(repo)
    assert (before[1], before[2]) == ("G3 H1 A0", "G3 H1 A1")
    code, out = run(repo, capsys, "lint")
    assert code == 0 and "version = 3" in out and "convert-to-version-4.py" in out   # a note, no failure
    assert run(repo, capsys, "attest", "solver.py", "-a", "A1", "--ai-reviewed-by", "N, new session")[0] == 2

    # convert the file: the commit messages so far keep their AI review through [[commits]] entries
    monkeypatch.chdir(repo)
    converter().main([])
    toml = (repo / "SIGNOFF.toml").read_text()
    assert "version = 4" in toml and "Wrote SIGNOFF.toml" in capsys.readouterr().out
    assert toml.count("[[commits]]") == 2 and "self-check" not in toml.split("[[commits]]", 1)[1]
    commit(repo, "version 4", "AI-Generation: G0\nHuman-Review: H1\nReviewed-by: J\nAI-Review: A0")
    assert levels(repo) == before
    code, out = run(repo, capsys, "lint", "--strict")
    assert code == 0 and "version = 3" not in out
    # from here on, a commit message is on today's scale
    edit_lines(repo, [4])
    commit(repo, "after", OLD.format(a="A1", by="M, self-check by the generating session"))
    code, out = run(repo, capsys, "lint")
    assert code == 1 and "self-check" in out
    with pytest.raises(SystemExit, match="not version 3"):
        converter().main([])


TOML_3 = '''version = 3   # the format
exclude = ["reviews/**"]

[policy]
"*" = { human = "H1", ai = "A1" }   # every file
G3  = { human = "H2", ai = "A2" }

[[annotations]]
path = "**"
AI-Generation = "G3"
Human-Review = "H1"
AI-Review = "A1"   # checked itself
Assisted-by = ["M"]
Reviewed-by = ["J"]
AI-Reviewed-by = [
    "M, self-check by the generating session",   # an array over several lines
    "M again [in PR #12]",
]

[[annotations]]
path = "docs/**"
AI-Generation = "G0"
Human-Review = "H2"
AI-Review = "A2"
Reviewed-by = "J"
AI-Reviewed-by = "N, new session"

[[annotations]]
path = "src/**"
AI-Generation = "G2"
Human-Review = "H1"
AI-Review = "A1"
Assisted-by = "M"
AI-Reviewed-by = "M, self-check in PR #12 [see there]"   # a "#" and a "]" inside the string
Reviewed-by = "J"

[[commits]]
commit = "0123456789ab"
AI-Review = "A3"
AI-Reviewed-by = "N, benchmark"
'''


def test_the_converter_writes_what_version_3_was_read_as(tmp_path):
    new = converter().convert(TOML_3)
    assert new.startswith("version = 4   # the format\n") and "self-check" not in new and "M again" not in new and "PR #12" not in new
    assert 'AI-Review = "A0"   # checked itself\nAssisted-by = ["M"]\nReviewed-by = ["J"]\n\n[[annotations]]' in new
    assert '"*" = { human = "H1", ai = "A0" }   # every file\nG0  = { ai = "A1" }' in new
    assert 'G3  = { human = "H2", ai = "A1" }' in new
    assert 'AI-Review = "A1"\nReviewed-by = "J"\nAI-Reviewed-by = "N, new session"' in new
    assert 'AI-Review = "A3"\nAI-Reviewed-by = "N, benchmark"' in new
    before, after = (config.load_text(text, tmp_path / "SIGNOFF.toml") for text in (TOML_3, new))
    assert before.version_3 and not after.version_3 and not after.notes
    assert (before.annotations, before.policy, before.commits) == (after.annotations, after.policy, after.commits)
