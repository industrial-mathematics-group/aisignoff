"""The blame cache (.git/aisignoff) and what replaced the snapshot: every result with the cache is
the result without it, a run after the default branch moved on only blames the commits since, and
a leftover SIGNOFF.snapshot.json is reported."""
import gzip
import json

import pytest

from aisignoff import cache
from aisignoff.cli import main
from aisignoff.history import parse_message
from aisignoff.project import Project

from test_aisignoff import write
from test_history import G3, commit, edit_lines, git, repo  # noqa: F401
from test_history_edges import TEMPLATE, nested  # noqa: F401
from test_history_precedence import D, merge


def lines(root, use_cache=True, path=None):
    """Everything a line's result says: levels, names, findings, source and where each axis came from."""
    project = Project(root)
    project.use_cache = use_cache
    out = {}
    for r in project.results(quiet=True):
        if r.parts is None or (path and r.path != path):
            continue
        for p in r.parts:
            key = (json.dumps(p.declaration.as_dict(), sort_keys=True), p.declaration.source, p.kinds, tuple(p.errors))
            for a, b in p.runs:
                for n in range(a, b + 1):
                    out[(r.path, n)] = key
    return out


def files(root):
    return sorted((root / ".git" / "aisignoff").glob("blame-*.json.gz"))


def same(root):
    """The results with the cache (which fills it) are those without it."""
    cached = lines(root)
    assert cached == lines(root, use_cache=False)
    assert lines(root) == cached  # and again, now from the cache at this commit
    return cached


def test_the_cache_gives_the_results_of_the_whole_history(repo):
    edit_lines(repo, [2, 3])
    first = commit(repo, "AI change", G3)
    same(repo)
    assert [f.name for f in files(repo)] == [f"blame-{first}.json.gz"]
    # a pull request written on a branch, merged after the cached commit: blame of the writers too
    git(repo, "checkout", "-q", "-b", "pr")
    edit_lines(repo, [7], "agent")
    commit(repo, "agent", "AI-Generation: G3\nAssisted-by: M")
    git(repo, "checkout", "-q", "main")
    edit_lines(repo, [9], "main")
    commit(repo, "on main meanwhile", D("G0", "H2", "A0"))
    merge(repo, "pr", "Merge pull request #2 from o/pr\n\n" + D("G1", "H1", "A1"))
    got = same(repo)
    assert json.loads(got[("solver.py", 7)][0])["AI-Generation"] == "G3"  # the writer's generation
    # a rename with a change, then a correction and an attestation: none of it is in the cache
    git(repo, "mv", "solver.py", "core.py")
    edit_lines(repo, [1], "renamed", path="core.py")
    commit(repo, "rename", D("G0", "H3", "A0"))
    with open(repo / "SIGNOFF.toml", "a") as f:
        f.write(f'\n[[commits]]\ncommit = "{first}"\nHuman-Review = "H3"\nReviewed-by = "Rita"\n')
    commit(repo, "correct the AI change", D("G0", "H2", "A0"))
    got = same(repo)
    assert json.loads(got[("core.py", 2)][0])["Human-Review"] == "H3"
    assert len(files(repo)) == cache.KEEP


def test_the_cache_only_blames_the_commits_since(repo, monkeypatch):
    edit_lines(repo, [2])
    start = commit(repo, "AI change", G3)
    lines(repo)
    edit_lines(repo, [5])
    commit(repo, "later", D("G0", "H3", "A0"))
    calls = []
    real = __import__("aisignoff.history", fromlist=["History"]).History._blame

    def spy(self, rev, path, first_parent, stop):
        calls.append(stop)
        return real(self, rev, path, first_parent, stop)

    monkeypatch.setattr("aisignoff.history.History._blame", spy)
    assert lines(repo)[("solver.py", 2)] == lines(repo, use_cache=False)[("solver.py", 2)]
    assert calls[0] == start  # the first run after the move: from the cached commit on


def test_other_blame_options_or_a_broken_cache_file_dont_use_it(repo):
    edit_lines(repo, [2], "styled")
    style = commit(repo, "style", G3)
    expected = same(repo)
    # an ignore-revs file changes what blame says: the cache of other options isn't used
    write(repo, ".git-blame-ignore-revs", style + "\n")
    commit(repo, "ignore the style commit", D("G0", "H2", "A0"))
    after = same(repo)
    assert after[("solver.py", 2)] != expected[("solver.py", 2)]
    # a file that can't be read is left out
    for f in files(repo):
        f.write_bytes(b"not gzip")
    assert lines(repo) == after
    with gzip.open(files(repo)[0], "wt") as fh:
        json.dump({"format": cache.FORMAT, "key": "x"}, fh)
    assert lines(repo) == after


def test_no_cache_when_turned_off(repo, monkeypatch):
    monkeypatch.setenv("AISIGNOFF_NO_CACHE", "1")
    edit_lines(repo, [2])
    commit(repo, "AI change", G3)
    lines(repo)
    assert files(repo) == []


def test_the_cache_of_a_project_below_the_top_follows_renames(nested, capsys):
    root = nested / "paper"
    write(root, "a.py", "1\ntwo\n")
    commit(nested, "AI change", G3)
    same(root)
    git(nested, "mv", "paper/a.py", "paper/b.py")
    write(root, "b.py", "0\n1\ntwo\n")
    commit(nested, "rename and change", D("G0", "H3", "A0"))
    got = same(root)
    assert [json.loads(got[("b.py", n)][0])["AI-Generation"] for n in (1, 2, 3)] == ["G0", "G0", "G3"]


# ------------------------------------------------------------------ what replaced the snapshot
OLD_TEMPLATE = TEMPLATE.replace("**A1** A new AI session", "**A1** The AI that wrote the change checked its own work.")


def test_a_landed_commit_with_the_old_template_is_read_as_it_was_meant(repo, capsys):
    message = OLD_TEMPLATE.format(a2=" ", model="")
    assert "template before version 4" in parse_message(message, "J", "c")[0][2].problems[0]
    taken_over = parse_message(message, "J", "c", landed=True)[0][2]
    assert (taken_over.level, taken_over.names, taken_over.problems) == ("A0", (), ())
    edit_lines(repo, [2])
    commit(repo, message.split("\n", 1)[0], message.split("\n", 1)[1])
    r = next(r for r in Project(repo).results() if r.path == "solver.py")
    line2 = next(p for p in r.parts if any(a <= 2 <= b for a, b in p.runs))
    assert line2.declaration.short() == "G3 H1 A0" and line2.errors == []
    capsys.readouterr()
    assert main(["--root", str(repo), "lint"]) == 0


def test_a_leftover_snapshot_fails_lint(repo, capsys):
    write(repo, "SIGNOFF.snapshot.json", '{"format": 1}\n')
    commit(repo, "an old snapshot")
    capsys.readouterr()
    assert main(["--root", str(repo), "lint"]) == 1
    assert "SIGNOFF.snapshot.json is no longer read" in capsys.readouterr().out


@pytest.mark.parametrize("data", [b"", b"\x1f\x8b broken"])
def test_decode_of_a_bad_entry_is_no_hit(data, tmp_path):
    f = tmp_path / "blame-x.json.gz"
    f.write_bytes(data)
    assert cache.CacheRun._read(f) is None


def test_binary_files_and_symlinks_are_cached_and_follow_their_changes(repo):
    (repo / "logo.png").write_bytes(b"\x89PNG\x00one")
    (repo / "other.bin").write_bytes(b"\x00same")
    commit(repo, "AI images", G3)
    same(repo)
    # changed, renamed only (R100), and untouched after the cached commit
    (repo / "logo.png").write_bytes(b"\x89PNG\x00two")
    commit(repo, "a person redraws the logo", D("G0", "H3", "A0"))
    git(repo, "mv", "other.bin", "moved.bin")
    commit(repo, "move it", D("G0", "H2", "A0"))
    got = same(repo)
    assert json.loads(got[("logo.png", 1)][0])["AI-Generation"] == "G0"
    assert json.loads(got[("moved.bin", 1)][0])["AI-Generation"] == "G3"  # the rename keeps its content's commit
    # content changed and changed back: the commit that changed it back
    (repo / "logo.png").write_bytes(b"\x89PNG\x00one")
    commit(repo, "AI puts the old logo back", G3)
    assert json.loads(same(repo)[("logo.png", 1)][0])["AI-Generation"] == "G3"
    # a run after an unrelated commit keeps every file's commit for the next one
    edit_lines(repo, [4], "later")
    commit(repo, "unrelated", D("G0", "H2", "A0"))
    lines(repo)
    with gzip.open(max(files(repo), key=lambda f: f.stat().st_mtime), "rt") as fh:
        assert {"logo.png", "moved.bin"} <= set(json.load(fh)["units"])
