"""The major finding of the independent review of 0.20.0: git's diff and aisignoff's rule for
binary content (a NUL in the first BINARY_PROBE bytes) disagree near their probe boundaries. The
changed lines follow aisignoff's rule on both sides, by bytes, whatever git's patch shows. Since 0.22.0, a
text side takes git's line diff also after a binary one, as git blame does after the merge; a binary new
side is one unit."""
import pytest

from test_review_018 import DECL, Repo, no_ci  # noqa: F401
from test_review_0193 import H3, report, totals

TAIL = b"same line 2\nsame line 3\n"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("AISIGNOFF_NO_CACHE", "1")
    d = tmp_path / "repo"
    d.mkdir()
    return Repo(d)


def replace_line_1(r, before, after, attributes=()):
    if attributes:
        r.write(".gitattributes", list(attributes))
    (r.d / "data").write_bytes(before)
    r.commit("add\n\n" + DECL)
    r.g("switch", "-qc", "feature")
    (r.d / "data").write_bytes(after)
    r.commit("edit\n\n" + H3)


def test_a_nul_past_gits_probe_follows_git(repo, tmp_path):
    """git looks at 8000 bytes and shows a text patch; by aisignoff's 16 KiB probe the old file is
    one binary unit, but the new text's lines follow git's line diff: lines 2 and 3 keep their levels,
    and the binary unit counts as one removed."""
    replace_line_1(repo, b"x" * 10000 + b"\x00\n" + TAIL, b"new line 1\n" + TAIL)
    assert sorted(report(repo, "data", tmp_path)) == [([[1, 1]], "H3"), ([[2, 3]], "H1")]
    assert totals(repo) == (1, 1)


def test_text_becoming_binary_past_gits_probe(repo, tmp_path):
    """The other direction: the new file is binary by aisignoff's rule, the old one text."""
    replace_line_1(repo, b"old line 1\n" + TAIL, b"x" * 10000 + b"\x00\n" + TAIL)
    assert report(repo, "data", tmp_path) == [([[1, 1]], "H3")]
    assert totals(repo) == (1, 3)


@pytest.mark.parametrize("attributes", [(), ("data -diff",)])
def test_a_nul_past_the_probe_in_bytes_is_text(repo, tmp_path, attributes):
    """A NUL at byte 18000, after 9000 two-byte characters: within 16384 characters, but past the
    16384 bytes the probe reads, so the file is text and its unchanged lines keep their levels."""
    text = ("é" * 9000).encode() + b"\x00\n"
    assert len(text) > 16384 > 9000 + 1
    replace_line_1(repo, text + TAIL, b"new line 1\n" + TAIL, attributes)
    assert sorted(report(repo, "data", tmp_path)) == [([[1, 1]], "H3"), ([[2, 3]], "H1")]
    assert totals(repo) == (1, 1)


def test_a_binary_file_forced_to_text_by_attributes_follows_git(repo, tmp_path):
    """'diff' set in .gitattributes makes git show a text patch of binary content: the text side's lines
    follow it, and the binary old side counts as one unit removed."""
    replace_line_1(repo, b"\x00bin\n" + TAIL, b"new line 1\n" + TAIL, ["data diff"])
    assert sorted(report(repo, "data", tmp_path)) == [([[1, 1]], "H3"), ([[2, 3]], "H1")]
    assert totals(repo) == (1, 1)


def test_a_binary_edit_past_gits_probe_is_one_unit(repo, tmp_path):
    """Binary on both sides by aisignoff's rule, text to git: one unit removed and one added."""
    binary = b"x" * 10000 + b"\x00\n"
    replace_line_1(repo, binary + TAIL, binary + b"changed\n" + TAIL)
    assert report(repo, "data", tmp_path) == [([[1, 1]], "H3")]
    assert totals(repo) == (1, 1)
