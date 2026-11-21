"""The finding of the independent review of 0.19.3: a text file whose patch git leaves out
('-diff', or a diff driver marked binary, in .gitattributes) keeps the provenance of its unchanged
lines, and a textconv driver doesn't change which lines changed."""
import json

import pytest

from test_review_018 import DECL, Repo, no_ci  # noqa: F401

H3 = DECL.replace("Human-Review: H1", "Human-Review: H3")
OLD = ["line 1", "line 2", "line 3", "line 4"]
NEW = ["line 1", "LINE 2", "line 3", "line 4"]


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("AISIGNOFF_NO_CACHE", "1")
    d = tmp_path / "repo"
    d.mkdir()
    return Repo(d)


def report(r, name, tmp_path):
    desc = tmp_path / "description.md"
    desc.write_text(H3)
    code, out = r.cli("report", "--json", "--base", "main", "--declare-from", str(desc))
    assert code == 0, out
    f = next(f for f in json.loads(out)["files"] if f["path"] == name)
    return [(p["runs"], p["Human-Review"]) for p in f["parts"]]


def totals(r):
    code, out = r.cli("diff", "main", "--json")
    assert code == 0, out
    t = json.loads(out)["total"]
    return t["added"], t["removed"]


EXPECTED = [([[1, 1], [3, 4]], "H1"), ([[2, 2]], "H3")]


def edit_line_2(r, attributes, rename=False):
    r.write(".gitattributes", attributes)
    r.write("data.txt", OLD)
    r.commit("add\n\n" + DECL)
    r.g("switch", "-qc", "feature")
    if rename:
        r.g("mv", "data.txt", "moved.txt")
    r.write("moved.txt" if rename else "data.txt", NEW)
    r.commit("edit line 2\n\n" + H3)


@pytest.mark.parametrize("attributes", [[], ["data.txt -diff"], ["data.txt binary"], ["data.txt diff=opaque"]])
def test_a_text_file_without_a_patch_keeps_its_unchanged_lines(repo, tmp_path, attributes):
    if attributes == ["data.txt diff=opaque"]:
        repo.g("config", "diff.opaque.binary", "true")
    edit_line_2(repo, attributes)
    assert sorted(report(repo, "data.txt", tmp_path)) == EXPECTED
    assert totals(repo) == (1, 1)


def test_a_renamed_text_file_without_a_patch_keeps_its_unchanged_lines(repo, tmp_path):
    edit_line_2(repo, ["*.txt -diff"], rename=True)
    assert sorted(report(repo, "moved.txt", tmp_path)) == EXPECTED
    assert totals(repo) == (1, 1)


def test_a_textconv_driver_doesnt_change_the_lines(repo, tmp_path):
    """A textconv filter that doubles the lines would otherwise move the changed line to line 3."""
    repo.g("config", "diff.double.textconv", "sed G")
    edit_line_2(repo, ["data.txt diff=double"])
    assert sorted(report(repo, "data.txt", tmp_path)) == EXPECTED
    assert totals(repo) == (1, 1)


def test_a_binary_file_replaced_with_text_is_still_all_new(repo, tmp_path):
    """The control: when one side really is binary, the text side's lines are all the change's."""
    repo.write(".gitattributes", ["data -diff"])
    (repo.d / "data").write_bytes(b"\x00binary\nline 2\nline 3\n")
    repo.commit("add\n\n" + DECL)
    repo.g("switch", "-qc", "feature")
    repo.write("data", ["new 1", "line 2", "line 3"])
    repo.commit("text\n\n" + H3)
    assert report(repo, "data", tmp_path) == [([[1, 3]], "H3")]
    assert totals(repo) == (3, 1)
