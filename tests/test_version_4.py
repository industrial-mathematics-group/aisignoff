"""Changing a repository over from SIGNOFF.toml version 3 (the AI review scale before 1.0.0rc6) to
version 4: what is read at version 3, the snapshot that keeps it, and examples/convert-to-version-4.py."""
import importlib.util
import json
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

    # 1. freeze with the new aisignoff, still at version 3: the commit messages so far are kept as read
    assert run(repo, capsys, "freeze")[0] == 0
    data = json.loads((repo / "SIGNOFF.snapshot.json").read_text())
    assert data["rules"] == 2 and not any("self-check" in json.dumps(d) for d in data["declarations"])
    commit(repo, "freeze", "AI-Generation: G0\nHuman-Review: H1\nReviewed-by: J\nAI-Review: A0")
    # 2. convert the file
    monkeypatch.chdir(repo)
    converter().main([])
    assert "version = 4" in (repo / "SIGNOFF.toml").read_text() and "Wrote SIGNOFF.toml" in capsys.readouterr().out
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


def test_a_snapshot_of_the_rules_before_is_read_on_todays_scale(repo, capsys):
    edit_lines(repo, [2])
    commit(repo, "reviewed", OLD.format(a="A1", by="M, new session"))
    assert run(repo, capsys, "freeze")[0] == 0
    path = repo / "SIGNOFF.snapshot.json"
    data = json.loads(path.read_text())
    data["rules"] = 1   # as 1.0.0rc5 wrote it: a self-check as A1, a new session as A2
    old = [d for d in data["declarations"] if d["AI-Review"] == "A1"]
    assert len(old) == 1
    old[0].update({"AI-Review": "A2"})
    data["declarations"].append({**old[0], "AI-Review": "A1", "AI-Reviewed-by": ["M, self-check by the generating session"]})
    runs = data["files"]["solver.py"]["runs"]
    first = next(r for r in runs if r[2] != data["declarations"].index(old[0]))
    first[2] = len(data["declarations"]) - 1
    path.write_text(json.dumps(data, indent=1) + "\n")
    commit(repo, "freeze with 1.0.0rc5", "AI-Generation: G0\nHuman-Review: H1\nReviewed-by: J\nAI-Review: A0")
    edit_lines(repo, [10])
    commit(repo, "later", OLD.format(a="A1", by="M, new session"))
    now = levels(repo)
    assert now[1] == "G3 H1 A1" and now[first[0] - 1] == "G3 H1 A0"
    code, out = run(repo, capsys, "lint")
    assert code == 0, out
    # the next freeze writes it on today's scale
    edit_lines(repo, [9])
    commit(repo, "and later", OLD.format(a="A1", by="M, new session"))
    assert run(repo, capsys, "freeze")[0] == 0
    data = json.loads(path.read_text())
    assert data["rules"] == 2 and "self-check" not in json.dumps(data["declarations"])
    assert levels(repo)[1] == "G3 H1 A1"


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
    "M again",
]

[[annotations]]
path = "docs/**"
AI-Generation = "G0"
Human-Review = "H2"
AI-Review = "A2"
Reviewed-by = "J"
AI-Reviewed-by = "N, new session"

[[commits]]
commit = "0123456789ab"
AI-Review = "A3"
AI-Reviewed-by = "N, benchmark"
'''


def test_the_converter_writes_what_version_3_was_read_as(tmp_path):
    new = converter().convert(TOML_3)
    assert new.startswith("version = 4   # the format\n") and "self-check" not in new and "M again" not in new
    assert 'AI-Review = "A0"   # checked itself\nAssisted-by = ["M"]\nReviewed-by = ["J"]\n\n[[annotations]]' in new
    assert '"*" = { human = "H1", ai = "A0" }   # every file\nG0  = { ai = "A1" }' in new
    assert 'G3  = { human = "H2", ai = "A1" }' in new
    assert 'AI-Review = "A1"\nReviewed-by = "J"\nAI-Reviewed-by = "N, new session"' in new
    assert 'AI-Review = "A3"\nAI-Reviewed-by = "N, benchmark"' in new
    before, after = (config.load_text(text, tmp_path / "SIGNOFF.toml") for text in (TOML_3, new))
    assert before.version_3 and not after.version_3 and not after.notes
    assert (before.annotations, before.policy, before.commits) == (after.annotations, after.policy, after.commits)
