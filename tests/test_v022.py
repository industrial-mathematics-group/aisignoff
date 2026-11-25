"""0.22.0: the decisions D2 and D6 of the 1.0 contract. Every key of SIGNOFF.toml must be understood
(an unknown one is a typo or a key of a newer aisignoff), with requires-aisignoff to say which release
a repository needs; and a text file's lines follow git's line diff also after a binary version of it,
before the merge as after it."""
import json

import pytest

from aisignoff import config as config_module
from aisignoff.config import ConfigError, load

from test_review_018 import DECL, Repo, no_ci  # noqa: F401
from test_review_0193 import H3

TAIL = b"same line 2\nsame line 3\n"


# ------------------------------------------------------------------ D2: keys
@pytest.mark.parametrize("text, where", [
    ('version = 4\nfoo = 1\n', "SIGNOFF.toml: unknown key(s) foo"),
    ('version = 4\n[history]\nignore-whitespce = false\n', "[history]: unknown key(s) ignore-whitespce"),
    ('version = 4\n[review]\ndirectory = "r"\n', "[review]: unknown key(s) directory"),
    ('version = 4\n[[annotations]]\npath = "**"\nHuman-Reveiw = "H1"\n', "unknown key 'Human-Reveiw'"),
    ('version = 4\n[policy]\n"*" = { humans = "H1" }\n', "unknown key(s) humans"),
])
def test_every_unknown_key_is_an_error(tmp_path, text, where):
    (tmp_path / "SIGNOFF.toml").write_text(text)
    with pytest.raises(ConfigError) as e:
        load(tmp_path)
    assert where in str(e.value)


def test_requires_aisignoff(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "__version__", "1.1.4")
    for required in ("1.0", "1.1", "1.1.4", "0.21.0"):
        (tmp_path / "SIGNOFF.toml").write_text(f'version = 4\nrequires-aisignoff = "{required}"\n')
        load(tmp_path)
    for required in ("1.2", "1.1.5", "2.0"):
        (tmp_path / "SIGNOFF.toml").write_text(f'version = 4\nrequires-aisignoff = "{required}"\n')
        with pytest.raises(ConfigError, match=f"needs aisignoff {required} or later"):
            load(tmp_path)
    for bad in ('"latest"', '"1"', '">=1.2"', "1.2"):
        (tmp_path / "SIGNOFF.toml").write_text(f'version = 4\nrequires-aisignoff = {bad}\n')
        with pytest.raises(ConfigError, match="must be a version"):
            load(tmp_path)


def test_requires_aisignoff_comes_before_the_unknown_keys(tmp_path, monkeypatch):
    """A repository that uses a key of a newer release says so: the older one then names the release,
    not the key it doesn't know."""
    monkeypatch.setattr(config_module, "__version__", "1.0.0")
    (tmp_path / "SIGNOFF.toml").write_text('version = 4\nrequires-aisignoff = "1.3"\n[history]\nnew-setting = 1\n')
    with pytest.raises(ConfigError, match="needs aisignoff 1.3 or later"):
        load(tmp_path)


def test_a_development_version_doesnt_refuse(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "__version__", "0+unknown")
    (tmp_path / "SIGNOFF.toml").write_text('version = 4\nrequires-aisignoff = "9.9"\n')
    load(tmp_path)


# ------------------------------------------------------------------ D6: a text file after a binary one
@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("AISIGNOFF_NO_CACHE", "1")
    d = tmp_path / "repo"
    d.mkdir()
    return Repo(d)


def levels(r, *args):
    code, out = r.cli("report", "--json", *args)
    assert code == 0, out
    f = next(f for f in json.loads(out)["files"] if f["path"] == "data")
    return sorted((p["runs"], p["Human-Review"]) for p in f["parts"])


@pytest.mark.parametrize("before, attributes", [
    (b"\x00binary\n" + TAIL, ()),                         # binary to git and to aisignoff
    (b"x" * 10000 + b"\x00\n" + TAIL, ()),                # a text patch from git, binary by aisignoff's probe
    (b"\x00binary\n" + TAIL, ("data diff",)),             # an attribute makes git show a patch
    (b"\x00binary\n" + TAIL, ("data -diff",)),            # an attribute makes git leave the patch out
])
def test_the_check_before_the_merge_shows_what_lands(repo, tmp_path, before, attributes):
    if attributes:
        repo.write(".gitattributes", list(attributes))
    (repo.d / "data").write_bytes(before)
    repo.commit("add binary data\n\n" + DECL)
    repo.g("switch", "-qc", "feature")
    (repo.d / "data").write_bytes(b"new line 1\n" + TAIL)
    repo.commit("text")
    description = tmp_path / "description.md"
    description.write_text(H3)
    expected = [([[1, 1]], "H3"), ([[2, 3]], "H1")]  # lines 2 and 3 were in the binary version
    assert levels(repo, "--base", "main", "--declare-from", str(description)) == expected
    repo.g("switch", "-q", "main")
    repo.g("merge", "-q", "--no-ff", "feature", "-m", "Merge the text\n\n" + H3)
    assert levels(repo) == expected  # landed: git blame says the same
    code, out = repo.cli("diff", "main~1", "--json")
    assert code == 0, out
    total = json.loads(out)["total"]
    assert (total["added"], total["removed"]) == (1, 1)  # the binary unit removed, one line added


def test_a_binary_new_side_is_still_one_unit(repo, tmp_path):
    (repo.d / "data").write_bytes(b"old line 1\n" + TAIL)
    repo.commit("add text\n\n" + DECL)
    repo.g("switch", "-qc", "feature")
    (repo.d / "data").write_bytes(b"\x00binary\n" + TAIL)
    repo.commit("binary")
    description = tmp_path / "description.md"
    description.write_text(H3)
    assert levels(repo, "--base", "main", "--declare-from", str(description)) == [([[1, 1]], "H3")]
