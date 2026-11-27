"""0.25.0: the counts of `diff` that the reviews of 0.23.0 and 0.24.0 found wrong. A symlink is one unit
whatever its target text, and a binary version that is replaced counts as one removed unit, also where git's
text diff only inserts lines before it."""
import json
import os

import pytest

from test_review_018 import DECL, Repo, no_ci  # noqa: F401


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("AISIGNOFF_NO_CACHE", "1")
    d = tmp_path / "repo"
    d.mkdir()
    return Repo(d)


def totals(r, base="main"):
    code, out = r.cli("diff", base, "--json")
    assert code == 0, out
    t = json.loads(out)["total"]
    return t["added"], t["removed"]


def test_a_symlink_with_a_multiline_target_is_one_unit(repo):
    os.symlink("first\nold\nsecond", repo.d / "link")
    repo.commit("link\n\n" + DECL)
    repo.g("switch", "-qc", "feature")
    (repo.d / "link").unlink()
    os.symlink("other\nsecond\nthird", repo.d / "link")
    repo.commit("retarget")
    assert totals(repo) == (1, 1)


def test_a_new_symlink_with_a_multiline_target_is_one_unit(repo):
    repo.g("switch", "-qc", "feature")
    os.symlink("a\nb\nc", repo.d / "link")
    repo.commit("link")
    assert totals(repo) == (1, 0)


def test_a_binary_version_replaced_by_an_insertion_counts_one_removed_unit(repo):
    old = b"\x00bin\nline 2\n"
    (repo.d / "data").write_bytes(old)
    repo.commit("binary\n\n" + DECL)
    repo.g("switch", "-qc", "feature")
    (repo.d / "data").write_bytes(b"x" * 17000 + b"\n" + old)  # the NUL is now past the probe: text
    repo.commit("insert")
    assert totals(repo) == (1, 1)
