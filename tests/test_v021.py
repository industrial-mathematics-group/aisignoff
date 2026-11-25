"""0.21.0: what the 1.0 feasibility report found (reports/2026-11-25-1.0-feasibility.md). The exit codes
(2 when a command can't run, 3 for an internal error, never 1 for either), settings that name nothing,
a SIGNOFF.toml of a newer aisignoff, and results that don't depend on the machine's git configuration."""
import json
import subprocess

import pytest

from aisignoff import cli, history
from aisignoff.cli import main
from aisignoff.config import ConfigError, load

from test_aisignoff import write
from test_history import BASE_TOML, G3, commit, git, repo  # noqa: F401


def line_levels(root, path, capsys):
    """Each line's (generation, human review), worked out without the blame cache: a second run would
    otherwise read the first one's blames."""
    capsys.readouterr()
    with pytest.MonkeyPatch.context() as m:
        m.setenv("AISIGNOFF_NO_CACHE", "1")
        assert main(["--root", str(root), "report", "--json", "--files"]) == 0
    data = json.loads(capsys.readouterr().out)
    f = next(f for f in data["files"] if f["path"] == path)
    out = {}
    for part in f["parts"]:
        for first, last in part["runs"]:
            for n in range(first, last + 1):
                out[n] = (part["AI-Generation"], part["Human-Review"])
    return [out[n] for n in sorted(out)]


# ------------------------------------------------------------------ exit codes
def test_a_signoff_toml_that_isnt_utf8_is_a_configuration_error(tmp_path, capsys):
    (tmp_path / "SIGNOFF.toml").write_bytes(b"version = 4\n# \xff\xfe\n")
    with pytest.raises(ConfigError, match="not UTF-8"):
        load(tmp_path)
    assert main(["--root", str(tmp_path), "lint"]) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_a_signoff_toml_that_is_a_folder_is_a_configuration_error(tmp_path, capsys):
    (tmp_path / "SIGNOFF.toml").mkdir()
    assert main(["--root", str(tmp_path), "lint"]) == 2
    assert "can't be read" in capsys.readouterr().err


def test_a_file_that_cant_be_written_exits_with_2(tmp_path, capsys):
    write(tmp_path, "SIGNOFF.toml", BASE_TOML.replace("[history]\nenabled = true\n", ""))
    write(tmp_path, "a.txt", "x\n")
    write(tmp_path, "badges", "a file, not a folder\n")
    assert main(["--root", str(tmp_path), "badge", "--out", str(tmp_path / "badges")]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err and "badges" in err


def test_an_internal_error_exits_with_3_not_1(tmp_path, capsys, monkeypatch):
    write(tmp_path, "SIGNOFF.toml", BASE_TOML.replace("[history]\nenabled = true\n", ""))
    write(tmp_path, "a.txt", "x\n")

    def broken(args):
        raise KeyError("a bug")

    monkeypatch.setattr(cli, "cmd_lint", broken)
    assert main(["--root", str(tmp_path), "lint"]) == 3
    err = capsys.readouterr().err
    assert "Traceback" in err and "internal error" in err and cli.ISSUES_URL in err


def test_a_signoff_toml_of_a_newer_aisignoff_says_so(tmp_path):
    (tmp_path / "SIGNOFF.toml").write_text("version = 5\n")
    with pytest.raises(ConfigError, match="newer aisignoff"):
        load(tmp_path)


# ------------------------------------------------------------------ settings that name nothing
@pytest.mark.parametrize("setting, message", [
    ('default-branch = "trunk"', "no branch trunk"),
    ('ignore-revs-file = "nope"', "nope does not exist"),
    ('require-trailers-since = "0000000"', "not a commit of the default branch"),
])
@pytest.mark.parametrize("command", [["lint"], ["report"], ["badge", "--out", "b"]])
def test_a_setting_that_names_nothing_stops_every_command(repo, capsys, setting, message, command):
    text = (repo / "SIGNOFF.toml").read_text().replace("enabled = true", f"enabled = true\n{setting}")
    (repo / "SIGNOFF.toml").write_text(text)
    if command[0] == "badge":
        command = ["badge", "--out", str(repo / "b")]
    assert main(["--root", str(repo), *command]) == 2
    assert message in capsys.readouterr().err


# ------------------------------------------------------------------ the machine's git
INDENT_BEFORE = "{\n    pass\n}\n    return x\n    pass\n"
INDENT_AFTER = "{\n    pass\n}\n    return x\n    x += 1\n    return x\n    pass\n"


def test_the_users_indent_heuristic_doesnt_move_lines(repo, capsys):
    write(repo, "f.py", INDENT_BEFORE)
    commit(repo, "before")
    write(repo, "f.py", INDENT_AFTER)
    commit(repo, "after", G3)
    # the example is one where git's blame differs with and without the heuristic
    blames = {v: [row[:8] for row in git(repo, "-c", f"diff.indentHeuristic={v}", "blame", "-s", "f.py").splitlines()]
              for v in ("true", "false")}
    assert blames["true"] != blames["false"]
    expected = line_levels(repo, "f.py", capsys)
    git(repo, "config", "diff.indentHeuristic", "false")
    assert line_levels(repo, "f.py", capsys) == expected


def test_a_text_conversion_neither_moves_lines_nor_stops_the_run(repo, capsys):
    write(repo, "f.txt", "".join(f"line {i}\n" for i in range(1, 7)))
    commit(repo, "before")
    write(repo, "f.txt", "".join(f"line {i}\n" if i != 4 else "new 4\n" for i in range(1, 7)))
    commit(repo, "after", G3)
    expected = line_levels(repo, "f.txt", capsys)
    assert expected.count(("G3", "H1")) == 1
    write(repo, ".git/info/attributes", "f.txt diff=conv\n")
    git(repo, "config", "diff.conv.textconv", "sed 1,2d")  # drops two lines: would move every line by two
    assert line_levels(repo, "f.txt", capsys) == expected
    git(repo, "config", "diff.conv.textconv", "false")  # fails, as git-crypt does while the repository is locked
    assert line_levels(repo, "f.txt", capsys) == expected


def test_replace_refs_dont_change_the_history_read(repo, capsys):
    write(repo, "solver.py", "".join(f"line {i}\n" if i != 2 else "new 2\n" for i in range(1, 11)))
    sha = commit(repo, "AI change", G3)
    expected = line_levels(repo, "solver.py", capsys)
    tree, parent = git(repo, "rev-parse", f"{sha}^{{tree}}"), git(repo, "rev-parse", f"{sha}^")
    forged = subprocess.run(["git", "-C", str(repo), "commit-tree", tree, "-p", parent, "-m",
                             "forged\n\nAI-Generation: G0\nHuman-Review: H3\nAI-Review: A0\nReviewed-by: Mallory"],
                            capture_output=True, text=True, check=True).stdout.strip()
    git(repo, "replace", sha, forged)
    assert git(repo, "log", "-1", "--format=%s") == "forged"  # git itself now shows the forged message
    assert line_levels(repo, "solver.py", capsys) == expected


def test_an_old_git_is_refused(repo, capsys, monkeypatch):
    monkeypatch.setattr(history, "git_version", lambda: (2, 30, 2))
    assert main(["--root", str(repo), "lint"]) == 2
    assert "git 2.30.2 is too old" in capsys.readouterr().err


def test_the_git_version_is_part_of_the_cache_key(repo, monkeypatch):
    from aisignoff.cache import BlameCache
    from aisignoff.config import load as load_config

    def key(version):
        monkeypatch.setattr(history, "git_version", lambda: version)
        h = history.History(repo, load_config(repo))
        return BlameCache(repo).open(h).key

    assert key((2, 47, 3)) != key((2, 48, 0))


# ------------------------------------------------------------------ smaller findings
def test_guide_skills_in_a_folder_given_is_relative_to_where_it_runs(tmp_path, monkeypatch, capsys):
    project, here = tmp_path / "project", tmp_path / "here"
    project.mkdir()
    here.mkdir()
    monkeypatch.chdir(here)
    assert main(["--root", str(project), "guide", "--skills", "skills"]) == 0
    assert (here / "skills" / "aisignoff-dev" / "SKILL.md").is_file()
    assert not (project / "skills").exists()
    assert main(["--root", str(project), "guide", "--skills"]) == 0  # the default: the repository's .claude/skills
    assert (project / ".claude" / "skills" / "aisignoff-review" / "SKILL.md").is_file()


def test_init_no_longer_suggests_excluding_the_review_folder(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "init", "--no-agents-md"]) == 0
    assert "reviews/**" not in (tmp_path / "SIGNOFF.toml").read_text(encoding="utf-8")
