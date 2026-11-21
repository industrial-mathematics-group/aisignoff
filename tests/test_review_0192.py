"""The findings of the independent reviews of 0.19.2 and of history.py: a binary file replaced
with text (or text with a binary) changes all its lines, a name that starts with a newline still
invalidates its cached commit, and a cache written before 0.19.3 isn't used."""
import gzip
import json

import pytest

from aisignoff import cache
from aisignoff.project import Project
from test_review_018 import DECL, Repo, no_ci  # noqa: F401

H3 = DECL.replace("Human-Review: H1", "Human-Review: H3")


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    return Repo(d)


def human(r, name):
    return {x.path: x for x in Project(r.d).results(quiet=True)}[name].declaration.get("Human-Review")


def runs(r, name, tmp_path, declaration):
    desc = tmp_path / "description.md"
    desc.write_text(declaration)
    code, out = r.cli("report", "--json", "--base", "main", "--declare-from", str(desc))
    assert code == 0, out
    f = next(f for f in json.loads(out)["files"] if f["path"] == name)
    return [(p["runs"], p["Human-Review"]) for p in f["parts"]]


def totals(r, base="main"):
    code, out = r.cli("diff", base, "--json")
    assert code == 0, out
    t = json.loads(out)["total"]
    return t["added"], t["removed"]


# ------------------------------------------------------------------ a binary file replaced with text
def test_text_that_replaces_a_binary_file_is_all_the_change(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("AISIGNOFF_NO_CACHE", "1")
    (repo.d / "data").write_bytes(b"\x00binary\nold line 2\nold line 3\n")
    repo.commit("add a binary\n\n" + DECL)
    repo.g("switch", "-qc", "feature")
    repo.write("data", ["new line 1", "new line 2", "new line 3"])
    repo.commit("replace it with text\n\n" + H3)
    assert runs(repo, "data", tmp_path, H3) == [([[1, 3]], "H3")]
    assert totals(repo) == (3, 1)


def test_a_binary_file_that_replaces_text_removes_all_its_lines(repo):
    repo.write("data", ["old line 1", "old line 2", "old line 3"])
    repo.commit("add text\n\n" + DECL)
    (repo.d / "data").write_bytes(b"\x00binary\nnew\n")
    assert totals(repo, "HEAD") == (1, 3)


# ------------------------------------------------------------------ the cache
def test_the_cache_sees_an_edit_of_a_file_whose_name_starts_with_a_newline(repo, monkeypatch):
    monkeypatch.delenv("AISIGNOFF_NO_CACHE", raising=False)
    name = "\nreport.bin"
    (repo.d / name).write_bytes(b"\x00first")
    repo.commit("add\n\n" + DECL)
    assert human(repo, name) == "H1"  # warms the cache
    (repo.d / name).write_bytes(b"\x00second")
    repo.commit("edit\n\n" + H3)
    assert human(repo, name) == "H3"
    monkeypatch.setenv("AISIGNOFF_NO_CACHE", "1")
    assert human(repo, name) == "H3"


def test_a_cache_written_before_the_fix_isnt_used(repo, monkeypatch):
    """0.19.1 could cache a stale commit for a binary file at the current commit; 0.19.2 read it as it
    was. A cache file of the earlier format is now ignored, so the upgrade needs no step."""
    monkeypatch.delenv("AISIGNOFF_NO_CACHE", raising=False)
    name = "données.bin"
    (repo.d / name).write_bytes(b"\x00first")
    first = repo.commit("add\n\n" + DECL)
    (repo.d / name).write_bytes(b"\x00second")
    repo.commit("edit\n\n" + H3)
    current = cache.FORMAT
    monkeypatch.setattr(cache, "FORMAT", 1)
    assert human(repo, name) == "H3"  # writes the cache at this commit, in the format before the fix
    [f] = sorted((repo.d / ".git" / "aisignoff").glob("blame-*.json.gz"))
    with gzip.open(f, "rt") as fh:  # as 0.19.1 left it: the binary file's commit is the one before the edit
        data = json.load(fh)
    data["shas"].append(first)
    data["units"][name] = len(data["shas"]) - 1
    with gzip.open(f, "wt") as fh:
        json.dump(data, fh)
    assert human(repo, name) == "H1"  # the control: read in that format, as 0.19.2 did
    monkeypatch.setattr(cache, "FORMAT", current)
    assert human(repo, name) == "H3"
