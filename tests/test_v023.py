"""0.23.0: the findings of the independent review of 0.22.0 (reviews/2026-11-25-v0.22.0-fable.md). Git settings
that still changed the lines of a change, files that git converts before the merge, a binary old side counted
as one unit everywhere, a HEAD that git can't read, an AGENTS.md that isn't UTF-8, and diff with -w."""
import json
import os
import subprocess
import sys

import pytest

from aisignoff import visualize
from aisignoff.config import ConfigError, load

from test_review_018 import DECL, HIST, Repo, no_ci  # noqa: F401
from test_review_0193 import H3

TAIL = b"same line 2\nsame line 3\n"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("AISIGNOFF_NO_CACHE", "1")
    d = tmp_path / "repo"
    d.mkdir()
    return Repo(d)


def levels(r, path, *args, env=None):
    """Each line's human review, from report --json (runs expanded)."""
    out = subprocess.run([sys.executable, "-m", "aisignoff", "report", "--json", *args], cwd=r.d,
                         capture_output=True, text=True, env={**os.environ, **(env or {})})
    assert out.returncode == 0, out.stdout + out.stderr
    f = next(f for f in json.loads(out.stdout)["files"] if f["path"] == path)
    by_line = {}
    for p in f["parts"]:
        for first, last in p["runs"]:
            for n in range(first, last + 1):
                by_line[n] = p["Human-Review"]
    return [by_line[n] for n in sorted(by_line)]


def before_and_after(r, tmp_path, path, env=None):
    """The levels the check before the merge shows, and those after a merge commit declared the same way."""
    description = tmp_path / "description.md"
    description.write_text(H3)
    before = levels(r, path, "--base", "main", "--declare-from", str(description), env=env)
    r.g("switch", "-q", "main")
    r.g("merge", "-q", "--no-ff", "feature", "-m", "Merge\n\n" + H3)
    return before, levels(r, path, env=env)


def totals(r, base="main"):
    code, out = r.cli("diff", base, "--json")
    assert code == 0, out
    t = json.loads(out)["total"]
    return t["added"], t["removed"]


# ------------------------------------------------------------------ finding 4: git settings before the merge
LINES = [f"line {i}" for i in range(1, 21)]


def three_edits(r):
    r.write("f.txt", LINES)
    r.commit("lines\n\n" + DECL)
    r.g("switch", "-qc", "feature")
    r.write("f.txt", [f"new {i}" if i in (5, 8, 15) else f"line {i}" for i in range(1, 21)])
    r.commit("three edits")


EXPECTED = ["H3" if i in (5, 8, 15) else "H1" for i in range(1, 21)]


def test_inter_hunk_context_doesnt_join_the_changed_lines(repo, tmp_path):
    three_edits(repo)
    repo.g("config", "diff.interHunkContext", "10")
    assert before_and_after(repo, tmp_path, "f.txt") == (EXPECTED, EXPECTED)


def test_git_diff_opts_doesnt_widen_the_changed_lines(repo, tmp_path):
    three_edits(repo)
    assert before_and_after(repo, tmp_path, "f.txt", env={"GIT_DIFF_OPTS": "--unified=3"}) == (EXPECTED, EXPECTED)


# ------------------------------------------------------------------ finding 1: files git converts, before the merge
def utf16(r, name, text):
    (r.d / name).write_text(text, encoding="utf-16le")


def test_an_edited_utf16_file_shows_its_lines_before_the_merge(repo, tmp_path):
    repo.write(".gitattributes", ["*.txt working-tree-encoding=UTF-16LE"])
    utf16(repo, "notes.txt", "one\ntwo\nthree\nfour\n")
    repo.commit("notes\n\n" + DECL)
    repo.g("switch", "-qc", "feature")
    utf16(repo, "notes.txt", "one\nTWO\nthree\nfour\n")
    repo.commit("edit")
    expected = ["H1", "H3", "H1", "H1"]
    assert before_and_after(repo, tmp_path, "notes.txt") == (expected, expected)


def test_a_new_utf16_file_shows_its_lines_before_the_merge(repo, tmp_path):
    repo.write(".gitattributes", ["*.txt working-tree-encoding=UTF-16LE"])
    repo.commit("attributes\n\n" + DECL)
    repo.g("switch", "-qc", "feature")
    utf16(repo, "new.txt", "a\nb\nc\n")
    repo.commit("new file")
    assert before_and_after(repo, tmp_path, "new.txt") == (["H3"] * 3, ["H3"] * 3)


def test_a_renamed_utf16_file_keeps_its_lines_before_the_merge(repo, tmp_path):
    repo.write(".gitattributes", ["*.txt working-tree-encoding=UTF-16LE"])
    utf16(repo, "old.txt", "a\nb\nc\nd\n")
    repo.commit("notes\n\n" + DECL)
    repo.g("switch", "-qc", "feature")
    repo.g("mv", "old.txt", "renamed.txt")
    repo.commit("rename")
    assert before_and_after(repo, tmp_path, "renamed.txt") == (["H1"] * 4, ["H1"] * 4)


# ------------------------------------------------------------------ finding 2: a binary old side is one unit everywhere
def binary_to_text(r):
    """A binary file of three lines replaced by three other lines: git's text diff removes three."""
    (r.d / "data").write_bytes(b"\x00one\ntwo\nthree\n")
    r.commit("binary\n\n" + DECL)
    r.g("switch", "-qc", "feature")
    (r.d / "data").write_bytes(b"new 1\nnew 2\nnew 3\n")
    r.commit("text")


@pytest.mark.parametrize("toml", [
    HIST.replace("[history]\nenabled = true\ndefault-branch = \"main\"\n", ""),     # file-level declarations
    HIST + '\n[[annotations]]\npath = "data"\nprecedence = "override"\nAI-Generation = "G3"\nHuman-Review = "H1"\n'
           'AI-Review = "A0"\nAssisted-by = ["Claude Opus 5.5 (Anthropic)"]\nReviewed-by = ["Dev"]\n',
])
def test_diff_counts_a_binary_old_side_as_one_unit(tmp_path, monkeypatch, toml):
    monkeypatch.setenv("AISIGNOFF_NO_CACHE", "1")
    d = tmp_path / "repo"
    d.mkdir()
    r = Repo(d, toml)
    binary_to_text(r)
    assert totals(r) == (3, 1)  # three lines added, the binary unit removed


def test_the_report_since_a_commit_counts_a_binary_old_side_as_one_unit(repo):
    binary_to_text(repo)
    _, changes = visualize.changed_since(repo.d, "main", ["data"])
    assert changes["data"] == ([1, 2, 3], 1)


# ------------------------------------------------------------------ finding 9: a HEAD that git can't read
def test_a_head_that_git_cant_read_is_an_error(repo):
    (repo.d / "a.txt").write_text("x\n")
    sha = repo.commit("a\n\n" + DECL)
    loose = repo.d / ".git" / "objects" / sha[:2] / sha[2:]
    assert loose.is_file()
    loose.chmod(0o644)
    loose.unlink()  # the commit object is gone: HEAD names a commit git can't read
    code, out = repo.cli("lint")
    assert code == 2 and "can't read that commit" in out


def test_a_repository_without_commits_is_no_error(tmp_path, monkeypatch):
    monkeypatch.setenv("AISIGNOFF_NO_CACHE", "1")
    d = tmp_path / "repo"
    d.mkdir()
    subprocess.run(["git", "-C", str(d), "init", "-q", "-b", "main"], check=True)
    (d / "SIGNOFF.toml").write_text(HIST)
    (d / "a.txt").write_text("x\n")
    r = subprocess.run([sys.executable, "-m", "aisignoff", "lint"], cwd=d, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ------------------------------------------------------------------ finding 8: an AGENTS.md that isn't UTF-8
def test_an_agents_md_that_isnt_utf8(tmp_path):
    (tmp_path / "AGENTS.md").write_bytes(b"# Notes\n\xff\xfe\n")
    run = lambda *a: subprocess.run([sys.executable, "-m", "aisignoff", "--root", str(tmp_path), *a],  # noqa: E731
                                    capture_output=True, text=True)
    r = run("guide", "--agents-md")
    assert r.returncode == 2 and "not UTF-8" in r.stderr and "Traceback" not in r.stderr
    r = run("init")
    assert r.returncode == 2 and "not UTF-8" in r.stderr
    assert not (tmp_path / "SIGNOFF.toml").exists()  # init writes nothing when it can't do all of it


# ------------------------------------------------------------------ finding 10: diff with -w
def test_diff_doesnt_count_a_whitespace_only_change_as_added(repo):
    repo.write("f.py", ["def f():", "    return 1"])
    repo.commit("f\n\n" + DECL)
    repo.g("switch", "-qc", "feature")
    repo.write("f.py", ["def f():", "      return 1", "x = 2"])  # reindented, and one new line
    repo.commit("edit")
    assert totals(repo) == (1, 0)  # ignore-whitespace is on by default: the reindented line keeps its owner


# ------------------------------------------------------------------ finding 7: messages
@pytest.mark.parametrize("text", [
    'version = 4\n[policy]\nG9 = { human = "H1" }\n',
    'version = 4\n[policy]\n"*" = { humans = "H1" }\n',
])
def test_unknown_keys_in_the_policy_say_what_they_may_be(tmp_path, text):
    (tmp_path / "SIGNOFF.toml").write_text(text)
    with pytest.raises(ConfigError, match="a typo, or a key of a newer aisignoff"):
        load(tmp_path)


def test_unknown_keys_in_a_record_file_say_what_they_may_be(tmp_path):
    (tmp_path / "SIGNOFF.toml").write_text("version = 4\n")
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "r.toml").write_text('notes = "x"\n')
    with pytest.raises(ConfigError, match=r"unknown key\(s\) notes \(a typo, or a key of a newer aisignoff"):
        load(tmp_path)
